import argparse
import hashlib
import hmac
import json
import math
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


MODEL = "NCAIR1/N-ATLaS"
REVISION = "e294476928aca9030e924ca27bb8e085e8581273"


def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def digest(value):
    return hashlib.sha256(
        canonical(value).encode("utf-8")
    ).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"Invalid JSON constant: {value}")


def parse_json(text):
    return json.loads(
        text,
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )


def check_hash(value):
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")

    claimed = value.get("content_sha256")
    unsigned = {
        key: item
        for key, item in value.items()
        if key != "content_sha256"
    }

    if (
        not isinstance(claimed, str)
        or not hmac.compare_digest(digest(unsigned), claimed)
    ):
        raise ValueError("Content hash check failed")


def check_uuid(value, label):
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValueError(f"Invalid {label}") from None


def check_time(value, label):
    if not isinstance(value, str):
        raise ValueError(f"Invalid {label}")

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"Invalid {label}") from None

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} requires a timezone")

    return parsed


def validate_extraction(value):
    keys = {
        "crop",
        "proposed_category",
        "reported_symptoms",
        "possible_causes_mentioned_by_farmer",
        "clarification_questions",
    }

    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("Invalid extraction fields")

    crop = value["crop"]
    if crop is not None and (
        not isinstance(crop, str)
        or not crop.strip()
        or len(crop) > 200
    ):
        raise ValueError("Invalid crop value")

    if value["proposed_category"] not in {
        "general",
        "crop_health",
        "water",
        "pest",
        "operations",
    }:
        raise ValueError("Invalid category")

    for key in (
        "reported_symptoms",
        "possible_causes_mentioned_by_farmer",
        "clarification_questions",
    ):
        items = value[key]
        if not isinstance(items, list) or len(items) > 20:
            raise ValueError(f"Invalid {key}")

        if any(
            not isinstance(item, str)
            or not item.strip()
            or len(item) > 1000
            for item in items
        ):
            raise ValueError(f"Invalid entry in {key}")

    if len(value["clarification_questions"]) > 3:
        raise ValueError("Too many clarification questions")


def validate_response(response):
    check_hash(response)

    if response.get("response_version") != "natlas-voice-response-v1":
        raise ValueError("Unsupported response version")

    check_uuid(response.get("response_id"), "response ID")
    check_uuid(response.get("request_id"), "request ID")

    if (
        response.get("model") != MODEL
        or response.get("model_revision") != REVISION
    ):
        raise ValueError("Unexpected model or revision")

    if response.get("human_review_required") is not True:
        raise ValueError("Human review must remain required")

    if response.get("farm_observation_saved") is not False:
        raise ValueError("Unexpected observation status")

    if response.get("confidence") is not None:
        raise ValueError("No calibrated confidence is supported")

    started = check_time(response.get("started_at"), "Start time")
    completed = check_time(response.get("completed_at"), "Completion time")

    if completed < started:
        raise ValueError("Completion precedes start time")

    seconds = response.get("inference_seconds")
    if (
        isinstance(seconds, bool)
        or not isinstance(seconds, (int, float))
        or not math.isfinite(seconds)
        or seconds < 0
    ):
        raise ValueError("Invalid inference duration")

    raw = response.get("raw_model_output")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Original model output is required")

    # Independently check the original output.
    parsed = None
    error = None
    try:
        parsed = parse_json(raw)
        validate_extraction(parsed)
    except (ValueError, TypeError) as problem:
        error = str(problem)

    expected_status = "passed" if error is None else "failed"

    if response.get("structure_check") != expected_status:
        raise ValueError("Structure status disagrees with original output")

    if canonical(response.get("parsed_extraction")) != canonical(parsed):
        raise ValueError("Parsed extraction differs from original output")

    if error is None:
        if response.get("structure_error") is not None:
            raise ValueError("Unexpected structure error")
    elif (
        not isinstance(response.get("structure_error"), str)
        or not response["structure_error"].strip()
    ):
        raise ValueError("Failed structure check requires an error")

    return {
        "status": expected_status,
        "error": error,
    }


