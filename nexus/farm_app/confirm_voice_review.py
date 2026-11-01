import argparse
import sqlite3
from datetime import datetime, timezone

from nexus.farm_app.atomic import create_observation_atomic
from nexus.farm_app.audit import initialize_audit
from nexus.farm_app.import_voice_response import (
    canonical,
    digest,
    parse_json,
    validate_extraction,
)
from nexus.farm_app.store import FarmStore
from nexus.farm_app.voice_confirm import BorrowedStore
from nexus.farm_app.voice_response_review import checked_response


def positive_id(value, label):
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
    ):
        raise ValueError(f"Invalid {label}")


def confirm_review(
    store,
    review_id,
    field_id,
    confirmed,
    condition="unknown",
    observed_at=None,
):
    positive_id(review_id, "review ID")
    positive_id(field_id, "field ID")

    if confirmed is not True:
        raise ValueError(
            "Explicit confirmation is required. "
            "Review the transcript, extraction and selected field first."
        )

    if condition not in ("unknown", "stable", "worsening"):
        raise ValueError("Invalid field condition")

    confirmation = {
        "review_id": review_id,
        "field_id": field_id,
        "condition": condition,
        "observed_at": observed_at,
    }
    confirmation_hash = digest(confirmation)

    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")

        review_row = db.execute(
            """
            SELECT *
            FROM natlas_voice_response_reviews
            WHERE id = ?
            """,
            (review_id,),
        ).fetchone()

        if not review_row:
            raise ValueError("Human review not found")

        review = parse_json(review_row["payload"])

        if digest(review) != review_row["content_sha256"]:
            raise ValueError("Human review hash check failed")

        if (
            review.get("review_version")
            != "natlas-voice-human-review-v1"
            or review.get("transcript_compared") is not True
            or review.get("farm_observation_saved") is not False
            or review.get("response_record_id")
            != review_row["response_record_id"]
        ):
            raise ValueError("Unsupported human review")

        response_row, response, request = checked_response(
            db,
            review_row["response_record_id"],
        )
        frozen = request["input"]

        expected = {
            "response_content_sha256": response_row["content_sha256"],
            "request_id": response["request_id"],
            "input_sha256": response["input_sha256"],
            "draft_id": frozen["draft_id"],
            "draft_version": frozen["draft_version"],
            "source": frozen["source"],
        }

        for key, value in expected.items():
            if (
                type(review.get(key)) is not type(value)
                or review[key] != value
            ):
                raise ValueError(f"Human review linkage failed: {key}")

        if frozen["source"] != "farmer":
            raise ValueError(
                "Test recordings cannot become farm observations. "
                "This review must remain test material."
            )

        validate_extraction(review.get("extraction"))

        draft = db.execute(
            "SELECT * FROM voice_drafts WHERE id = ?",
            (frozen["draft_id"],),
        ).fetchone()

        if not draft or draft["source"] != "farmer":
            raise ValueError("Actual farmer draft not found")

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS natlas_voice_observation_links (
                id INTEGER PRIMARY KEY,
                review_id INTEGER NOT NULL UNIQUE
                    REFERENCES natlas_voice_response_reviews(id),
                draft_id INTEGER NOT NULL UNIQUE
                    REFERENCES voice_drafts(id),
                observation_id INTEGER NOT NULL UNIQUE
                    REFERENCES observations(id),
                task_id INTEGER NOT NULL UNIQUE
                    REFERENCES tasks(id),
                confirmation_sha256 TEXT NOT NULL,
                confirmed_at TEXT NOT NULL,
                provenance TEXT NOT NULL
            )
            """
        )

        existing = db.execute(
            """
            SELECT *
            FROM natlas_voice_observation_links
            WHERE draft_id = ?
            """,
            (frozen["draft_id"],),
        ).fetchone()

        if existing:
            if (
                existing["review_id"] != review_id
                or existing["confirmation_sha256"]
                != confirmation_hash
            ):
                raise ValueError(
                    "This draft already created an observation "
                    "with a different confirmation."
                )

            return {
                "observation_id": existing["observation_id"],
                "task_id": existing["task_id"],
                "reused": True,
            }

        # Also prevent duplication through the earlier voice bridge.
        old_link_table = db.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table'
              AND name = 'voice_observation_links'
            """
        ).fetchone()

        if old_link_table:
            old_link = db.execute(
                """
                SELECT observation_id
                FROM voice_observation_links
                WHERE draft_id = ?
                """,
                (frozen["draft_id"],),
            ).fetchone()

            if old_link:
                raise ValueError(
                    "This draft already created observation "
                    f"#{old_link['observation_id']} through voice confirmation."
                )

        if (
            draft["version"] != frozen["draft_version"]
            or draft["corrected_transcript"]
            != frozen["corrected_transcript"]
            or draft["original_transcript"]
            != frozen["original_transcript"]
            or draft["audio_sha256"] != frozen["audio_sha256"]
            or draft["model"] != frozen["asr_model"]
            or draft["revision"] != frozen["asr_revision"]
            or draft["updated_at"] != frozen["draft_updated_at"]
        ):
            raise ValueError(
                "The draft changed after this request was exported. "
                "Export the current version and review its new response."
            )

        latest_review = db.execute(
            """
            SELECT id
            FROM natlas_voice_response_reviews
            WHERE response_record_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (response_row["id"],),
        ).fetchone()

        if latest_review["id"] != review_id:
            raise ValueError(
                "A newer human review exists for this response. "
                "Use the latest review."
            )

        result = create_observation_atomic(
            BorrowedStore(store, db),
            {
                "field_id": field_id,
                # Preserve the confirmed transcript as the observation.
                "note": frozen["corrected_transcript"],
                "source": "farmer",
                "category": review["extraction"]["proposed_category"],
                "condition": condition,
                "observed_at": observed_at,
            },
        )

        provenance = {
            "version": "natlas-reviewed-voice-observation-v1",
            "confirmation": confirmation,
            "frozen_input": frozen,
            "request_content_sha256": request["content_sha256"],
            "response": response,
            "human_review": review,
            "human_review_sha256": review_row["content_sha256"],
            "verification": "farmer_reported",
            "limitations": [
                "Recording source and reviewer identity are user-reported.",
                "Hashes do not authenticate model inference.",
                "Possible causes remain unconfirmed.",
                "Original audio is not stored in this capture.",
                "Recommendations remain human-review prompts.",
            ],
        }

        db.execute(
            """
            INSERT INTO natlas_voice_observation_links (
                review_id, draft_id, observation_id, task_id,
                confirmation_sha256, confirmed_at, provenance
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review_id,
                frozen["draft_id"],
                result["observation_id"],
                result["task_id"],
                confirmation_hash,
                datetime.now(timezone.utc).isoformat(),
                canonical(provenance),
            ),
        )

        # The outer transaction commits the observation, task,
        # review snapshot and provenance link together.
        return {**result, "reused": False}


