"""Account administration and operator-mediated single-use password recovery."""
import argparse
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from nexus.farm_app import local_accounts as accounts, scoped_access as access


def event(db, category, actor=None, affected=None, farm=None, summary='Local operator action', result='success'):
    db.execute('INSERT INTO nexus_security_events(recorded_at,actor_id,affected_id,farm_id,category,result,summary) VALUES (?,?,?,?,?,?,?)', (datetime.now(timezone.utc).isoformat(), actor, affected, farm, category, result, summary))


def operator(db, account_id):
    if type(account_id) is not int or not db.execute('SELECT 1 FROM nexus_platform_admins p JOIN nexus_accounts a ON a.id=p.account_id WHERE p.account_id=? AND a.disabled=0', (account_id,)).fetchone():
        raise access.AccessError('Platform administrator permission required')


def authenticated_operator(db, token, csrf=None):
    user = access.identity(db, token)
    operator(db, user['account_id'])
    if csrf is not None and (not isinstance(csrf, str) or not hmac.compare_digest(csrf.encode(), user['csrf'].encode())):
        raise access.AccessError('Refresh before submitting this account change')
    return user['account_id']


def protect_owner(db, account_id, farm_id=None):
    rows = db.execute("SELECT farm_id FROM nexus_farm_memberships WHERE account_id=? AND role='owner'", (account_id,)).fetchall()
    for row in rows:
        farm = row['farm_id']
        if farm_id is not None and farm != farm_id:
            continue
        other = db.execute("SELECT 1 FROM nexus_farm_memberships m JOIN nexus_accounts a ON a.id=m.account_id WHERE m.farm_id=? AND m.role='owner' AND a.disabled=0 AND a.id<>?", (farm, account_id)).fetchone()
        if not other:
            raise ValueError('Assign another enabled owner before removing or disabling this farm owner')


