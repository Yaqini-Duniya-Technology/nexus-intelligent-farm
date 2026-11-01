"""Authenticated, deny-by-default services for the narrow local account pilot."""
import hashlib
import hmac
import secrets
import time
from contextlib import closing
from datetime import datetime, timezone
from nexus.farm_app import local_accounts as accounts


class AccessError(ValueError):
    def __init__(self, message='Access denied', status=403):
        super().__init__(message)
        self.status = status


# A fixed dummy verifier makes unknown-user and bad-password paths comparable.
DUMMY = 'pbkdf2_sha256$600000$' + '00' * 16 + '$' + '00' * 32


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def login(database, username, password, now=None):
    now = int(time.time()) if now is None else now
    if not isinstance(username, str) or not isinstance(password, str) or len(username) > 64 or len(password) > 1024:
        raise AccessError('Invalid credentials', 401)
    key = digest(username)
    with closing(accounts.connect(database)) as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM nexus_login_attempts WHERE window_start+900<=?', (now,))
        attempt = db.execute('SELECT * FROM nexus_login_attempts WHERE username_hash=?', (key,)).fetchone()
        if attempt and attempt['window_start'] + 900 > now and attempt['failures'] >= 5:
            db.rollback()
            raise AccessError('Login temporarily limited. Retry after 15 minutes.', 429)
        account = db.execute('SELECT * FROM nexus_accounts WHERE username=?', (username,)).fetchone()
        valid = accounts.verify(password, account['password_hash'] if account else DUMMY)
        if not valid or not account or account['disabled']:
            start = attempt['window_start'] if attempt and attempt['window_start'] + 900 > now else now
            count = attempt['failures'] + 1 if start != now and attempt else 1
            # Same-second retries must also count.
            if attempt and attempt['window_start'] + 900 > now:
                count = attempt['failures'] + 1
            db.execute('INSERT INTO nexus_login_attempts VALUES (?,?,?) ON CONFLICT(username_hash) DO UPDATE SET failures=excluded.failures,window_start=excluded.window_start', (key, count, start))
            db.commit()
            raise AccessError('Invalid credentials', 401)
        db.execute('DELETE FROM nexus_login_attempts WHERE username_hash=?', (key,))
        db.execute('DELETE FROM nexus_sessions WHERE expires_at<=? OR last_seen<=?', (now, now - 1800))
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        db.execute('INSERT INTO nexus_sessions VALUES (?,?,?,?,?,?)', (digest(token), account['id'], csrf, now, now, now + 28800))
        db.commit()
        return token, csrf


def identity(db, token, now=None):
    now = int(time.time()) if now is None else now
    if not isinstance(token, str) or not 32 <= len(token) <= 128:
        raise AccessError('Sign in required', 401)
    row = db.execute('SELECT s.*, a.username,a.disabled FROM nexus_sessions s JOIN nexus_accounts a ON a.id=s.account_id WHERE token_hash=?', (digest(token),)).fetchone()
    if not row or row['disabled'] or row['expires_at'] <= now or row['last_seen'] + 1800 <= now or row['created_at'] > now:
        raise AccessError('Session expired or unavailable. Sign in again.', 401)
    db.execute('UPDATE nexus_sessions SET last_seen=? WHERE token_hash=?', (now, digest(token)))
    return row


def require_farm(db, account_id, farm_id, write=False):
    if type(farm_id) is not int or farm_id < 1:
        raise AccessError('Select an accessible farm', 403)
    membership = db.execute('SELECT role FROM nexus_farm_memberships WHERE account_id=? AND farm_id=?', (account_id, farm_id)).fetchone()
    if not membership or (write and membership['role'] not in ('owner', 'editor')):
        raise AccessError()
    return membership['role']


def read(database, token, farm_id=None):
    with closing(accounts.connect(database)) as db, db:
        user = identity(db, token)
        farms = [dict(row) for row in db.execute('SELECT f.id,f.name,m.role FROM farms f JOIN nexus_farm_memberships m ON m.farm_id=f.id WHERE m.account_id=? ORDER BY f.id', (user['account_id'],))]
        result = {'username': user['username'], 'csrf': user['csrf'], 'farms': farms, 'fields': [], 'observations': [], 'notes': []}
        if farm_id is not None:
            require_farm(db, user['account_id'], farm_id)
            result['fields'] = [dict(row) for row in db.execute('SELECT id,name,crop FROM fields WHERE farm_id=? ORDER BY id', (farm_id,))]
            result['observations'] = [dict(row) for row in db.execute('SELECT o.id,o.field_id,o.note,o.observed_at FROM observations o JOIN fields f ON f.id=o.field_id WHERE f.farm_id=? ORDER BY o.id DESC LIMIT 100', (farm_id,))]
            result['notes'] = [dict(row) for row in db.execute('SELECT id,note,created_at FROM nexus_scoped_notes WHERE farm_id=? ORDER BY id DESC LIMIT 100', (farm_id,))]
        return result


def note(database, token, csrf, farm_id, value):
    if not isinstance(value, str) or not value.strip() or len(value) > 3000:
        raise ValueError('Enter a note of 1–3000 characters')
    with closing(accounts.connect(database)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        user = identity(db, token)
        if not isinstance(csrf, str) or not hmac.compare_digest(csrf.encode('utf-8'), user['csrf'].encode('utf-8')):
            raise AccessError('Refresh this page before saving')
        require_farm(db, user['account_id'], farm_id, write=True)
        return db.execute('INSERT INTO nexus_scoped_notes(farm_id,account_id,note,created_at) VALUES (?,?,?,?)', (farm_id, user['account_id'], value.strip(), datetime.now(timezone.utc).isoformat())).lastrowid


def logout(database, token, csrf):
    with closing(accounts.connect(database)) as db, db:
        user = identity(db, token)
        if not isinstance(csrf, str) or not hmac.compare_digest(csrf.encode('utf-8'), user['csrf'].encode('utf-8')):
            raise AccessError()
        db.execute('DELETE FROM nexus_sessions WHERE token_hash=?', (digest(token),))
