import argparse
import csv
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def spreadsheet_value(value):
    """Keep text from being interpreted as a spreadsheet formula."""
    if isinstance(value, str):
        stripped = value.lstrip()

        if stripped.startswith(("=", "+", "-", "@")) or value.startswith(
            ("\t", "\r", "\n")
        ):
            return "'" + value

    return value


def quote_identifier(value):
    return '"' + value.replace('"', '""') + '"'


def export_records(database="nexus-farm.sqlite3", output="exports"):
    database_path = Path(database).expanduser().resolve()

    if not database_path.is_file():
        raise ValueError(f"Database not found: {database_path}")

    output_root = Path(output).expanduser().resolve()
    now = datetime.now(timezone.utc)

    destination = output_root / (
        "nexus-records-" + now.strftime("%Y%m%dT%H%M%S_%fZ")
    )

    destination.mkdir(parents=True, exist_ok=False)
    db = None

    try:
        db = sqlite3.connect(
            database_path.as_uri() + "?mode=ro",
            uri=True,
        )

        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")

        tables = [
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
        ]

        files = []

        for index, table in enumerate(tables, start=1):
            # Numeric filenames safely support unusual SQL table names.
            filename = f"table-{index:02d}.csv"
            path = destination / filename

            cursor = db.execute(
                "SELECT * FROM " + quote_identifier(table)
            )

            columns = [column[0] for column in cursor.description]
            count = 0

            with path.open(
                "w",
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                writer = csv.writer(handle)

                writer.writerow([
                    spreadsheet_value(column)
                    for column in columns
                ])

                for row in cursor:
                    writer.writerow([
                        spreadsheet_value(value)
                        for value in row
                    ])
                    count += 1

            files.append({
                "table": table,
                "file": filename,
                "rows": count,
                "columns": columns,
                "sha256": hashlib.sha256(
                    path.read_bytes()
                ).hexdigest(),
            })

        db.rollback()
        db.close()
        db = None

        manifest = {
            "export_version": "farm-csv-v1",
            "exported_at": now.isoformat(),
            "source_database": database_path.name,
            "consistent_read": True,
            "encoding": "utf-8-sig",
            "files": files,
            "notes": [
                "CSV files are for review and analysis, "
                "not database restoration.",
                "Use the SQLite backup for restoration.",
                "Potential formula text is prefixed with an apostrophe.",
                "Null database values appear as empty CSV cells.",
                "Money columns named amount_kobo contain kobo; "
                "divide by 100 for NGN.",
                "Quantity columns named quantity_g contain grams; "
                "divide by 1000 for kg.",
                "Recorded reports do not establish diagnosis "
                "or treatment effectiveness.",
            ],
        }

        (destination / "manifest.json").write_text(
            json.dumps(
                manifest,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        lines = [
            "NEXUS farm records export",
            "",
            "Files and source tables:",
        ]

        lines.extend(
            f"{entry['file']} = {entry['table']} "
            f"({entry['rows']} records)"
            for entry in files
        )

        lines.extend(["", *manifest["notes"]])

        (destination / "README.txt").write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )

        return destination, manifest

    except Exception:
        if db is not None:
            db.close()

        shutil.rmtree(destination)
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Export NEXUS records to CSV"
    )

    parser.add_argument(
        "--database",
        default="nexus-farm.sqlite3",
    )

    parser.add_argument(
        "--output",
        default="exports",
    )

    args = parser.parse_args()

    try:
        destination, manifest = export_records(
            args.database,
            args.output,
        )
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f"Export failed: {error}\n")

    print("NEXUS CSV export created.")
    print(f"Folder: {destination}")

    for entry in manifest["files"]:
        print(
            f"{entry['table']}: {entry['rows']} records "
            f"-> {entry['file']}"
        )

    print("Open README.txt for the table names and units.")
    print("The source database was opened read-only.")


if __name__ == "__main__":
    main()