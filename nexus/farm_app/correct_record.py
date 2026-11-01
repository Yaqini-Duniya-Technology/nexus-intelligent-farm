import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


ALLOWED = {
    ('farms', 'location'): None,
    ('observations', 'source'): (
        'farmer', 'adviser', 'sensor',
    ),
    ('task_actions', 'action_type'): (
        'inspection',
        'manual_work',
        'adviser_consultation',
        'other',
    ),
}


def correct_record(
    database,
    table,
    record_id,
    column,
    value,
    expected_old,
    reason,
):
    if (table, column) not in ALLOWED:
        raise ValueError(
            'This table and column cannot be corrected here'
        )

    if (
        isinstance(record_id, bool)
        or not isinstance(record_id, int)
        or record_id < 1
    ):
        raise ValueError('Use a positive record ID')

    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 3000
    ):
        raise ValueError(
            'Provide a new value, maximum 3000 characters'
        )

    if (
        not isinstance(reason, str)
        or not reason.strip()
        or len(reason) > 3000
    ):
        raise ValueError(
            'Provide a correction reason, maximum 3000 characters'
        )

    if not isinstance(expected_old, str):
        raise ValueError('Provide the expected current value')

    value = value.strip()
    reason = reason.strip()
    choices = ALLOWED[(table, column)]

    if choices is not None and value not in choices:
        raise ValueError(
            'Allowed values: ' + ', '.join(choices)
        )

    path = Path(database).resolve()

    if not path.is_file():
        raise ValueError('Database file not found')

    with closing(sqlite3.connect(path)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')

        row = db.execute(
            f'SELECT {column} FROM {table} WHERE id=?',
            (record_id,),
        ).fetchone()

        if row is None:
            raise ValueError('Record not found')

        old = row[column]

        if old != expected_old:
            raise ValueError(
                'Current value differs from --expected-old. '
                'Inspect the record before retrying.'
            )

        if old == value:
            return {
                'status': 'unchanged',
                'message': 'No correction needed.',
            }

        db.execute(
            '''
            CREATE TABLE IF NOT EXISTS record_corrections (
                id INTEGER PRIMARY KEY,
                table_name TEXT NOT NULL,
                record_id INTEGER NOT NULL,
                column_name TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT NOT NULL,
                reason TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            )
            '''
        )

        timestamp = datetime.now(timezone.utc).isoformat()

        cursor = db.execute(
            '''
            INSERT INTO record_corrections (
                table_name,
                record_id,
                column_name,
                old_value,
                new_value,
                reason,
                recorded_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                table,
                record_id,
                column,
                old,
                value,
                reason,
                timestamp,
            ),
        )

        db.execute(
            f'UPDATE {table} SET {column}=? WHERE id=?',
            (value, record_id),
        )

        return {
            'status': 'corrected',
            'correction_id': cursor.lastrowid,
            'table': table,
            'record_id': record_id,
            'column': column,
            'old_value': old,
            'new_value': value,
            'reason': reason,
            'recorded_at': timestamp,
        }


def correction_history(database):
    path = Path(database).resolve()

    if not path.is_file():
        raise ValueError('Database file not found')

    uri = path.as_uri() + '?mode=ro'

    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row

        exists = db.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='record_corrections'"
        ).fetchone()

        if not exists:
            return []

        return [
            dict(r)
            for r in db.execute(
                'SELECT * FROM record_corrections ORDER BY id DESC'
            )
        ]


def main():
    parser = argparse.ArgumentParser(
        description='Correct NEXUS labels with an audit record'
    )

    parser.add_argument(
        '--database',
        default='nexus-farm.sqlite3',
    )

    parser.add_argument('--history', action='store_true')

    parser.add_argument(
        '--table',
        choices=['farms', 'observations', 'task_actions'],
    )

    parser.add_argument('--id', type=int)
    parser.add_argument('--column')
    parser.add_argument('--value')
    parser.add_argument('--expected-old')
    parser.add_argument('--reason')

    args = parser.parse_args()

    try:
        if args.history:
            result = correction_history(args.database)
        else:
            if any(
                v is None
                for v in (
                    args.table,
                    args.id,
                    args.column,
                    args.value,
                    args.expected_old,
                    args.reason,
                )
            ):
                raise ValueError(
                    'Provide --table, --id, --column, --value, '
                    '--expected-old and --reason'
                )

            result = correct_record(
                args.database,
                args.table,
                args.id,
                args.column,
                args.value,
                args.expected_old,
                args.reason,
            )

    except (ValueError, sqlite3.Error, OSError) as error:
        parser.exit(1, f'Correction failed: {error}\n')

    print(json.dumps(result, indent=2, ensure_ascii=False))

    if not args.history:
        print(
            'Stored review snapshots and bundles were not rewritten. '
            'New captures use the corrected current label.'
        )


if __name__ == '__main__':
    main()