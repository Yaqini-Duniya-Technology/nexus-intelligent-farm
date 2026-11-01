import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nexus.farm_app.atomic import create_observation_atomic
from nexus.farm_app.audit import initialize_audit
from nexus.farm_app.store import FarmStore


class AtomicObservationTests(unittest.TestCase):
    def setUp(self):
        self.connections = []

        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)

        # unittest runs cleanup functions in reverse order.
        # Close database connections before deleting the folder.
        self.addCleanup(self.close_connections)

        original_connect = sqlite3.connect

        def tracked_connect(*args, **kwargs):
            connection = original_connect(*args, **kwargs)
            self.connections.append(connection)
            return connection

        self.connect_patch = patch(
            "sqlite3.connect",
            side_effect=tracked_connect,
        )
        self.connect_patch.start()
        self.addCleanup(self.connect_patch.stop)

        self.database_path = (
            Path(self.temp_directory.name) / "test.sqlite3"
        )

        self.store = FarmStore(str(self.database_path))
        initialize_audit(self.store)

        self.farm_id = self.store.create(
            "farms",
            {
                "name": "Test farm",
                "location": "Abuja",
            },
        )

        self.field_id = self.store.create(
            "fields",
            {
                "farm_id": self.farm_id,
                "name": "North field",
                "crop": "maize",
            },
        )

    def close_connections(self):
        while self.connections:
            connection = self.connections.pop()
            connection.close()

    def observation_data(self):
        return {
            "field_id": self.field_id,
            "note": "Observed holes in maize leaves.",
            "category": "pest",
            "source": "farmer",
            "condition": "unknown",
        }

    def counts(self):
        tables = (
            "farms",
            "fields",
            "observations",
            "tasks",
            "review_snapshots",
        )

        with self.store.connect() as db:
            return {
                table: db.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                for table in tables
            }

    def test_success_saves_all_records_and_survives_reopening(self):
        result = create_observation_atomic(
            self.store,
            self.observation_data(),
        )

        # Close existing connections before reopening the database.
        self.close_connections()
        reopened_store = FarmStore(str(self.database_path))

        with reopened_store.connect() as db:
            observation = db.execute(
                "SELECT * FROM observations WHERE id = ?",
                (result["observation_id"],),
            ).fetchone()

            task = db.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (result["task_id"],),
            ).fetchone()

            snapshot = db.execute(
                "SELECT * FROM review_snapshots WHERE task_id = ?",
                (result["task_id"],),
            ).fetchone()

        self.assertIsNotNone(observation)
        self.assertIsNotNone(task)
        self.assertIsNotNone(snapshot)

        payload = json.loads(snapshot["payload"])

        self.assertEqual(
            task["observation_id"],
            observation["id"],
        )
        self.assertEqual(payload["task_id"], task["id"])
        self.assertEqual(
            payload["observation"]["id"],
            observation["id"],
        )
        self.assertTrue(payload["atomic_save"])
        self.assertEqual(
            payload["capture_method"],
            "same_transaction_v1",
        )
        self.assertEqual(
            payload["history"]["knowledge_cutoff"],
            observation["created"],
        )
        self.assertEqual(
            self.counts(),
            {
                "farms": 1,
                "fields": 1,
                "observations": 1,
                "tasks": 1,
                "review_snapshots": 1,
            },
        )

    def test_history_failure_rolls_back_observation_and_task(self):
        before = self.counts()

        with patch(
            "nexus.farm_app.atomic.retrieve_history",
            side_effect=RuntimeError("Injected history failure"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "Injected history failure",
            ):
                create_observation_atomic(
                    self.store,
                    self.observation_data(),
                )

        self.assertEqual(self.counts(), before)

    def test_snapshot_insert_failure_rolls_back_all_new_records(self):
        before = self.counts()

        with self.store.connect() as db:
            db.executescript(
                """
                CREATE TRIGGER reject_snapshot_insert
                BEFORE INSERT ON review_snapshots
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'Injected snapshot failure'
                    );
                END;
                """
            )

        with self.assertRaisesRegex(
            sqlite3.IntegrityError,
            "Injected snapshot failure",
        ):
            create_observation_atomic(
                self.store,
                self.observation_data(),
            )

        self.assertEqual(self.counts(), before)

        with self.store.connect() as db:
            db.execute("DROP TRIGGER reject_snapshot_insert")

        create_observation_atomic(
            self.store,
            self.observation_data(),
        )

        self.assertEqual(self.counts()["observations"], 1)
        self.assertEqual(self.counts()["tasks"], 1)
        self.assertEqual(self.counts()["review_snapshots"], 1)

    def test_later_save_preserves_existing_snapshot(self):
        first = create_observation_atomic(
            self.store,
            self.observation_data(),
        )

        with self.store.connect() as db:
            original = db.execute(
                """
                SELECT payload
                FROM review_snapshots
                WHERE task_id = ?
                """,
                (first["task_id"],),
            ).fetchone()["payload"]

        second_data = self.observation_data()
        second_data["note"] = "A second field inspection."

        second = create_observation_atomic(
            self.store,
            second_data,
        )

        with self.store.connect() as db:
            preserved = db.execute(
                """
                SELECT payload
                FROM review_snapshots
                WHERE task_id = ?
                """,
                (first["task_id"],),
            ).fetchone()["payload"]

        self.assertEqual(preserved, original)
        self.assertNotEqual(first["task_id"], second["task_id"])
        self.assertEqual(self.counts()["observations"], 2)
        self.assertEqual(self.counts()["tasks"], 2)
        self.assertEqual(self.counts()["review_snapshots"], 2)


if __name__ == "__main__":
    unittest.main()