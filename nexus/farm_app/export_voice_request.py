import argparse
import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def canonical(data):
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def export_request(database, draft_id, output_directory):
    database = Path(database).resolve()

    if not database.is_file():
        raise ValueError("Select an existing NEXUS database")

    if (
        isinstance(draft_id, bool)
        or not isinstance(draft_id, int)
        or draft_id < 1
    ):
        raise ValueError("Select a valid voice draft ID")

    with closing(sqlite3.connect(database)) as db:
        db.row_factory = sqlite3.Row

        with db:
            db.execute("BEGIN IMMEDIATE")

            draft = db.execute(
                "SELECT * FROM voice_drafts WHERE id = ?",
                (draft_id,),
            ).fetchone()

            if draft is None:
                raise ValueError("Voice draft not found")

            if draft["source"] not in (
                "synthetic_test",
                "human_test",
                "farmer",
            ):
                raise ValueError("Unsupported recording source")

            transcript = draft["corrected_transcript"]

            if (
                not isinstance(transcript, str)
                or not transcript.strip()
                or len(transcript) > 3000
            ):
                raise ValueError("Invalid corrected transcript")

            db.execute(
                """
                CREATE TABLE IF NOT EXISTS natlas_voice_requests (
                    id INTEGER PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    draft_id INTEGER NOT NULL REFERENCES voice_drafts(id),
                    draft_version INTEGER NOT NULL,
                    input_sha256 TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(draft_id, draft_version, input_sha256)
                )
                """
            )

            # Freeze the exact source version used for this request.
            frozen_input = {
                "draft_id": draft["id"],
                "draft_version": draft["version"],
                "source": draft["source"],
                "audio_sha256": draft["audio_sha256"],
                "original_transcript": draft["original_transcript"],
                "corrected_transcript": transcript,
                "asr_model": draft["model"],
                "asr_revision": draft["revision"],
                "draft_updated_at": draft["updated_at"],
            }

            input_hash = hashlib.sha256(
                canonical(frozen_input).encode("utf-8")
            ).hexdigest()

            existing = db.execute(
                """
                SELECT *
                FROM natlas_voice_requests
                WHERE draft_id = ?
                  AND draft_version = ?
                  AND input_sha256 = ?
                """,
                (draft["id"], draft["version"], input_hash),
            ).fetchone()

            reused = existing is not None

            if existing:
                payload = json.loads(existing["payload"])
            else:
                created_at = datetime.now(timezone.utc).isoformat()

                payload = {
                    "request_version": "natlas-voice-request-v1",
                    "request_id": str(uuid.uuid4()),
                    "created_at": created_at,
                    "input_sha256": input_hash,
                    "input": frozen_input,
                    "model": "NCAIR1/N-ATLaS",
                    "model_revision": (
                        "e294476928aca9030e924ca27bb8e085e8581273"
                    ),
                    "purpose": "reviewable_information_extraction",
                    "farm_observation_saved": False,
                }

                payload["content_sha256"] = hashlib.sha256(
                    canonical(payload).encode("utf-8")
                ).hexdigest()

                db.execute(
                    """
                    INSERT INTO natlas_voice_requests (
                        request_id,
                        draft_id,
                        draft_version,
                        input_sha256,
                        payload,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payload["request_id"],
                        draft["id"],
                        draft["version"],
                        input_hash,
                        canonical(payload),
                        created_at,
                    ),
                )

    output_directory = Path(output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=True)

    path = output_directory / (
        f"natlas-voice-request-{payload['request_id']}.json"
    )

    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return payload, path, reused


def main():
    parser = argparse.ArgumentParser(
        description="Export a saved voice draft for N-ATLaS extraction"
    )
    parser.add_argument("--draft-id", required=True, type=int)
    parser.add_argument("--database", default="nexus-farm.sqlite3")
    parser.add_argument("--output-directory", default="exports")
    args = parser.parse_args()

    try:
        payload, path, reused = export_request(
            args.database,
            args.draft_id,
            args.output_directory,
        )
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(
            1,
            f"Export could not be completed: {error}\n"
            "If a request was stored, rerunning reuses it.\n",
        )

    frozen = payload["input"]

    print(
        "Existing voice request reused."
        if reused
        else "N-ATLaS voice request stored."
    )
    print("Request ID:", payload["request_id"])
    print("Draft:", frozen["draft_id"])
    print("Draft version:", frozen["draft_version"])
    print("Source:", frozen["source"])
    print("JSON:", path)
    print("No model inference was performed.")
    print("No farm observation or review task was created.")


if __name__ == "__main__":
    main()