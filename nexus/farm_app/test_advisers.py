import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nexus.farm_app.advisers import (
    adviser_state,
    initialize_advisers,
    save_adviser_review,
)


class TestStore:
    def __init__(self, path):
        self.path = str(path)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            with db:
                yield db
        finally:
            db.close()


class AdviserReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)

        self.store = TestStore(
            Path(temporary.name) / "reviews.sqlite3"
        )

        self.original_time = (
            datetime.now(timezone.utc) - timedelta(days=2)
        )

        with self.store.connect() as db:
            db.executescript("""
                CREATE TABLE farms (
                    id INTEGER PRIMARY KEY,
                    name TEXT
                );

                CREATE TABLE fields (
                    id INTEGER PRIMARY KEY,
                    farm_id INTEGER,
                    name TEXT,
                    crop TEXT
                );

                CREATE TABLE observations (
                    id INTEGER PRIMARY KEY,
                    field_id INTEGER,
                    note TEXT,
                    category TEXT,
                    observed_at TEXT,
                    created TEXT
                );

                INSERT INTO farms
                VALUES (1, 'TEST FARM');

                INSERT INTO fields
                VALUES (1, 1, 'TEST FIELD', 'maize');
            """)

            db.execute(
                """
                INSERT INTO observations
                VALUES (1, 1, ?, ?, ?, ?)
                """,
                (
                    "TEST observation",
                    "pest",
                    self.original_time.isoformat(),
                    self.original_time.isoformat(),
                ),
            )

        initialize_advisers(self.store)

    def data(self):
        return {
            "observation_id": 1,
            "adviser_name": "TEST ADVISER",
            "adviser_role": "TEST ROLE",
            "reviewed_at": (
                self.original_time + timedelta(hours=1)
            ).isoformat(),
            "findings": "TEST findings only.",
            "assessment": "unconfirmed",
            "basis": "TEST examination; cause unresolved.",
            "next_step": "TEST next step only.",
        }

    def test_save_survives_reopening(self):
        save_adviser_review(self.store, self.data())

        reopened = TestStore(self.store.path)
        state = adviser_state(reopened)

        self.assertEqual(len(state["reviews"]), 1)

        review = state["reviews"][0]

        self.assertEqual(review["observation_id"], 1)
        self.assertEqual(
            review["adviser_name"],
            "TEST ADVISER",
        )
        self.assertEqual(
            review["assessment"],
            "unconfirmed",
        )
        self.assertEqual(
            review["findings"],
            "TEST findings only.",
        )
        self.assertIsNotNone(
            datetime.fromisoformat(
                review["recorded_at"]
            ).tzinfo
        )

    def test_invalid_inputs_save_nothing(self):
        invalid = [
            {"observation_id": True},
            {"observation_id": 999},
            {"adviser_name": ""},
            {"adviser_role": " "},
            {"findings": "x" * 3001},
            {"basis": ""},
            {"next_step": ""},
            {"assessment": "invalid"},
        ]

        for change in invalid:
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    save_adviser_review(
                        self.store,
                        {**self.data(), **change},
                    )

                self.assertEqual(
                    adviser_state(self.store)["reviews"],
                    [],
                )

    def test_invalid_review_times_save_nothing(self):
        invalid = [
            (
                self.original_time - timedelta(seconds=1)
            ).isoformat(),
            (
                datetime.now(timezone.utc)
                + timedelta(days=1)
            ).isoformat(),
            "2026-01-01T12:00:00",
            "not a timestamp",
        ]

        for value in invalid:
            with self.subTest(reviewed_at=value):
                with self.assertRaises(ValueError):
                    save_adviser_review(
                        self.store,
                        {
                            **self.data(),
                            "reviewed_at": value,
                        },
                    )

                self.assertEqual(
                    adviser_state(self.store)["reviews"],
                    [],
                )

    def test_new_review_preserves_earlier_review(self):
        save_adviser_review(self.store, self.data())

        original = adviser_state(
            self.store
        )["reviews"][0]

        initialize_advisers(self.store)

        save_adviser_review(
            self.store,
            {
                **self.data(),
                "findings": "TEST correction.",
            },
        )

        state = adviser_state(self.store)

        self.assertEqual(len(state["reviews"]), 2)
        self.assertEqual(state["reviews"][1], original)
        self.assertEqual(
            state["reviews"][0]["findings"],
            "TEST correction.",
        )
        self.assertEqual(
            len(state["observations"]),
            1,
        )


if __name__ == "__main__":
    unittest.main()