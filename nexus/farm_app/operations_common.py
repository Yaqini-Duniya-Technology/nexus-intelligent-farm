"""Shared primitives for the local operations release. Standard library only."""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path

RELEASE = 'NEXUS reliability audit 2026.11.01'
LAGOS = timezone(timedelta(hours=1))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def positive(value, label='ID'):
    if type(value) is not int or value < 1:
        raise ValueError('Use a positive ' + label)
    return value


def word(value, label, limit=3000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'Complete {label} (maximum {limit} characters)')
    return value.strip()


def day(value):
    if not isinstance(value, str):
        raise ValueError('Use a YYYY-MM-DD date')
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError()
        return parsed
    except ValueError:
        raise ValueError('Use a YYYY-MM-DD date') from None


def instant(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Time must be valid and include a timezone') from None


def text(value):
    return escape(str(value if value is not None else 'Unknown'))


def identifier(value):
    return '"' + value.replace('"', '""') + '"'


@contextmanager
def readonly(database):
    if isinstance(database, sqlite3.Connection):
        yield database
        return
    path = Path(database).expanduser().resolve()
    if not path.is_file():
        raise ValueError('Database not found. Use the NEXUS folder or provide --database.')
    db = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        yield db
    finally:
        db.close()


def table_names(db):
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
