import argparse
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def backup_database(database, output_directory):
    source_path = Path(database).expanduser().resolve()
    output_path = Path(output_directory).expanduser().resolve()

    if not source_path.is_file():
        raise ValueError(
            f"Database not found: {source_path}. "
            "Run this command from your NEXUS project folder "
            "or provide --database."
        )

    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S_%fZ"
    )
    destination = output_path / (
        f"{source_path.stem}-backup-{timestamp}.sqlite3"
    )

    # Reserve a new filename without overwriting an existing file.
    with destination.open("xb"):
        pass

    try:
        # Read-only mode prevents creating or modifying the source.
        source_uri = source_path.as_uri() + "?mode=ro"

        with closing(
            sqlite3.connect(
                source_uri,
                uri=True,
                timeout=30,
            )
        ) as source:
            with closing(
                sqlite3.connect(
                    str(destination),
                    timeout=30,
                )
            ) as target:
                # SQLite's backup API produces a consistent copy,
                # including when the app has an open connection.
                source.backup(target, pages=256, sleep=0.1)

                integrity = [
                    row[0]
                    for row in target.execute(
                        "PRAGMA integrity_check"
                    )
                ]

                if integrity != ["ok"]:
                    raise ValueError(
                        "Backup integrity check failed: "
                        + "; ".join(integrity)
                    )

                foreign_key_errors = target.execute(
                    "PRAGMA foreign_key_check"
                ).fetchall()

                if foreign_key_errors:
                    raise ValueError(
                        "Backup contains invalid record relationships. "
                        "Check the source database before continuing."
                    )

                existing_tables = {
                    row[0]
                    for row in target.execute(
                        """
                        SELECT name
                        FROM sqlite_master
                        WHERE type = 'table'
                        """
                    )
                }

                expected_tables = (
                    "farms",
                    "fields",
                    "observations",
                    "tasks",
                    "task_actions",
                    "followups",
                    "review_snapshots",
                    "followup_schedules",
                )

                counts = {}

                for table in expected_tables:
                    if table in existing_tables:
                        counts[table] = target.execute(
                            f"SELECT COUNT(*) FROM {table}"
                        ).fetchone()[0]

        return destination, counts

    except BaseException:
        # Remove only the incomplete backup created by this call.
        # The source database remains untouched.
        destination.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Create a verified NEXUS database backup"
    )

    parser.add_argument(
        "--database",
        default="nexus-farm.sqlite3",
        help="Path to the existing NEXUS database",
    )

    parser.add_argument(
        "--output-directory",
        default="backups",
        help="Folder for dated backup files",
    )

    args = parser.parse_args()

    try:
        destination, counts = backup_database(
            args.database,
            args.output_directory,
        )
    except (ValueError, sqlite3.Error, OSError) as error:
        parser.exit(
            status=1,
            message=f"Backup failed: {error}\n",
        )

    print("NEXUS backup created.")
    print(f"File: {destination}")
    print("Integrity check: passed")
    print("Record relationships: passed")

    for table, count in counts.items():
        print(f"{table}: {count}")


if __name__ == "__main__":
    main()