def bootstrap(database, account_id):
    with closing(accounts.connect(database)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM nexus_platform_admins').fetchone():
            raise ValueError('Platform administrator already bootstrapped; use the existing administrator')
        if type(account_id) is not int or not db.execute('SELECT 1 FROM nexus_accounts WHERE id=? AND disabled=0', (account_id,)).fetchone():
            raise ValueError('Choose an existing enabled account')
        db.execute('INSERT INTO nexus_platform_admins VALUES (?)', (account_id,))
        event(db, 'platform_admin_bootstrap', affected=account_id, summary='Privileged local CLI bootstrap')


def state(database, token, search='', status='all', offset=0):
    if not isinstance(search, str) or len(search)>64 or status not in ('all','enabled','disabled') or type(offset) is not int or not 0<=offset<=1000000:
        raise ValueError('Invalid account filter')
    with closing(accounts.connect(database)) as db, db:
        authenticated_operator(db, token)
        where="instr(username,?)>0 AND (?='all' OR disabled=?)"
        args=(search,status,1 if status=='disabled' else 0)
        rows=[dict(r) for r in db.execute('SELECT id,username,disabled,created_at,last_sign_in FROM nexus_accounts WHERE '+where+' ORDER BY id LIMIT 100 OFFSET ?',args+(offset,))]
        return {'accounts':rows,'total':db.execute('SELECT count(*) FROM nexus_accounts WHERE '+where,args).fetchone()[0], 'offset':offset, 'farms':[dict(r) for r in db.execute('SELECT id,name FROM farms ORDER BY id')], 'memberships':[dict(r) for r in db.execute('SELECT * FROM nexus_farm_memberships ORDER BY farm_id,account_id')], 'events':[dict(r) for r in db.execute('SELECT * FROM nexus_security_events ORDER BY id DESC LIMIT 100')], 'roles':sorted(accounts.ROLES)}


def change(database, token, csrf, data):
    if not isinstance(csrf,str) or not csrf:
        raise access.AccessError('Refresh before submitting this account change')
    with closing(accounts.connect(database)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        actor=authenticated_operator(db,token,csrf)
        op=data.get('operation'); target=data.get('account_id'); farm=data.get('farm_id')
        if op=='create':
            username=data.get('username'); password=data.get('password')
            accounts.validate_username(username)
            encoded=accounts.password_hash(password)
            try: target=db.execute('INSERT INTO nexus_accounts(username,password_hash,created_at) VALUES (?,?,?)',(username,encoded,datetime.now(timezone.utc).isoformat())).lastrowid
            except Exception as error:
                import sqlite3
                if isinstance(error,sqlite3.IntegrityError):raise ValueError('Username already exists') from None
                raise
        else:
            if type(target) is not int or not db.execute('SELECT 1 FROM nexus_accounts WHERE id=?',(target,)).fetchone():raise ValueError('Select an existing account')
            if op in ('grant','remove'):
                if type(farm) is not int or not db.execute('SELECT 1 FROM farms WHERE id=?',(farm,)).fetchone():raise ValueError('Select an existing farm')
                old=db.execute('SELECT role FROM nexus_farm_memberships WHERE account_id=? AND farm_id=?',(target,farm)).fetchone()
                role=data.get('role')
                if old and old['role']=='owner' and (op=='remove' or role!='owner'):protect_owner(db,target,farm)
                if op=='remove':db.execute('DELETE FROM nexus_farm_memberships WHERE account_id=? AND farm_id=?',(target,farm))
                else:
                    if not isinstance(role,str) or role not in accounts.ROLES:raise ValueError('Choose owner, editor or viewer')
                    if db.execute('SELECT disabled FROM nexus_accounts WHERE id=?',(target,)).fetchone()[0]:raise ValueError('Enable this account before assigning a farm')
                    db.execute('INSERT INTO nexus_farm_memberships VALUES (?,?,?) ON CONFLICT(account_id,farm_id) DO UPDATE SET role=excluded.role',(target,farm,role))
            elif op=='status':
                disabled=data.get('disabled')
                if type(disabled) is not bool:raise ValueError('Choose enabled or disabled')
                if disabled:
                    protect_owner(db,target)
                    if db.execute('SELECT 1 FROM nexus_platform_admins WHERE account_id=?',(target,)).fetchone() and not db.execute('SELECT 1 FROM nexus_platform_admins p JOIN nexus_accounts a ON a.id=p.account_id WHERE a.disabled=0 AND a.id<>?',(target,)).fetchone():raise ValueError('Cannot disable the last platform administrator')
                    db.execute('DELETE FROM nexus_sessions WHERE account_id=?',(target,))
                    db.execute('DELETE FROM nexus_password_resets WHERE account_id=?',(target,))
                db.execute('UPDATE nexus_accounts SET disabled=? WHERE id=?',(int(disabled),target))
            else:raise ValueError('Choose a supported administration operation')
        summary={'create':'Account created','grant':'Farm role assigned: '+str(data.get('role')),'remove':'Farm assignment removed','status':'Account disabled' if data.get('disabled') else 'Account enabled'}[op]
        event(db,'account_'+op,actor,target,farm if op in ('grant','remove') else None,summary)
        return {'account_id':target,'message':summary}


def issue_reset(database, actor, account_id, identity_basis, output):
    if not isinstance(identity_basis,str) or not 5<=len(identity_basis.strip())<=500:raise ValueError('Confirm identity independently and describe the verification basis (5–500 characters)')
    path=Path(output).expanduser().resolve()
    # Refuse to overwrite any file. Token is never returned to the dashboard or log.
    with closing(accounts.connect(database)) as db, db:
        db.execute('BEGIN IMMEDIATE');operator(db,actor)
        if type(account_id) is not int or not db.execute('SELECT 1 FROM nexus_accounts WHERE id=? AND disabled=0',(account_id,)).fetchone():raise ValueError('Choose an enabled account')
        token=secrets.token_urlsafe(32)
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as file:file.write(token+'\n')
            db.execute('DELETE FROM nexus_password_resets WHERE account_id=?',(account_id,))
            db.execute('INSERT INTO nexus_password_resets VALUES (?,?,?,NULL)',(access.digest(token),account_id,int(time.time())+900))
            event(db,'password_reset_issued',actor,account_id,summary='Operator confirmed independent identity check; token expires after 15 minutes')
            db.commit()
        except Exception:
            path.unlink(missing_ok=True)
            raise
    return {'message':'Reset credential written to the private file. Deliver privately and delete the file after use. Expires after 15 minutes.'}


def redeem(database, token, password):
    if not isinstance(token,str) or not 32<=len(token)<=128:raise access.AccessError('Reset credential is invalid or expired',400)
    now=int(time.time())
    with closing(accounts.connect(database)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT r.*,a.disabled,a.username FROM nexus_password_resets r JOIN nexus_accounts a ON a.id=r.account_id WHERE token_hash=?',(access.digest(token),)).fetchone()
        if not row or row['used_at'] is not None or row['expires_at']<=now or row['disabled']:raise access.AccessError('Reset credential is invalid or expired',400)
        target=row['account_id']
        encoded=accounts.password_hash(password)
        db.execute('UPDATE nexus_accounts SET password_hash=? WHERE id=?',(encoded,target))
        db.execute('UPDATE nexus_password_resets SET used_at=? WHERE account_id=?',(now,target))
        db.execute('DELETE FROM nexus_sessions WHERE account_id=?',(target,))
        db.execute('DELETE FROM nexus_login_attempts WHERE username_hash=?',(access.digest(row['username']),))
        event(db,'password_reset_completed',affected=target,summary='Password replaced; all existing sessions invalidated')
    return {'message':'Password changed. Sign in again with your new password.'}


def record_denial(database, token):
    # Record fixed summaries only; never echo submitted fields or cookie values.
    with closing(accounts.connect(database)) as db, db:
        try:actor=access.identity(db,token)['account_id']
        except access.AccessError:actor=None
        event(db,'administration_denied',actor=actor,summary='Account administration request denied',result='denied')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--database',required=True)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('list-local')
    boot=sub.add_parser('bootstrap-admin');boot.add_argument('--account-id',type=int,required=True)
    reset=sub.add_parser('issue-reset');reset.add_argument('--operator-id',type=int,required=True);reset.add_argument('--account-id',type=int,required=True);reset.add_argument('--identity-basis',required=True);reset.add_argument('--output',required=True)
    args=parser.parse_args()
    try:
        if args.command=='list-local':
            with closing(accounts.connect(args.database)) as db:
                print(json.dumps([dict(r) for r in db.execute('SELECT id,username,disabled FROM nexus_accounts ORDER BY id')],indent=2))
        elif args.command=='bootstrap-admin':bootstrap(args.database,args.account_id);print('Platform administrator bootstrapped. Farm memberships are unchanged.')
        else:print(issue_reset(args.database,args.operator_id,args.account_id,args.identity_basis,args.output)['message'])
    except (ValueError,OSError,sqlite3.Error) as error:parser.exit(1,f'Account administration failed: {error}\n')


if __name__=='__main__':main()
