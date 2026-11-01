import json
from datetime import datetime, timezone

from nexus.farm_app.history import retrieve_history


def initialize_audit(store):
    with store.connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS review_snapshots (
                task_id INTEGER PRIMARY KEY REFERENCES tasks(id),
                captured_at TEXT NOT NULL,
                capture_kind TEXT NOT NULL,
                payload TEXT NOT NULL
            )
        """)


def capture_missing_snapshots(store, capture_kind):
    """
    Preserve one review snapshot per task.

    Snapshots are insert-only in this application. They are not
    cryptographically tamper-proof and do not train a model.
    """
    if capture_kind not in (
        "post_creation_capture",
        "legacy_reconstruction",
        "recovery_reconstruction",
    ):
        raise ValueError("Invalid snapshot capture kind")

    initialize_audit(store)

    with store.connect() as db:
        existing = {
            row["task_id"]
            for row in db.execute(
                "SELECT task_id FROM review_snapshots"
            )
        }

    state = store.snapshot()

    observations = {
        row["id"]: row
        for row in state["observations"]
    }

    fields = {
        row["id"]: row
        for row in state["fields"]
    }

    farms = {
        row["id"]: row
        for row in state["farms"]
    }

    for task in state["tasks"]:
        if task["id"] in existing:
            continue

        observation = observations.get(task["observation_id"])
        field = (
            fields.get(observation["field_id"])
            if observation
            else None
        )
        farm = (
            farms.get(field["farm_id"])
            if field
            else None
        )

        try:
            history = retrieve_history(
                state,
                task["observation_id"],
            )
        except ValueError as error:
            history = {
                "status": "unavailable",
                "reason": str(error),
                "policy_effect": "descriptive_only",
            }
        else:
            history["status"] = "available"

        captured_at = datetime.now(timezone.utc).isoformat()

        payload = {
            "snapshot_version": "review-context-v1",
            "captured_at": captured_at,
            "capture_kind": capture_kind,
            "task_id": task["id"],
            "farm": farm,
            "field": field,
            "observation": observation,
            "review": {
                "recommendation": task["recommendation"],
                "priority": task.get("priority"),
                "explanation": task.get("explanation"),
                "missing_information": task.get(
                    "missing_information"
                ),
                "rule_version": task.get("rule_version"),
            },
            "history": history,
            "policy_effect": "descriptive_only",
            "verification": "farmer_reported",
        }

        with store.connect() as db:
            db.execute(
                """
                INSERT OR IGNORE INTO review_snapshots (
                    task_id,
                    captured_at,
                    capture_kind,
                    payload
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    task["id"],
                    captured_at,
                    capture_kind,
                    json.dumps(payload),
                ),
            )


def history_explanation(history):
    if history.get("status") != "available":
        return (
            "Farm memory: historical context was unavailable "
            "when this snapshot was captured."
        )

    reports = history["eligible_reports"]
    matches = history["matching_observations"]
    counts = history["reported_results"]

    if not reports:
        return (
            "Farm memory: no earlier eligible follow-up reports "
            "were available from this field and category "
            "within the observation's submission-time cutoff."
        )

    return (
        f"Farm memory: {matches} earlier observation(s) contain "
        f"{reports} eligible farmer-reported follow-up(s). "
        f"Reported results: improved {counts['improved']}, "
        f"unchanged {counts['unchanged']}, "
        f"worsened {counts['worsened']}, "
        f"uncertain {counts['uncertain']}. "
        "These reports do not establish the same diagnosis, "
        "treatment effectiveness or causation."
    )


def audited_state(store):
    state = store.snapshot()

    with store.connect() as db:
        snapshots = {
            row["task_id"]: {
                "captured_at": row["captured_at"],
                "capture_kind": row["capture_kind"],
                "payload": json.loads(row["payload"]),
            }
            for row in db.execute(
                "SELECT * FROM review_snapshots"
            )
        }

    for task in state["tasks"]:
        snapshot = snapshots.get(task["id"])

        if snapshot is None:
            task["review_snapshot"] = {
                "status": "missing",
            }
            task["explanation"] = (
                (task.get("explanation") or "")
                + " Review snapshot unavailable."
            ).strip()
            continue

        payload = snapshot["payload"]
        original = payload["review"].get("explanation") or ""
        history = payload["history"]

        if snapshot["capture_kind"] == "post_creation_capture":
            provenance = (
                "Stored review snapshot captured immediately "
                "after task creation."
            )
        else:
            provenance = (
                "Stored review snapshot reconstructed after "
                "task creation; it is not an original "
                "decision-time record."
            )

        task["original_explanation"] = task.get("explanation")
        task["explanation"] = " ".join(
            part
            for part in (
                original,
                history_explanation(history),
                provenance,
                "Historical context is descriptive. "
                "The recommendation and priority are unchanged.",
            )
            if part
        )

        task["historical_context"] = history
        task["review_snapshot"] = {
            "status": "stored",
            "captured_at": snapshot["captured_at"],
            "capture_kind": snapshot["capture_kind"],
            "snapshot_version": payload["snapshot_version"],
        }

    return state


def get_snapshot(store, task_id):
    with store.connect() as db:
        row = db.execute(
            """
            SELECT payload
            FROM review_snapshots
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()

    if row is None:
        raise ValueError("Review snapshot not found")

    return json.loads(row["payload"])