"""Explicit storage and additive migration controls for the local launcher."""
import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from nexus.farm_app.backup import backup_database

# Released migration text is immutable: a changed checksum stops startup.
MIGRATIONS = (
    (1, 'local_access_foundation', (
        "CREATE TABLE nexus_accounts (id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, disabled INTEGER NOT NULL DEFAULT 0 CHECK(disabled IN (0,1)), created_at TEXT NOT NULL)",
        "CREATE TABLE nexus_farm_memberships (account_id INTEGER NOT NULL REFERENCES nexus_accounts(id), farm_id INTEGER NOT NULL REFERENCES farms(id), role TEXT NOT NULL CHECK(role IN ('owner','editor','viewer')), PRIMARY KEY(account_id,farm_id))",
    )),
    (2, 'scoped_pilot_sessions', (
        "CREATE TABLE nexus_sessions (token_hash TEXT PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES nexus_accounts(id), csrf TEXT NOT NULL, created_at INTEGER NOT NULL, last_seen INTEGER NOT NULL, expires_at INTEGER NOT NULL)",
        "CREATE TABLE nexus_login_attempts (username_hash TEXT PRIMARY KEY, failures INTEGER NOT NULL, window_start INTEGER NOT NULL)",
        "CREATE TABLE nexus_scoped_notes (id INTEGER PRIMARY KEY, farm_id INTEGER NOT NULL REFERENCES farms(id), account_id INTEGER NOT NULL REFERENCES nexus_accounts(id), note TEXT NOT NULL, created_at TEXT NOT NULL)",
    )),
    (3, 'account_administration', (
        "CREATE TABLE nexus_platform_admins (account_id INTEGER PRIMARY KEY REFERENCES nexus_accounts(id))",
        "ALTER TABLE nexus_accounts ADD COLUMN last_sign_in TEXT",
        "CREATE TABLE nexus_password_resets (token_hash TEXT PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES nexus_accounts(id), expires_at INTEGER NOT NULL, used_at INTEGER)",
        "CREATE TABLE nexus_security_events (id INTEGER PRIMARY KEY, recorded_at TEXT NOT NULL, actor_id INTEGER REFERENCES nexus_accounts(id), affected_id INTEGER REFERENCES nexus_accounts(id), farm_id INTEGER REFERENCES farms(id), category TEXT NOT NULL, result TEXT NOT NULL, summary TEXT NOT NULL)",
        "CREATE TRIGGER nexus_security_no_update BEFORE UPDATE ON nexus_security_events BEGIN SELECT RAISE(ABORT,'Security history is append-only'); END",
        "CREATE TRIGGER nexus_security_no_delete BEFORE DELETE ON nexus_security_events BEGIN SELECT RAISE(ABORT,'Security history is append-only'); END",
    )),
)


def checksum(name, statements):
    return hashlib.sha256(json.dumps([name, statements], separators=(',', ':')).encode()).hexdigest()


def inspect(db):
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='nexus_schema_migrations'").fetchone()
    rows = db.execute('SELECT version,name,checksum FROM nexus_schema_migrations ORDER BY version').fetchall() if exists else []
    known = {version: (name, checksum(name, sql)) for version, name, sql in MIGRATIONS}
    for version, name, digest in rows:
        if version not in known or known[version] != (name, digest):
            raise ValueError('Unknown or changed migration history; use the matching application release')
    applied = [row[0] for row in rows]
    if applied != [m[0] for m in MIGRATIONS[:len(applied)]]:
        raise ValueError('Migration history is not a contiguous released sequence')
    return MIGRATIONS[len(applied):]


def migrate(database, backup_directory):
    path = Path(database).expanduser().resolve()
    if not path.is_file():
        raise ValueError('Initialize the local workspace database before applying migrations')
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=30)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        try:
            pending = inspect(db)
            if not pending:
                db.rollback()
                return {'applied': [], 'backup': None}
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='farms'").fetchone():
                raise ValueError('This is not an initialized NEXUS farm database')
            # The write lock prevents another writer changing the pre-migration copy.
            backup = backup_database(path, backup_directory)
            db.execute('CREATE TABLE IF NOT EXISTS nexus_schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)')
            for version, name, statements in pending:
                for statement in statements:
                    db.execute(statement)
                db.execute('INSERT INTO nexus_schema_migrations VALUES (?,?,?,?)', (version, name, checksum(name, statements), datetime.now(timezone.utc).isoformat()))
            if db.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Migration relationship check failed')
            db.commit()
            return {'applied': [m[0] for m in pending], 'backup': str(backup[0])}
        except Exception:
            db.rollback()
            raise


def configure(parser):
    parser.add_argument('--data-directory', help='Explicit persistent directory; selects its nexus-farm.sqlite3')
    parser.add_argument('--initialize-data-directory', action='store_true', help='Explicitly allow a new empty database inside --data-directory')
    parser.add_argument('--apply-migrations', action='store_true', help='Back up and apply pending additive access migrations before serving')


def prepare(args, parser):
    directory = None
    if getattr(args, 'initialize_data_directory', False) and not args.data_directory:
        parser.error('--initialize-data-directory requires --data-directory')
    if args.data_directory:
        if args.database is not None:
            parser.error('Use --data-directory or --database, not both')
        directory = Path(args.data_directory).expanduser().resolve()
        database = directory / 'nexus-farm.sqlite3'
        if not database.is_file() and not getattr(args, 'initialize_data_directory', False):
            parser.error('No database in selected data directory. Copy your existing database and attachments there, or use --initialize-data-directory for a new empty workspace')
        directory.mkdir(parents=True, exist_ok=True)
        args.database = str(database)
    else:
        args.database = str(Path(args.database or 'nexus-farm.sqlite3').expanduser().resolve())
    if Path(args.database).is_file():
        with closing(sqlite3.connect(Path(args.database).as_uri() + '?mode=ro', uri=True)) as db:
            inspect(db)  # Reject incompatible newer access schemas before legacy initializers run.
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--backup-directory', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if args.apply:
        result = migrate(args.database, args.backup_directory)
    else:
        with closing(sqlite3.connect(Path(args.database).resolve().as_uri() + '?mode=ro', uri=True)) as db:
            result = {'pending': [m[0] for m in inspect(db)]}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
