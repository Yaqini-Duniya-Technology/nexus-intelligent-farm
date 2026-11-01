import argparse
import csv
import hashlib
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def safe_cell(value):
    text = "" if value is None else str(value)

    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text

    return text


def export_photos(database, output):
    database = Path(database).resolve(strict=True)

    connection = sqlite3.connect(
        database.as_uri() + "?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    folder = None

    try:
        connection.execute("BEGIN")

        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(observation_photos)"
            )
        }

        if not columns:
            raise ValueError(
                "This database has no saved photo table."
            )

        source = (
            "source_kind"
            if "source_kind" in columns
            else "'unknown'"
        )

        rows = connection.execute(
            f"SELECT id, observation_id, caption, image_data, sha256, "
            f"uploaded_at, {source} AS source_kind "
            "FROM observation_photos ORDER BY id"
        )

        output = Path(output).resolve()
        output.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now(timezone.utc).strftime(
            "%Y%m%dT%H%M%S_%fZ"
        )

        folder = output / ("nexus-photos-" + stamp)
        folder.mkdir()

        count = 0

        with (folder / "photos.csv").open(
            "w",
            encoding="utf-8-sig",
            newline="",
        ) as handle:
            writer = csv.writer(handle)

            writer.writerow([
                "photo_id",
                "observation_id",
                "filename",
                "source_kind",
                "caption",
                "uploaded_at",
                "sha256",
                "size_bytes",
            ])

            for row in rows:
                raw = bytes(row["image_data"])
                digest = hashlib.sha256(raw).hexdigest()

                if digest != row["sha256"]:
                    raise ValueError(
                        f"Photo #{row['id']} failed its hash check."
                    )

                filename = (
                    f"photo-{row['id']}-"
                    f"observation-{row['observation_id']}.jpg"
                )

                (folder / filename).write_bytes(raw)

                writer.writerow([
                    safe_cell(value)
                    for value in [
                        row["id"],
                        row["observation_id"],
                        filename,
                        row["source_kind"],
                        row["caption"],
                        row["uploaded_at"],
                        digest,
                        len(raw),
                    ]
                ])

                count += 1

        (folder / "README.txt").write_text(
            "NEXUS photo export\n\n"
            "JPEGs are the stored resized copies, "
            "not original uploads.\n"
            "photos.csv links each image to its observation "
            "and source label.\n"
            "Source labels are user declarations, "
            "not verified provenance.\n"
            "test_image means test or AI-generated material, "
            "not farm evidence.\n"
            "unknown means the source was not recorded.\n"
            "Uploaded times are ISO timestamps "
            "with timezone offsets.\n"
            "Each image was checked against its "
            "stored SHA-256 hash.\n"
            "Potential spreadsheet formulas are prefixed "
            "with an apostrophe.\n"
            "Photos do not establish a diagnosis "
            "or treatment effectiveness.\n"
            "This export is for review; use a SQLite "
            "backup for restoration.\n",
            encoding="utf-8",
        )

        return folder, count

    except Exception:
        if folder is not None:
            shutil.rmtree(folder)
        raise

    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(
        description="Export NEXUS saved photos"
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
        folder, count = export_photos(
            args.database,
            args.output,
        )

    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(
            1,
            f"Photo export failed: {error}\n",
        )

    print("NEXUS photo export created.")
    print(f"Folder: {folder}")
    print(f"Photos: {count}")
    print("Image hash checks: passed")
    print("Open photos.csv for captions and source labels.")
    print("The source database was opened read-only.")


if __name__ == "__main__":
    main()