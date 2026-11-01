import json
import sqlite3
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from nexus.farm_app.audit import initialize_audit
from nexus.farm_app.confirm_voice_review import confirm_review
from nexus.farm_app.import_voice_response import (
    canonical,
    digest,
    import_response,
)
from nexus.farm_app.store import FarmStore
from nexus.farm_app.voice_response_review import (
    initialize,
    save_review,
)


class VoiceReviewConfirmationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)

        self.directory = Path(temporary.name)
        self.database = self.directory / "test.sqlite3"

        self.store = FarmStore(str(self.database))
        initialize_audit(self.store)

        self.farm_id = self.store.create(
            "farms",
            {
                "name": "Test farm",
                "location": "Test location",
            },
        )

        self.field_id = self.store.create(
            "fields",
            {
                "farm_id": self.farm_id,
                "name": "Test field",
                "crop": "maize",
            },
        )

        with self.store.connect() as db:
            db.executescript(
                """
                CREATE TABLE voice_drafts (
                    id INTEGER PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    audio_sha256 TEXT NOT NULL,
                    source TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    original_transcript TEXT NOT NULL,
                    corrected_transcript TEXT NOT NULL,
                    model TEXT NOT NULL,
                    revision TEXT NOT NULL,
                    metrics TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE natlas_voice_requests (
                    id INTEGER PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    draft_id INTEGER NOT NULL
                        REFERENCES voice_drafts(id),
                    draft_version INTEGER NOT NULL,
                    input_sha256 TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(draft_id, draft_version, input_sha256)
                );
                """
            )

        self.review_id = self.make_review()

    def make_review(self, source="farmer"):
        now = datetime.now(timezone.utc).isoformat()
        transcript = "Na lura da ganyen masara masu rawaya."
        audio_hash = "a" * 64
        asr_revision = (
            "e635b9eda29060c6114c8f4d8b2d903f5c83a44a"
        )

        # All records here are fabricated automated-test fixtures.
        # They exist only in this temporary database.
        with self.store.connect() as db:
            cursor = db.execute(
                """
                INSERT INTO voice_drafts (
                    request_id,
                    audio_sha256,
                    source,
                    recorded_at,
                    original_transcript,
                    corrected_transcript,
                    model,
                    revision,
                    metrics,
                    version,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    audio_hash,
                    source,
                    now,
                    transcript,
                    transcript,
                    "NCAIR1/Hausa-ASR",
                    asr_revision,
                    "{}",
                    1,
                    now,
                ),
            )
            self.draft_id = cursor.lastrowid

        frozen = {
            "draft_id": self.draft_id,
            "draft_version": 1,
            "source": source,
            "audio_sha256": audio_hash,
            "original_transcript": transcript,
            "corrected_transcript": transcript,
            "asr_model": "NCAIR1/Hausa-ASR",
            "asr_revision": asr_revision,
            "draft_updated_at": now,
        }

        request = {
            "request_version": "natlas-voice-request-v1",
            "request_id": str(uuid.uuid4()),
            "created_at": now,
            "input_sha256": digest(frozen),
            "input": frozen,
            "model": "NCAIR1/N-ATLaS",
            "model_revision": (
                "e294476928aca9030e924ca27bb8e085e8581273"
            ),
            "purpose": "reviewable_information_extraction",
            "farm_observation_saved": False,
        }
        request["content_sha256"] = digest(request)

        with self.store.connect() as db:
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
                    request["request_id"],
                    self.draft_id,
                    1,
                    request["input_sha256"],
                    canonical(request),
                    now,
                ),
            )

        extraction = {
            "crop": "maize",
            "proposed_category": "crop_health",
            "reported_symptoms": ["Yellow maize leaves"],
            "possible_causes_mentioned_by_farmer": [],
            "clarification_questions": [
                "When did yellowing begin?"
            ],
        }

        response = {
            "response_version": "natlas-voice-response-v1",
            "response_id": str(uuid.uuid4()),
            "request_id": request["request_id"],
            "request_content_sha256": request["content_sha256"],
            "input_sha256": request["input_sha256"],
            "draft_id": self.draft_id,
            "draft_version": 1,
            "source": source,
            "model": request["model"],
            "model_revision": request["model_revision"],
            "started_at": now,
            "completed_at": now,
            "inference_seconds": 0.0,
            "generation_settings": {
                "max_new_tokens": 500,
                "do_sample": False,
            },
            "raw_model_output": canonical(extraction),
            "parsed_extraction": extraction,
            "structure_check": "passed",
            "structure_error": None,
            "human_review_required": True,
            "confidence": None,
            "farm_observation_saved": False,
            "limitations": [
                "Fabricated automated-test fixture"
            ],
        }
        response["content_sha256"] = digest(response)

        response_file = (
            self.directory
            / f"response-{response['response_id']}.json"
        )
        response_file.write_text(
            canonical(response),
            encoding="utf-8",
        )

        _, response_id, _, _ = import_response(
            response_file,
            self.database,
        )

        initialize(self.database)

        result = save_review(
            self.database,
            {
                "response_record_id": response_id,
                "reviewer_as_reported": (
                    "Automated test fixture"
                ),
                "notes": (
                    "Fabricated fixture, not actual farm evidence."
                ),
                "confirmed": True,
                "extraction": extraction,
            },
        )

        return result["id"]

    def counts(self):
        tables = (
            "observations",
            "tasks",
            "review_snapshots",
            "natlas_voice_observation_links",
        )
        result = {}

        with self.store.connect() as db:
            for table in tables:
                exists = db.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table' AND name = ?
                    """,
                    (table,),
                ).fetchone()

                result[table] = (
                    db.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                    if exists
                    else 0
                )

        return result

    def confirm(self, **kwargs):
        return confirm_review(
            self.store,
            self.review_id,
            self.field_id,
            kwargs.pop("confirmed", True),
            **kwargs,
        )

    def test_success_saves_observation_task_snapshot_and_link(self):
        result = self.confirm()

        self.assertFalse(result["reused"])
        self.assertEqual(
            self.counts(),
            {
                "observations": 1,
                "tasks": 1,
                "review_snapshots": 1,
                "natlas_voice_observation_links": 1,
            },
        )

        with self.store.connect() as db:
            observation = db.execute(
                "SELECT * FROM observations WHERE id = ?",
                (result["observation_id"],),
            ).fetchone()

            link = db.execute(
                """
                SELECT *
                FROM natlas_voice_observation_links
                WHERE review_id = ?
                """,
                (self.review_id,),
            ).fetchone()

            snapshot = db.execute(
                """
                SELECT payload
                FROM review_snapshots
                WHERE task_id = ?
                """,
                (result["task_id"],),
            ).fetchone()

        self.assertEqual(observation["source"], "farmer")
        self.assertEqual(
            observation["category"],
            "crop_health",
        )
        self.assertEqual(
            observation["note"],
            "Na lura da ganyen masara masu rawaya.",
        )

        provenance = json.loads(link["provenance"])

        self.assertEqual(
            provenance["human_review"]["draft_id"],
            self.draft_id,
        )
        self.assertEqual(
            link["task_id"],
            result["task_id"],
        )
        self.assertTrue(
            json.loads(snapshot["payload"])["atomic_save"]
        )

    def test_repeat_confirmation_reuses_existing_records(self):
        first = self.confirm()
        second = self.confirm()

        self.assertTrue(second["reused"])
        self.assertEqual(
            first["observation_id"],
            second["observation_id"],
        )
        self.assertEqual(
            first["task_id"],
            second["task_id"],
        )
        self.assertEqual(
            self.counts()["observations"],
            1,
        )

    def test_changed_draft_is_rejected(self):
        before = self.counts()

        with self.store.connect() as db:
            db.execute(
                """
                UPDATE voice_drafts
                SET version = version + 1,
                    corrected_transcript = ?
                WHERE id = ?
                """,
                ("Changed transcript", self.draft_id),
            )

        with self.assertRaisesRegex(
            ValueError,
            "draft changed",
        ):
            self.confirm()

        self.assertEqual(self.counts(), before)

    def test_explicit_confirmation_is_required(self):
        before = self.counts()

        with self.assertRaisesRegex(
            ValueError,
            "confirmation is required",
        ):
            self.confirm(confirmed=False)

        self.assertEqual(self.counts(), before)

    def assert_test_source_is_rejected(self, source):
        # Build a consistent draft, request, response and review
        # with the test source. Do not relabel a farmer fixture.
        self.review_id = self.make_review(source=source)
        test_draft_id = self.draft_id

        # Keep an existing farmer observation in the database,
        # so rejection also checks preservation of saved records.
        farmer_review_id = self.make_review(source="farmer")
        existing = confirm_review(
            self.store,
            farmer_review_id,
            self.field_id,
            True,
        )

        before = self.counts()

        with self.store.connect() as db:
            original_observation = dict(
                db.execute(
                    "SELECT * FROM observations WHERE id = ?",
                    (existing["observation_id"],),
                ).fetchone()
            )

        with self.assertRaisesRegex(
            ValueError,
            "Test recordings cannot become farm observations",
        ):
            self.confirm()

        self.assertEqual(self.counts(), before)

        with self.store.connect() as db:
            saved_source = db.execute(
                "SELECT source FROM voice_drafts WHERE id = ?",
                (test_draft_id,),
            ).fetchone()["source"]

            test_link = db.execute(
                """
                SELECT id
                FROM natlas_voice_observation_links
                WHERE draft_id = ?
                """,
                (test_draft_id,),
            ).fetchone()

            preserved_observation = dict(
                db.execute(
                    "SELECT * FROM observations WHERE id = ?",
                    (existing["observation_id"],),
                ).fetchone()
            )

        self.assertEqual(saved_source, source)
        self.assertIsNone(test_link)
        self.assertEqual(
            preserved_observation,
            original_observation,
        )

    def test_synthetic_test_recording_is_rejected(self):
        self.assert_test_source_is_rejected(
            "synthetic_test"
        )

    def test_human_test_recording_is_rejected(self):
        self.assert_test_source_is_rejected(
            "human_test"
        )

    def test_link_insert_failure_rolls_back_all_farm_records(self):
        # Create the link table through a successful save,
        # then remove that save inside this isolated database.
        self.confirm()

        with self.store.connect() as db:
            db.execute(
                "DELETE FROM natlas_voice_observation_links"
            )
            db.execute("DELETE FROM review_snapshots")
            db.execute("DELETE FROM tasks")
            db.execute("DELETE FROM observations")

            db.executescript(
                """
                CREATE TRIGGER reject_voice_link
                BEFORE INSERT ON natlas_voice_observation_links
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'Injected voice link failure'
                    );
                END;
                """
            )

        before = self.counts()

        with self.assertRaisesRegex(
            sqlite3.IntegrityError,
            "Injected voice link failure",
        ):
            self.confirm()

        self.assertEqual(self.counts(), before)


if __name__ == "__main__":
    unittest.main()