import argparse
import hashlib
import hmac
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


MAX_FILE_BYTES = 262144

EXPECTED_KEYS = {
    "crop",
    "proposed_category",
    "reported_symptoms",
    "possible_causes_mentioned_by_farmer",
    "clarification_questions",
}

CATEGORIES = {
    "general",
    "crop_health",
    "water",
    "pest",
    "operations",
}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"Invalid JSON constant: {value}")


def canonical_bytes(data):
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def validate(data):
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")

    supplied_hash = data.get("content_sha256")
    if not isinstance(supplied_hash, str):
        raise ValueError("Content hash is missing")

    content = dict(data)
    del content["content_sha256"]

    calculated_hash = hashlib.sha256(
        canonical_bytes(content)
    ).hexdigest()

    if not hmac.compare_digest(supplied_hash, calculated_hash):
        raise ValueError("Content hash does not match")

    if data.get("draft_version") != "natlas-reviewed-extraction-v1":
        raise ValueError("Unsupported draft version")

    if data.get("source") != "synthetic_test":
        raise ValueError("This importer accepts synthetic tests only")

    if data.get("model") != "NCAIR1/N-ATLaS":
        raise ValueError("Unexpected model identifier")

    if data.get("review_status") != "human_reviewed_test_draft":
        raise ValueError("Expected a human-reviewed test draft")

    if data.get("farm_observation_saved") is not False:
        raise ValueError("Expected a draft without a farm observation")

    for key in (
        "model_revision",
        "source_transcript",
        "original_model_output",
        "reviewer_as_reported",
        "reviewed_at",
    ):
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Missing or invalid {key}")

    reviewed_at = datetime.fromisoformat(
        data["reviewed_at"].replace("Z", "+00:00")
    )
    if reviewed_at.tzinfo is None:
        raise ValueError("Review time must include a timezone")

    extraction = data.get("reviewed_extraction")
    if (
        not isinstance(extraction, dict)
        or set(extraction) != EXPECTED_KEYS
    ):
        raise ValueError("Invalid reviewed extraction fields")

    crop = extraction["crop"]
    if crop is not None and (
        not isinstance(crop, str) or not crop.strip()
    ):
        raise ValueError("Crop must be text or null")

    category = extraction["proposed_category"]
    if not isinstance(category, str) or category not in CATEGORIES:
        raise ValueError("Invalid reviewed category")

    for key in (
        "reported_symptoms",
        "possible_causes_mentioned_by_farmer",
        "clarification_questions",
    ):
        values = extraction[key]
        if not isinstance(values, list) or not all(
            isinstance(value, str) and value.strip()
            for value in values
        ):
            raise ValueError(f"Invalid {key}")

    if len(extraction["clarification_questions"]) > 3:
        raise ValueError("Too many clarification questions")

    corrections = data.get("corrections")
    if not isinstance(corrections, list) or not corrections:
        raise ValueError("Review notes are missing")

    for correction in corrections:
        if not isinstance(correction, dict):
            raise ValueError("Invalid correction record")
        for key in ("field", "reason"):
            value = correction.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Invalid correction details")

    return calculated_hash


def import_draft(database, filename):
    database = Path(database).resolve()
    filename = Path(filename).resolve()

    # Avoid accidentally creating an empty database at a wrong path.
    if not database.is_file():
        raise ValueError("Select an existing NEXUS database")

    with filename.open("rb") as source:
        raw = source.read(MAX_FILE_BYTES + 1)

    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("Draft exceeds the 256 KB limit")

    data = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )

    content_hash = validate(data)
    payload = canonical_bytes(data).decode("utf-8")

    with closing(sqlite3.connect(database)) as db:
        db.execute("PRAGMA foreign_keys = ON")

        with db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS natlas_test_imports (
                    id INTEGER PRIMARY KEY,
                    content_sha256 TEXT NOT NULL UNIQUE,
                    imported_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )

            existing = db.execute(
                """
                SELECT id
                FROM natlas_test_imports
                WHERE content_sha256 = ?
                """,
                (content_hash,),
            ).fetchone()

            cursor = db.execute(
                """
                INSERT INTO natlas_test_imports (
                    content_sha256,
                    imported_at,
                    payload
                )
                VALUES (?, ?, ?)
                ON CONFLICT(content_sha256) DO NOTHING
                """,
                (
                    content_hash,
                    datetime.now(timezone.utc).isoformat(),
                    payload,
                ),
            )

            reused = existing is not None or cursor.rowcount == 0

            record = db.execute(
                """
                SELECT id, imported_at
                FROM natlas_test_imports
                WHERE content_sha256 = ?
                """,
                (content_hash,),
            ).fetchone()

    return {
        "id": record[0],
        "imported_at": record[1],
        "reused": reused,
        "content_sha256": content_hash,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Import a reviewed N-ATLaS synthetic test draft"
    )
    parser.add_argument("file")
    parser.add_argument(
        "--database",
        default="nexus-farm.sqlite3",
    )
    args = parser.parse_args()

    try:
        result = import_draft(args.database, args.file)
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f"Import failed: {error}\n")

    print(
        "Existing test draft reused."
        if result["reused"]
        else "N-ATLaS test draft imported."
    )
    print("Record ID:", result["id"])
    print("Imported at:", result["imported_at"])
    print("Content SHA-256:", result["content_sha256"])
    print("Source: synthetic_test")
    print("Hash check passed; provenance is not independently authenticated.")
    print("No farm observation or review task was created.")


if __name__ == "__main__":
    main()