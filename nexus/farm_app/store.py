import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from nexus.farm_app.observations import normalize, review


class FarmStore:
    def __init__(self, path):
        self.path = path

        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS farms (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    location TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS fields (
                    id INTEGER PRIMARY KEY,
                    farm_id INTEGER NOT NULL REFERENCES farms(id),
                    name TEXT NOT NULL,
                    crop TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY,
                    field_id INTEGER NOT NULL REFERENCES fields(id),
                    note TEXT NOT NULL,
                    created TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY,
                    observation_id INTEGER NOT NULL UNIQUE
                        REFERENCES observations(id),
                    recommendation TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    outcome TEXT,
                    completed TEXT
                );

                CREATE TABLE IF NOT EXISTS task_actions (
                    id INTEGER PRIMARY KEY,
                    task_id INTEGER NOT NULL UNIQUE REFERENCES tasks(id),
                    action_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    performed_at TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS followups (
                    id INTEGER PRIMARY KEY,
                    task_id INTEGER NOT NULL REFERENCES tasks(id),
                    result TEXT NOT NULL,
                    evidence TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
            """)

            additions = {
                "observations": {
                    "observed_at": "TEXT",
                    "category": "TEXT DEFAULT 'general'",
                    "source": "TEXT DEFAULT 'farmer'",
                    "condition": "TEXT DEFAULT 'unknown'",
                    "soil_moisture_pct": "REAL",
                    "moisture_method": "TEXT",
                    "contract_version": "TEXT",
                },
                "tasks": {
                    "priority": "TEXT DEFAULT 'routine'",
                    "explanation": "TEXT",
                    "missing_information": "TEXT DEFAULT '[]'",
                    "rule_version": "TEXT",
                },
            }

            for table, columns in additions.items():
                existing = {
                    row["name"]
                    for row in db.execute(
                        f"PRAGMA table_info({table})"
                    )
                }

                for name, declaration in columns.items():
                    if name not in existing:
                        db.execute(
                            f"ALTER TABLE {table} "
                            f"ADD COLUMN {name} {declaration}"
                        )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)

        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")

            # Commit on success; roll back when an exception occurs.
            with db:
                yield db
        finally:
            # SQLite's transaction context does not close connections.
            db.close()

    @staticmethod
    def _parse_time(value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                "A required historical timestamp is missing"
            )

        try:
            timestamp = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except ValueError:
            raise ValueError(
                "A historical timestamp is invalid"
            ) from None

        # Legacy server timestamps without an offset use UTC.
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        return timestamp.astimezone(timezone.utc)

    def _task_context(self, db, task_id):
        if (
            isinstance(task_id, bool)
            or not isinstance(task_id, int)
            or task_id < 1
        ):
            raise ValueError("Invalid task ID")

        task = db.execute(
            """
            SELECT
                tasks.*,
                observations.observed_at AS original_observed_at,
                observations.created AS observation_created
            FROM tasks
            JOIN observations
                ON observations.id = tasks.observation_id
            WHERE tasks.id = ?
            """,
            (task_id,),
        ).fetchone()

        if not task:
            raise ValueError("Task not found")

        return task

    def _observation_time(self, task):
        return self._parse_time(
            task["original_observed_at"]
            or task["observation_created"]
        )

    def _assess_followup(self, followup, task, observation, action):
        """Check historical evidence without modifying stored records."""
        reasons = []

        if not task:
            reasons.append("Linked task is missing")
        elif task["status"] != "completed":
            reasons.append("Linked task is not completed")

        if followup["result"] not in (
            "improved",
            "unchanged",
            "worsened",
            "uncertain",
        ):
            reasons.append("Reported result is invalid")

        evidence = followup.get("evidence")

        if not isinstance(evidence, str) or not evidence.strip():
            reasons.append("Supporting evidence is missing")

        followup_time = None

        try:
            followup_time = self._parse_time(
                followup["observed_at"]
            )
        except ValueError as error:
            reasons.append(f"Follow-up timestamp: {error}")

        if not observation:
            reasons.append("Original observation is missing")
        else:
            try:
                observation_time = self._parse_time(
                    observation["observed_at"]
                    or observation["created"]
                )

                if (
                    followup_time is not None
                    and followup_time < observation_time
                ):
                    reasons.append(
                        "Follow-up predates the original observation"
                    )
            except ValueError as error:
                reasons.append(
                    f"Original observation timestamp: {error}"
                )

        if action:
            try:
                action_time = self._parse_time(
                    action["performed_at"]
                )

                if (
                    followup_time is not None
                    and followup_time < action_time
                ):
                    reasons.append(
                        "Follow-up predates the recorded action"
                    )
            except ValueError as error:
                reasons.append(f"Action timestamp: {error}")

        try:
            recorded_time = self._parse_time(
                followup["recorded_at"]
            )

            # Match the existing five-minute clock tolerance.
            if (
                followup_time is not None
                and (followup_time - recorded_time).total_seconds() > 300
            ):
                reasons.append(
                    "Follow-up was more than five minutes "
                    "in the future when recorded"
                )
        except ValueError as error:
            reasons.append(f"Recording timestamp: {error}")

        return {
            "eligible": not reasons,
            "status": "eligible" if not reasons else "excluded",
            "reasons": reasons,
            "action_time_available": action is not None,
            "verification": "farmer_reported",
        }

    def snapshot(self):
        tables = (
            "farms",
            "fields",
            "observations",
            "tasks",
            "task_actions",
            "followups",
        )

        with self.connect() as db:
            state = {
                table: [
                    dict(row)
                    for row in db.execute(
                        f"SELECT * FROM {table} ORDER BY id DESC"
                    )
                ]
                for table in tables
            }

        tasks = {
            row["id"]: row
            for row in state["tasks"]
        }
        observations = {
            row["id"]: row
            for row in state["observations"]
        }
        actions = {
            row["task_id"]: row
            for row in state["task_actions"]
        }

        summaries = {
            task_id: {
                "task_id": task_id,
                "eligible_followups": 0,
                "excluded_followups": 0,
                "reported_results": {
                    "improved": 0,
                    "unchanged": 0,
                    "worsened": 0,
                    "uncertain": 0,
                },
                "verification": "farmer_reported",
                "action_time_available": task_id in actions,
            }
            for task_id in tasks
        }

        for followup in state["followups"]:
            task = tasks.get(followup["task_id"])

            observation = (
                observations.get(task["observation_id"])
                if task
                else None
            )

            assessment = self._assess_followup(
                followup,
                task,
                observation,
                actions.get(followup["task_id"]),
            )

            followup["evidence_assessment"] = assessment

            # Preserve original evidence in the response and database.
            followup["original_evidence"] = followup["evidence"]

            if not assessment["eligible"]:
                reasons = "; ".join(assessment["reasons"])

                # Existing dashboard displays this warning without
                # requiring an HTML upgrade.
                followup["evidence"] = (
                    "[EXCLUDED FROM EVIDENCE SUMMARY: "
                    f"{reasons}] "
                    f"{followup['original_evidence']}"
                )

            summary = summaries.get(followup["task_id"])

            if summary is None:
                continue

            if assessment["eligible"]:
                summary["eligible_followups"] += 1
                summary["reported_results"][followup["result"]] += 1
            else:
                summary["excluded_followups"] += 1

        state["evidence_summaries"] = list(summaries.values())
        return state

    def create(self, kind, data):
        required = {
            "farms": ("name", "location"),
            "fields": ("farm_id", "name", "crop"),
            "observations": ("field_id", "note"),
        }

        if kind not in required:
            raise ValueError("Unknown record type")

        values = []

        for key in required[kind]:
            value = data.get(key)

            if key.endswith("_id"):
                if (
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or value < 1
                ):
                    raise ValueError("Select a valid parent record")
            else:
                if (
                    not isinstance(value, str)
                    or not value.strip()
                    or len(value) > 3000
                ):
                    raise ValueError(
                        "Complete all fields "
                        "(maximum 3000 characters)"
                    )

                value = value.strip()

            values.append(value)

        columns = list(required[kind])
        details = None

        if kind == "observations":
            columns.append("created")
            values.append(datetime.now(timezone.utc).isoformat())

            details = normalize(data)
            columns.extend(details.keys())
            values.extend(details.values())

        placeholders = ",".join("?" for _ in values)
        column_names = ",".join(columns)

        with self.connect() as db:
            cursor = db.execute(
                f"INSERT INTO {kind} ({column_names}) "
                f"VALUES ({placeholders})",
                values,
            )

            record_id = cursor.lastrowid

            if kind == "observations":
                triage = review(details)

                db.execute(
                    """
                    INSERT INTO tasks (
                        observation_id,
                        recommendation,
                        priority,
                        explanation,
                        missing_information,
                        rule_version
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record_id,
                        triage["recommendation"],
                        triage["priority"],
                        triage["explanation"],
                        json.dumps(triage["missing_information"]),
                        triage["rule_version"],
                    ),
                )

            return record_id

    def transition(self, task_id, action, outcome=None):
        with self.connect() as db:
            task = self._task_context(db, task_id)

            if action == "approve" and task["status"] == "pending":
                db.execute(
                    """
                    UPDATE tasks
                    SET status = 'approved'
                    WHERE id = ?
                    """,
                    (task_id,),
                )

            elif action == "complete" and task["status"] == "approved":
                if (
                    not isinstance(outcome, str)
                    or not outcome.strip()
                    or len(outcome) > 3000
                ):
                    raise ValueError(
                        "Record an outcome "
                        "(maximum 3000 characters)"
                    )

                completed_at = datetime.now(timezone.utc)

                if completed_at < self._observation_time(task):
                    raise ValueError(
                        "Completion cannot occur before "
                        "the original observation"
                    )

                db.execute(
                    """
                    UPDATE tasks
                    SET status = 'completed',
                        outcome = ?,
                        completed = ?
                    WHERE id = ?
                    """,
                    (
                        outcome.strip(),
                        completed_at.isoformat(),
                        task_id,
                    ),
                )

            else:
                raise ValueError(
                    "Invalid task transition: approve before completing"
                )

    def record_action(self, task_id, data):
        action_type = data.get("action_type")
        description = data.get("description")

        if action_type not in (
            "inspection",
            "manual_work",
            "adviser_consultation",
            "other",
        ):
            raise ValueError("Choose an action type")

        if (
            not isinstance(description, str)
            or not description.strip()
            or len(description) > 3000
        ):
            raise ValueError(
                "Describe what was actually done "
                "(maximum 3000 characters)"
            )

        performed_at = normalize(
            {"observed_at": data.get("performed_at")}
        )["observed_at"]

        recorded_at = datetime.now(timezone.utc).isoformat()

        with self.connect() as db:
            task = self._task_context(db, task_id)

            if task["status"] != "approved":
                raise ValueError(
                    "Approve the task before recording its action"
                )

            if self._parse_time(performed_at) < self._observation_time(task):
                raise ValueError(
                    "Action time must be on or after "
                    "the original observation time"
                )

            db.execute(
                """
                INSERT INTO task_actions (
                    task_id,
                    action_type,
                    description,
                    performed_at,
                    recorded_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    action_type,
                    description.strip(),
                    performed_at,
                    recorded_at,
                ),
            )

            db.execute(
                """
                UPDATE tasks
                SET status = 'completed',
                    outcome = ?,
                    completed = ?
                WHERE id = ?
                """,
                (
                    description.strip(),
                    recorded_at,
                    task_id,
                ),
            )

    def record_followup(self, task_id, data):
        result = data.get("result")
        evidence = data.get("evidence")

        if result not in (
            "improved",
            "unchanged",
            "worsened",
            "uncertain",
        ):
            raise ValueError("Choose a reported result")

        if (
            not isinstance(evidence, str)
            or not evidence.strip()
            or len(evidence) > 3000
        ):
            raise ValueError(
                "Describe follow-up evidence "
                "(maximum 3000 characters)"
            )

        observed_at = normalize(
            {"observed_at": data.get("observed_at")}
        )["observed_at"]

        followup_time = self._parse_time(observed_at)

        with self.connect() as db:
            task = self._task_context(db, task_id)

            if task["status"] != "completed":
                raise ValueError(
                    "Complete the task before recording follow-up evidence"
                )

            if followup_time < self._observation_time(task):
                raise ValueError(
                    "Follow-up time must be on or after "
                    "the original observation time"
                )

            action = db.execute(
                """
                SELECT performed_at
                FROM task_actions
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()

            if action:
                if followup_time < self._parse_time(action["performed_at"]):
                    raise ValueError(
                        "Follow-up time must be on or after "
                        "the action time"
                    )

            db.execute(
                """
                INSERT INTO followups (
                    task_id,
                    result,
                    evidence,
                    observed_at,
                    recorded_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    result,
                    evidence.strip(),
                    observed_at,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )