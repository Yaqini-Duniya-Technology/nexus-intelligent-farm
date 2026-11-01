import json
from datetime import datetime, timezone

from nexus.farm_app.history import retrieve_history
from nexus.farm_app.observations import normalize, review


def create_observation_atomic(store, data):
    """
    Save an observation, its review task and its snapshot together.

    BEGIN IMMEDIATE prevents another writer from changing farm
    records while this transaction constructs its review context.
    """
    field_id = data.get("field_id")
    note = data.get("note")

    if (
        isinstance(field_id, bool)
        or not isinstance(field_id, int)
        or field_id < 1
    ):
        raise ValueError("Select a valid field")

    if (
        not isinstance(note, str)
        or not note.strip()
        or len(note) > 3000
    ):
        raise ValueError(
            "Describe the observation "
            "(maximum 3000 characters)"
        )

    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")

        # Use one timestamp for submission and default observation time.
        now = datetime.now(timezone.utc)
        details = normalize(data, now=now)
        triage = review(details, now=now)

        field = db.execute(
            "SELECT * FROM fields WHERE id = ?",
            (field_id,),
        ).fetchone()

        if not field:
            raise ValueError("Select an existing field")

        columns = [
            "field_id",
            "note",
            "created",
            *details.keys(),
        ]
        values = [
            field_id,
            note.strip(),
            now.isoformat(),
            *details.values(),
        ]

        placeholders = ",".join("?" for _ in values)

        cursor = db.execute(
            f"INSERT INTO observations ({','.join(columns)}) "
            f"VALUES ({placeholders})",
            values,
        )

        observation_id = cursor.lastrowid

        cursor = db.execute(
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
                observation_id,
                triage["recommendation"],
                triage["priority"],
                triage["explanation"],
                json.dumps(triage["missing_information"]),
                triage["rule_version"],
            ),
        )

        task_id = cursor.lastrowid

        # Read through the same connection to include the uncommitted
        # observation and task in the snapshot.
        tables = (
            "farms",
            "fields",
            "observations",
            "tasks",
            "task_actions",
            "followups",
        )

        state = {
            table: [
                dict(row)
                for row in db.execute(
                    f"SELECT * FROM {table} ORDER BY id DESC"
                )
            ]
            for table in tables
        }

        observations = {
            row["id"]: row
            for row in state["observations"]
        }
        tasks = {
            row["id"]: row
            for row in state["tasks"]
        }
        actions = {
            row["task_id"]: row
            for row in state["task_actions"]
        }

        # Apply the same historical-evidence checks used by the dashboard.
        for followup in state["followups"]:
            previous_task = tasks.get(followup["task_id"])
            previous_observation = (
                observations.get(previous_task["observation_id"])
                if previous_task
                else None
            )

            followup["original_evidence"] = followup["evidence"]
            followup["evidence_assessment"] = store._assess_followup(
                followup,
                previous_task,
                previous_observation,
                actions.get(followup["task_id"]),
            )

        history = retrieve_history(state, observation_id)
        history["status"] = "available"

        farm = db.execute(
            "SELECT * FROM farms WHERE id = ?",
            (field["farm_id"],),
        ).fetchone()

        captured_at = datetime.now(timezone.utc).isoformat()

        payload = {
            "snapshot_version": "review-context-v1",
            "captured_at": captured_at,
            # Retained for compatibility with the current audit display.
            "capture_kind": "post_creation_capture",
            "atomic_save": True,
            "capture_method": "same_transaction_v1",
            "task_id": task_id,
            "farm": dict(farm) if farm else None,
            "field": dict(field),
            "observation": observations[observation_id],
            "review": {
                "recommendation": triage["recommendation"],
                "priority": triage["priority"],
                "explanation": triage["explanation"],
                "missing_information": json.dumps(
                    triage["missing_information"]
                ),
                "rule_version": triage["rule_version"],
            },
            "history": history,
            "policy_effect": "descriptive_only",
            "verification": "farmer_reported",
        }

        db.execute(
            """
            INSERT INTO review_snapshots (
                task_id,
                captured_at,
                capture_kind,
                payload
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                task_id,
                captured_at,
                payload["capture_kind"],
                json.dumps(payload),
            ),
        )

        # The context manager commits only when all operations succeed.
        # Any exception rolls back the observation, task and snapshot.

    return {
        "observation_id": observation_id,
        "task_id": task_id,
    }