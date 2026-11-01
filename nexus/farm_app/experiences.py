import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from urllib.parse import urlparse

from nexus.farm_app.human_decisions import decision_state
from nexus.farm_app.decision_events import initialize_events


EXPERIENCE_VERSION = "experience-v1"


def initialize_experiences(store):
    """
    Experiences are derived evaluations of existing decision records.

    They do not replace:
      - review bundles
      - human decisions
      - action records
      - outcome records

    Those remain the authoritative evidence.
    """
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")

        db.execute("""
            CREATE TABLE IF NOT EXISTS decision_experiences (
                id INTEGER PRIMARY KEY,
                decision_id INTEGER NOT NULL
                    REFERENCES human_decisions(id),

                created_at TEXT NOT NULL,

                action_count INTEGER NOT NULL
                    CHECK(action_count >= 0),

                outcome_count INTEGER NOT NULL
                    CHECK(outcome_count >= 0),

                latest_result TEXT
                    CHECK(
                        latest_result IS NULL
                        OR latest_result IN (
                            'improved',
                            'unchanged',
                            'worsened',
                            'uncertain'
                        )
                    ),

                evidence_status TEXT NOT NULL
                    CHECK(
                        evidence_status IN (
                            'no_action',
                            'action_only',
                            'outcome_reported'
                        )
                    ),

                learning_status TEXT NOT NULL
                    CHECK(
                        learning_status IN (
                            'insufficient_evidence',
                            'recorded_experience',
                            'candidate_for_review'
                        )
                    ),

                experience_version TEXT NOT NULL
            )
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_decision_experiences_decision
            ON decision_experiences(decision_id)
        """)


def _decision_events(db, decision_id):
    return db.execute(
        """
        SELECT *
        FROM decision_events
        WHERE decision_id=?
        ORDER BY occurred_at ASC, id ASC
        """,
        (decision_id,),
    ).fetchall()


def evaluate_experience(events):
    """
    Convert an event history into conservative learning metadata.

    This function intentionally does NOT infer causality.
    """
    actions = [
        event for event in events
        if event["kind"] == "action"
    ]

    outcomes = [
        event for event in events
        if event["kind"] == "outcome"
    ]

    action_count = len(actions)
    outcome_count = len(outcomes)

    if action_count == 0:
        return {
            "action_count": 0,
            "outcome_count": 0,
            "latest_result": None,
            "evidence_status": "no_action",
            "learning_status": "insufficient_evidence",
        }

    if outcome_count == 0:
        return {
            "action_count": action_count,
            "outcome_count": 0,
            "latest_result": None,
            "evidence_status": "action_only",
            "learning_status": "insufficient_evidence",
        }

    latest_outcome = outcomes[-1]
    latest_result = latest_outcome["result"]

    # A reported outcome gives us a recorded experience,
    # but does not establish that the action caused it.
    learning_status = "recorded_experience"

    # Only clearly directional reported outcomes become
    # candidates for later human/scientific review.
    if latest_result in ("improved", "worsened"):
        learning_status = "candidate_for_review"

    return {
        "action_count": action_count,
        "outcome_count": outcome_count,
        "latest_result": latest_result,
        "evidence_status": "outcome_reported",
        "learning_status": learning_status,
    }


def build_experience(store, decision_id):
    """
    Build a new immutable experience snapshot for a decision.

    Earlier snapshots remain available for audit history.
    """
    if (
        isinstance(decision_id, bool)
        or not isinstance(decision_id, int)
        or decision_id < 1
    ):
        raise ValueError("Select a valid human decision")

    initialize_events(store)
    initialize_experiences(store)

    with closing(sqlite3.connect(store.path)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")

        decision = db.execute(
            """
            SELECT *
            FROM human_decisions
            WHERE id=?
            """,
            (decision_id,),
        ).fetchone()

        if not decision:
            raise ValueError("Human decision not found")

        events = _decision_events(db, decision_id)
        evaluation = evaluate_experience(events)

        created_at = datetime.now(timezone.utc).isoformat()

        cursor = db.execute(
            """
            INSERT INTO decision_experiences (
                decision_id,
                created_at,
                action_count,
                outcome_count,
                latest_result,
                evidence_status,
                learning_status,
                experience_version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision_id,
                created_at,
                evaluation["action_count"],
                evaluation["outcome_count"],
                evaluation["latest_result"],
                evaluation["evidence_status"],
                evaluation["learning_status"],
                EXPERIENCE_VERSION,
            ),
        )

        row = db.execute(
            """
            SELECT *
            FROM decision_experiences
            WHERE id=?
            """,
            (cursor.lastrowid,),
        ).fetchone()

        return dict(row)


def experience_state(store):
    initialize_events(store)
    initialize_experiences(store)

    state = decision_state(store)

    with closing(sqlite3.connect(store.path)) as db:
        db.row_factory = sqlite3.Row

        state["events"] = [
            dict(row)
            for row in db.execute(
                """
                SELECT *
                FROM decision_events
                ORDER BY id DESC
                """
            )
        ]

        state["experiences"] = [
            dict(row)
            for row in db.execute(
                """
                SELECT *
                FROM decision_experiences
                ORDER BY id DESC
                """
            )
        ]

    return state