def main():
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Confirm a reviewed farmer voice observation"
    )
    parser.add_argument("--review-id", type=int, required=True)
    parser.add_argument("--field-id", type=int, required=True)
    parser.add_argument("--database", default="nexus-farm.sqlite3")
    parser.add_argument(
        "--condition",
        choices=("unknown", "stable", "worsening"),
        default="unknown",
    )
    parser.add_argument(
        "--observed-at",
        help="Observation timestamp with timezone; omit to use submission time",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm the reviewed transcript describes this field",
    )
    args = parser.parse_args()

    database = Path(args.database).expanduser().resolve()
    if not database.is_file():
        parser.exit(1, "Existing NEXUS database not found\n")

    try:
        if not args.confirm:
            raise ValueError(
                "Read the saved review and confirm the field "
                "before using --confirm."
            )

        store = FarmStore(str(database))
        initialize_audit(store)

        result = confirm_review(
            store,
            args.review_id,
            args.field_id,
            args.confirm,
            args.condition,
            args.observed_at,
        )
    except (ValueError, sqlite3.Error) as error:
        parser.exit(1, f"Confirmation rejected: {error}\n")

    print(
        "Existing confirmed observation reused."
        if result["reused"]
        else "Reviewed voice observation saved."
    )
    print("Observation ID:", result["observation_id"])
    print("Task ID:", result["task_id"])
    print("Transcript, model response and human review captured.")
    print("No diagnosis or equipment action was performed.")


if __name__ == "__main__":
    main()