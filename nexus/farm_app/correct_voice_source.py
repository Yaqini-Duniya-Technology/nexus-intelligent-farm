import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def inspect(db, draft_id, reference_id):
    draft = db.execute(
        "SELECT * FROM voice_drafts WHERE id = ?",
        (draft_id,),
    ).fetchone()

    reference = db.execute(
        "SELECT * FROM voice_drafts WHERE id = ?",
        (reference_id,),
    ).fetchone()

    if not draft or not reference:
        raise ValueError("Draft or reference draft not found")

    links = []

    for table in (
        "voice_observation_links",
        "natlas_voice_observation_links",
    ):
        exists = db.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table,),
        ).fetchone()

        if exists:
            for row in db.execute(
                f"""
                SELECT observation_id, task_id
                FROM {table}
                WHERE draft_id = ?
                """,
                (draft_id,),
            ):
                links.append({
                    "table": table,
                    "observation_id": row["observation_id"],
                    "task_id": row["task_id"],
                })

    audio_hash = draft["audio_sha256"]
    matching_audio = (
        isinstance(audio_hash, str)
        and len(audio_hash) == 64
        and audio_hash == reference["audio_sha256"]
    )

    return {
        "draft_id": draft["id"],
        "current_source": draft["source"],
        "current_version": draft["version"],
        "reference_id": reference["id"],
        "reference_source": reference["source"],
        "same_audio_hash": matching_audio,
        "linked_farm_records": links,
    }


def correct(db, draft_id, reference_id, reason):
    report = inspect(db, draft_id, reference_id)

    if report["reference_source"] != "synthetic_test":
        raise ValueError(
            "Reference must be labelled synthetic_test"
        )

    if not report["same_audio_hash"]:
        raise ValueError(
            "Audio hashes differ. Inspect the original recordings "
            "before deciding their sources."
        )

    if report["linked_farm_records"]:
        raise ValueError(
            "This draft already has linked farm records. "
            "No correction applied. Review those records first."
        )

    if report["current_source"] == "synthetic_test":
        return {**report, "changed": False}

    if report["current_source"] != "farmer":
        raise ValueError(
            "This command only corrects farmer to synthetic_test"
        )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS voice_source_corrections (
            id INTEGER PRIMARY KEY,
            draft_id INTEGER NOT NULL REFERENCES voice_drafts(id),
            reference_draft_id INTEGER NOT NULL
                REFERENCES voice_drafts(id),
            old_source TEXT NOT NULL,
            new_source TEXT NOT NULL,
            old_version INTEGER NOT NULL,
            new_version INTEGER NOT NULL,
            reason TEXT NOT NULL,
            recorded_at TEXT NOT NULL
        )
        """
    )

    now = datetime.now(timezone.utc).isoformat()
    old_version = report["current_version"]

    db.execute(
        """
        INSERT INTO voice_source_corrections (
            draft_id, reference_draft_id,
            old_source, new_source,
            old_version, new_version,
            reason, recorded_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            draft_id,
            reference_id,
            "farmer",
            "synthetic_test",
            old_version,
            old_version + 1,
            reason,
            now,
        ),
    )

    db.execute(
        """
        UPDATE voice_drafts
        SET source = 'synthetic_test',
            version = version + 1,
            updated_at = ?
        WHERE id = ?
        """,
        (now, draft_id),
    )

    return {
        **inspect(db, draft_id, reference_id),
        "changed": True,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Inspect and audit a voice source correction"
    )
    parser.add_argument("--draft-id", type=int, required=True)
    parser.add_argument("--reference-id", type=int, required=True)
    parser.add_argument("--database", default="nexus-farm.sqlite3")
    parser.add_argument("--reason")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()

    if (
        args.draft_id < 1
        or args.reference_id < 1
        or args.draft_id == args.reference_id
    ):
        parser.exit(1, "Provide two different positive draft IDs\n")

    database = Path(args.database).expanduser().resolve()
    if not database.is_file():
        parser.exit(1, "Existing NEXUS database not found\n")

    if args.confirm:
        if (
            not args.reason
            or not args.reason.strip()
            or len(args.reason) > 3000
        ):
            parser.exit(1, "Provide a correction reason\n")

    mode = "rw" if args.confirm else "ro"
    uri = database.as_uri() + f"?mode={mode}"

    try:
        with closing(sqlite3.connect(uri, uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")

            with db:
                db.execute(
                    "BEGIN IMMEDIATE" if args.confirm else "BEGIN"
                )

                if args.confirm:
                    result = correct(
                        db,
                        args.draft_id,
                        args.reference_id,
                        args.reason.strip(),
                    )
                else:
                    result = inspect(
                        db,
                        args.draft_id,
                        args.reference_id,
                    )

        print(json.dumps(result, indent=2))
        print(
            "Source correction committed."
            if args.confirm and result["changed"]
            else "No records changed."
        )

    except (ValueError, sqlite3.Error) as error:
        parser.exit(1, f"Operation stopped: {error}\n")


if __name__ == "__main__":
    main()