def import_response(filename, database):
    path = Path(filename).expanduser().resolve()
    if not path.is_file():
        raise ValueError("Response JSON file does not exist")

    raw = path.read_bytes()
    if len(raw) > 256 * 1024:
        raise ValueError("Response exceeds 256 KB")

    response = parse_json(raw.decode("utf-8"))
    local_check = validate_response(response)

    database_path = Path(database).expanduser().resolve()
    if not database_path.is_file():
        raise ValueError("Existing NEXUS database not found")

    with closing(sqlite3.connect(str(database_path))) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")

        with db:
            db.execute("BEGIN IMMEDIATE")

            table = db.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'natlas_voice_requests'
                """
            ).fetchone()

            if not table:
                raise ValueError(
                    "No saved voice request table exists in this database"
                )

            saved = db.execute(
                """
                SELECT * FROM natlas_voice_requests
                WHERE request_id = ?
                """,
                (response["request_id"],),
            ).fetchone()

            if not saved:
                raise ValueError("Matching saved request not found")

            request = parse_json(saved["payload"])
            check_hash(request)

            if (
                request.get("request_version") != "natlas-voice-request-v1"
                or request.get("purpose")
                != "reviewable_information_extraction"
                or request.get("farm_observation_saved") is not False
            ):
                raise ValueError("Unsupported saved request")

            frozen = request.get("input")
            if not isinstance(frozen, dict):
                raise ValueError("Saved request input is missing")

            calculated_input_hash = digest(frozen)

            if (
                request.get("request_id") != saved["request_id"]
                or frozen.get("draft_id") != saved["draft_id"]
                or frozen.get("draft_version") != saved["draft_version"]
                or calculated_input_hash != saved["input_sha256"]
                or calculated_input_hash != request.get("input_sha256")
            ):
                raise ValueError("Saved request consistency check failed")

            bindings = {
                "request_content_sha256": request["content_sha256"],
                "input_sha256": calculated_input_hash,
                "draft_id": frozen["draft_id"],
                "draft_version": frozen["draft_version"],
                "source": frozen["source"],
                "model": request["model"],
                "model_revision": request["model_revision"],
            }

            for key, expected in bindings.items():
                if (
                    type(response.get(key)) is not type(expected)
                    or response[key] != expected
                ):
                    raise ValueError(
                        f"Response does not match saved request: {key}"
                    )

            db.execute(
                """
                CREATE TABLE IF NOT EXISTS natlas_voice_responses (
                    id INTEGER PRIMARY KEY,
                    response_id TEXT NOT NULL UNIQUE,
                    request_id TEXT NOT NULL
                        REFERENCES natlas_voice_requests(request_id),
                    content_sha256 TEXT NOT NULL UNIQUE,
                    imported_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    local_structure_check TEXT NOT NULL
                )
                """
            )

            existing = db.execute(
                """
                SELECT * FROM natlas_voice_responses
                WHERE response_id = ? OR content_sha256 = ?
                """,
                (
                    response["response_id"],
                    response["content_sha256"],
                ),
            ).fetchone()

            if existing:
                if (
                    existing["response_id"] != response["response_id"]
                    or existing["content_sha256"]
                    != response["content_sha256"]
                    or canonical(parse_json(existing["payload"]))
                    != canonical(response)
                ):
                    raise ValueError(
                        "Existing response ID has different content"
                    )

                record_id = existing["id"]
                imported_at = existing["imported_at"]
                reused = True
            else:
                imported_at = datetime.now(timezone.utc).isoformat()
                cursor = db.execute(
                    """
                    INSERT INTO natlas_voice_responses (
                        response_id,
                        request_id,
                        content_sha256,
                        imported_at,
                        payload,
                        local_structure_check
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        response["response_id"],
                        response["request_id"],
                        response["content_sha256"],
                        imported_at,
                        canonical(response),
                        canonical(local_check),
                    ),
                )
                record_id = cursor.lastrowid
                reused = False

    return response, record_id, imported_at, reused


def main():
    parser = argparse.ArgumentParser(
        description="Import a request-linked N-ATLaS response"
    )
    parser.add_argument("filename")
    parser.add_argument("--database", default="nexus-farm.sqlite3")
    args = parser.parse_args()

    try:
        response, record_id, imported_at, reused = import_response(
            args.filename,
            args.database,
        )
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f"Import failed: {error}\n")

    print(
        "Existing voice response reused."
        if reused
        else "N-ATLaS voice response imported."
    )
    print("Record ID:", record_id)
    print("Response ID:", response["response_id"])
    print("Request ID:", response["request_id"])
    print("Draft:", response["draft_id"])
    print("Draft version:", response["draft_version"])
    print("Source:", response["source"])
    print("Imported at:", imported_at)
    print("Structure check:", response["structure_check"])
    print("Content hashes and saved request linkage: passed")
    print("Human review is still required.")
    print("Hashes do not authenticate the model run.")
    print("No farm observation or review task was created.")


if __name__ == "__main__":
    main()