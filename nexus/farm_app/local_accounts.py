"""Privileged local account creation and farm grants. Full Operations remains single-user."""
import argparse
import getpass
import hashlib
import hmac
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from nexus.farm_app.deployment_controls import inspect

ITERATIONS = 600_000
ROLES = {'owner', 'editor', 'viewer'}


def password_hash(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 1024:
        raise ValueError('Use a password of 12 to 1024 characters')
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f'pbkdf2_sha256${ITERATIONS}${salt}${digest}'


def verify(password, stored):
    try:
        algorithm, rounds, salt, expected = stored.split('$')
        if algorithm != 'pbkdf2_sha256' or int(rounds) != ITERATIONS or len(salt) != 32 or len(expected) != 64:
            return False
        if not isinstance(password, str) or len(password) > 1024:
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, AttributeError):
        return False


def connect(database):
    db = sqlite3.connect(Path(database).expanduser().resolve().as_uri() + '?mode=rw', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        if inspect(db):
            raise ValueError('Apply pending access migrations first')
        return db
    except Exception:
        db.close()
        raise


def validate_username(username):
    if not isinstance(username, str) or not username.isascii() or not 3 <= len(username) <= 64 or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-._' for c in username):
        raise ValueError('Username: 3–64 lowercase ASCII letters, digits, dot, dash or underscore')


def create(database, username, password):
    validate_username(username)
    encoded = password_hash(password)
    with closing(connect(database)) as db, db:
        try:
            account_id = db.execute('INSERT INTO nexus_accounts(username,password_hash,created_at) VALUES (?,?,?)', (username, encoded, datetime.now(timezone.utc).isoformat())).lastrowid
            from nexus.farm_app.account_admin import event
            event(db, 'account_create', affected=account_id, summary='Privileged local CLI creation')
            return account_id
        except sqlite3.IntegrityError:
            raise ValueError('Username already exists') from None


def grant(database, account_id, farm_id, role):
    if any(type(value) is not int or value < 1 for value in (account_id, farm_id)) or role not in ROLES:
        raise ValueError('Select positive account/farm IDs and owner, editor or viewer')
    with closing(connect(database)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM nexus_accounts WHERE id=? AND disabled=0', (account_id,)).fetchone() or not db.execute('SELECT 1 FROM farms WHERE id=?', (farm_id,)).fetchone():
            raise ValueError('Enabled account and existing farm required')
        old = db.execute('SELECT role FROM nexus_farm_memberships WHERE account_id=? AND farm_id=?', (account_id, farm_id)).fetchone()
        if old and old['role'] == 'owner' and role != 'owner' and db.execute("SELECT count(*) FROM nexus_farm_memberships m JOIN nexus_accounts a ON a.id=m.account_id WHERE farm_id=? AND role='owner' AND a.disabled=0", (farm_id,)).fetchone()[0] <= 1:
            raise ValueError('Cannot demote the last enabled farm owner')
        db.execute('INSERT INTO nexus_farm_memberships VALUES (?,?,?) ON CONFLICT(account_id,farm_id) DO UPDATE SET role=excluded.role', (account_id, farm_id, role))
        from nexus.farm_app.account_admin import event
        event(db, 'account_grant', affected=account_id, farm=farm_id, summary='Privileged local CLI role assignment: '+role)


def allowed(database, account_id, farm_id, write=False):
    # Explicit primitive for future route integration; grants never imply global access.
    if type(account_id) is not int or type(farm_id) is not int:
        return False
    with closing(connect(database)) as db:
        row = db.execute('SELECT role FROM nexus_farm_memberships m JOIN nexus_accounts a ON a.id=m.account_id WHERE account_id=? AND farm_id=? AND a.disabled=0', (account_id, farm_id)).fetchone()
        return bool(row and (not write or row['role'] in ('owner', 'editor')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    add = commands.add_parser('create')
    add.add_argument('--username', required=True)
    access = commands.add_parser('grant')
    access.add_argument('--account-id', type=int, required=True)
    access.add_argument('--farm-id', type=int, required=True)
    access.add_argument('--role', choices=sorted(ROLES), required=True)
    args = parser.parse_args()
    try:
        if args.command == 'create':
            password = getpass.getpass('New password (hidden): ')
            if password != getpass.getpass('Repeat password: '):
                raise ValueError('Passwords differ')
            print('Account created:', create(args.database, args.username, password))
        else:
            grant(args.database, args.account_id, args.farm_id, args.role)
            print('Local farm membership saved.')
        print('The pilot enforces its supported routes. Full Operations remains single-user; keep both local.')
    except (ValueError, sqlite3.Error) as error:
        parser.exit(1, f'Account administration failed: {error}\n')


if __name__ == '__main__':
    main()
