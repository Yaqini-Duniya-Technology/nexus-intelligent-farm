"""Prepare a separate authenticated NEXUS database from an existing SQLite backup."""
import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

from nexus.farm_app import local_accounts
from nexus.farm_app.backup import backup_database

REQUIRED_TABLES = (
    'farms', 'fields', 'observations', 'tasks', 'task_actions', 'followups',
    'nexus_accounts', 'nexus_farm_memberships', 'nexus_sessions', 'nexus_password_resets',
    'nexus_platform_admins', 'nexus_security_events', 'nexus_scoped_notes', 'nexus_login_attempts',
)


def restore(backup, directory):
    source = Path(backup).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f'Backup file not found: {source}')
    # Refuse existing directories, including symlinks. Never target a live database.
    directory = Path(directory).expanduser().absolute()
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    staged = None
    try:
        staged, _ = backup_database(source, directory)
        with closing(local_accounts.connect(staged)) as db, db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing = set(REQUIRED_TABLES) - tables
            if missing:
                raise ValueError('Missing authenticated workspace tables: ' + ', '.join(sorted(missing)))
            counts = {table: db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
                      for table in ('farms', 'fields', 'observations', 'field_inspections') if table in tables}
            # Keep account credentials and memberships, but require fresh sign-in and reset tokens.
            db.execute('DELETE FROM nexus_sessions')
            db.execute('DELETE FROM nexus_password_resets')
        destination = directory / 'nexus-farm.sqlite3'
        # Exclusive publication: fail if anything already exists at the destination.
        # SQLite backup has already committed and closed before the copy is moved.
        with destination.open('xb'):
            pass
        try:
            staged.replace(destination)
        except OSError:
            destination.unlink(missing_ok=True)
            raise
        return destination, counts
    except BaseException:
        if staged is not None:
            staged.unlink(missing_ok=True)
        try:
            directory.rmdir()
        except OSError:
            pass
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--directory', required=True, help='New directory for the restored database')
    args = parser.parse_args()
    try:
        destination, counts = restore(args.backup, args.directory)
    except (ValueError, sqlite3.Error, OSError) as error:
        parser.exit(1, f'Isolated restore failed: {error}\n')
    print(f'Isolated database: {destination}')
    print('Integrity, foreign keys and access migration checks passed. Sign in again on the restored workspace.')
    for table, count in counts.items():
        print(f'{table}: {count}')
    print('Database only. External attachments, exports and audio are not restored.')


if __name__ == '__main__':
    main()
