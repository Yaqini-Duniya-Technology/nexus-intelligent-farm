from nexus.farm_app.resource_logistics import capture as capture_resource_links
from nexus.farm_app.studio_reports import capture_context as capture_studio_context
from nexus.farm_app.work_orders import capture_for_observation
from nexus.farm_app.field_inspections import capture_history as capture_inspections
from nexus.farm_app.season_context import capture_history

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def clarification_history(db, tables, observation_id):
    """Capture checked answer payloads through the bundle transaction."""
    if "voice_clarification_answers" not in tables:
        return []
    rows = db.execute(
        "SELECT * FROM voice_clarification_answers "
        "WHERE observation_id=? ORDER BY id DESC", (observation_id,)
    ).fetchall()
    if rows and "natlas_voice_observation_links" not in tables:
        raise ValueError("Clarification answers have no confirmation table")
    entries = []
    for row in rows:
        try:
            payload = json.loads(row["payload"])
            canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":"), allow_nan=False)
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if digest != row["content_sha256"]:
                raise ValueError("Answer content hash mismatch")
            link = db.execute(
                "SELECT * FROM natlas_voice_observation_links WHERE id=?",
                (row["link_id"],),
            ).fetchone()
            if link is None or link["observation_id"] != observation_id:
                raise ValueError("Answer confirmation link mismatch")
            capture = json.loads(link["provenance"])
            review = capture["human_review"]
            review_raw = json.dumps(review, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False)
            review_hash = hashlib.sha256(review_raw.encode("utf-8")).hexdigest()
            if (review_hash != capture["human_review_sha256"]
                    or payload["review_hash"] != review_hash
                    or payload["observation_id"] != observation_id
                    or payload["review_id"] != link["review_id"]
                    or payload["version"] != "voice-clarification-answers-v1"
                    or payload["questions"] != review["extraction"]["clarification_questions"]):
                raise ValueError("Answer review context mismatch")
            questions, answers = payload["questions"], payload["answers"]
            if (not isinstance(questions, list) or not 1 <= len(questions) <= 3
                    or not isinstance(answers, list) or len(questions) != len(answers)
                    or any(not isinstance(v, str) or not v.strip()
                           for v in questions + answers)
                    or not isinstance(payload["reporter"], str)
                    or not payload["reporter"].strip()):
                raise ValueError("Invalid answer payload")
            entry = dict(row)
            entry["payload"] = payload
            entries.append(entry)
        except (ValueError, KeyError, TypeError) as error:
            raise ValueError(
                f"Clarification entry #{row['id']} could not be checked: {error}"
            ) from None
    return entries


def linked_decision_records(db, tables, observation_id):
    if "human_decisions" not in tables:
        return []
    decisions = db.execute(
        "SELECT d.* FROM human_decisions d "
        "JOIN decision_review_bundles b ON b.id=d.bundle_id "
        "WHERE b.observation_id=? ORDER BY d.id DESC", (observation_id,)
    ).fetchall() if "decision_review_bundles" in tables else []
    result = []
    for row in decisions:
        decision = dict(row)
        decision["payload"] = json.loads(decision["payload"])
        events = None
        if "decision_events" in tables:
            events = [dict(event) for event in db.execute(
                "SELECT * FROM decision_events WHERE decision_id=? ORDER BY id DESC",
                (decision["id"],),
            )]
            by_id = {event["id"]: event for event in events}
            for event in events:
                if event["kind"] == "outcome":
                    action = by_id.get(event["action_id"])
                    if action is None or action["kind"] != "action":
                        raise ValueError("Decision outcome has an invalid action link")
                elif event["kind"] != "action":
                    raise ValueError("Unknown decision event kind")
        result.append({"decision": decision, "events": events})
    return result


def capture_review(database, observation_id, weather_id=None):
    if observation_id < 1 or (
        weather_id is not None and weather_id < 1
    ):
        raise ValueError("Use positive record IDs")

    path = Path(database).resolve()

    if not path.is_file():
        raise ValueError("Database file not found")

    with closing(sqlite3.connect(path)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")

        tables = {
            row["name"]
            for row in db.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            )
        }

        required = {"observations", "fields", "farms", "tasks"}

        if not required <= tables:
            raise ValueError(
                "This is not a supported NEXUS farm database"
            )

        def one(sql, arguments):
            row = db.execute(sql, arguments).fetchone()
            return dict(row) if row else None

        def many(table, column, record_id):
            if table not in tables:
                return []

            return [
                dict(row)
                for row in db.execute(
                    f"""
                    SELECT *
                    FROM {table}
                    WHERE {column} = ?
                    ORDER BY id DESC
                    """,
                    (record_id,),
                )
            ]

        observation = one(
            "SELECT * FROM observations WHERE id = ?",
            (observation_id,),
        )

        if not observation:
            raise ValueError("Observation not found")

        field = one(
            "SELECT * FROM fields WHERE id = ?",
            (observation["field_id"],),
        )

        if not field:
            raise ValueError("Field not found")

        farm = one(
            "SELECT * FROM farms WHERE id = ?",
            (field["farm_id"],),
        )

        if not farm:
            raise ValueError("Farm not found")

        task = one(
            "SELECT * FROM tasks WHERE observation_id = ?",
            (observation_id,),
        )

        contexts = many(
            "field_context_versions",
            "field_id",
            field["id"],
        )

        contexts.sort(
            key=lambda context: (
                context["context_date"],
                context["id"],
            ),
            reverse=True,
        )

        reviews = many(
            "adviser_reviews",
            "observation_id",
            observation_id,
        )

        photos = []

        if "observation_photos" in tables:
            columns = {
                row["name"]
                for row in db.execute(
                    "PRAGMA table_info(observation_photos)"
                )
            }

            source = (
                "source_kind"
                if "source_kind" in columns
                else "'unknown' AS source_kind"
            )

            photos = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT
                        id,
                        observation_id,
                        caption,
                        sha256,
                        uploaded_at,
                    """
                    + source
                    + """
                    FROM observation_photos
                    WHERE observation_id = ?
                    ORDER BY id DESC
                    """,
                    (observation_id,),
                )
            ]

        weather = None

        if weather_id is not None:
            if "weather_snapshots" not in tables:
                raise ValueError(
                    "No weather snapshots table found"
                )

            weather = one(
                "SELECT * FROM weather_snapshots WHERE id = ?",
                (weather_id,),
            )

            if not weather:
                raise ValueError("Weather snapshot not found")

            weather["payload"] = json.loads(weather["payload"])

        original = None
        actions = []
        followups = []

        if task:
            if "review_snapshots" in tables:
                original = one(
                    """
                    SELECT *
                    FROM review_snapshots
                    WHERE task_id = ?
                    """,
                    (task["id"],),
                )

            actions = many(
                "task_actions",
                "task_id",
                task["id"],
            )

            followups = many(
                "followups",
                "task_id",
                task["id"],
            )

        # Read relevant corrections within this same transaction.
        corrections = []

        if "record_corrections" in tables:
            targets = [
                ("farms", farm["id"]),
                ("observations", observation_id),
            ]

            targets.extend(
                ("task_actions", action["id"])
                for action in actions
            )

            for table_name, record_id in targets:
                corrections.extend(
                    dict(row)
                    for row in db.execute(
                        """
                        SELECT *
                        FROM record_corrections
                        WHERE table_name = ?
                          AND record_id = ?
                        """,
                        (table_name, record_id),
                    )
                )

            corrections.sort(
                key=lambda correction: correction["id"]
            )

        clarifications = clarification_history(db, tables, observation_id)
        linked_decisions = linked_decision_records(db, tables, observation_id)

        optional_tables = {
            "observation_season_history",
            "field_inspections",
            "field_measurements",
            "field_case_entries",
            "field_notebook",
            "field_evidence_links",
            "work_orders",
            "work_order_events",
            "field_context_versions",
            "adviser_reviews",
            "observation_photos",
            "review_snapshots",
            "task_actions",
            "followups",
            "record_corrections",
            "voice_clarification_answers",
            "natlas_voice_observation_links",
            "human_decisions",
            "decision_events",
        }

        content = {
            "bundle_version": "human-review-bundle-v9",
            "field_inspections": capture_inspections(db, tables, observation),
            "planned_work_orders": capture_for_observation(db,tables,observation_id),
            "evidence_studio": capture_studio_context(db,tables,observation),
            "resource_case_links": capture_resource_links(db,tables,observation_id),
            "observation_season_history": capture_history(db, tables, observation),
            "review_kind": "current_record_capture",
            "farm": farm,
            "field": field,
            "observation": observation,
            "latest_field_context": (
                contexts[0] if contexts else None
            ),
            "task": task,
            "original_review_snapshot": original,
            "adviser_reviews": reviews,
            "photo_metadata": photos,
            "task_actions": actions,
            "raw_followups": followups,
            "manually_selected_weather": weather,
            "record_corrections": corrections,
            "voice_clarification_history": clarifications,
            "linked_human_decisions": linked_decisions,
            "unavailable_tables": sorted(
                optional_tables - tables
            ),
            "limitations": [
                "Season context preserves user-reported links and growth stages; it does not verify season identity or maturity.",
                "Linked human decisions are selected through their supporting bundle's observation ID, not by free-text matching.",
                "Decision actions and outcomes are separate from workspace task actions and followups; they do not change task status.",
                "Supporting bundle IDs are retained as references; their payloads are not recursively copied.",
                "Linked decision events are user-reported and do not establish causation, effectiveness or a verified diagnosis.",
                "Clarification answers and reporter identities are user-entered and not independently verified.",
                "Clarification history is ordered newest saved entry first; earlier entries are retained and may differ.",
                "Answer hashes and confirmation links check stored consistency, not agricultural accuracy or model provenance.",
                "Clarification answers may postdate the observation; they do not rewrite the original voice capture.",
                (
                    "Current records may postdate the observation "
                    "or original task."
                ),
                "This is not the original decision-time record.",
                (
                    "Correction history covers this farm, "
                    "observation and its task actions only."
                ),
                (
                    "Correction reasons are user-entered "
                    "and not independently verified."
                ),
                (
                    "Field context is user-reported "
                    "and may be outdated."
                ),
                (
                    "Adviser identities and conclusions "
                    "are not independently verified."
                ),
                (
                    "Photo metadata is captured; image bytes "
                    "are not copied into this bundle."
                ),
                "Test images are not real farm evidence.",
                (
                    "Raw followups are included without "
                    "applying evidence eligibility checks."
                ),
                (
                    "Weather selection does not establish "
                    "geographic or temporal relevance."
                ),
                (
                    "No diagnosis, intervention selection "
                    "or task update is performed."
                ),
            ],
        }

        raw = json.dumps(
            content,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )

        digest = hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS decision_review_bundles (
                id INTEGER PRIMARY KEY,
                observation_id INTEGER NOT NULL
                    REFERENCES observations(id),
                captured_at TEXT NOT NULL,
                content_sha256 TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL
            )
            """
        )

        db.execute(
            """
            INSERT INTO decision_review_bundles (
                observation_id,
                captured_at,
                content_sha256,
                payload
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(content_sha256) DO NOTHING
            """,
            (
                observation_id,
                datetime.now(timezone.utc).isoformat(),
                digest,
                raw,
            ),
        )

        bundle = one(
            """
            SELECT *
            FROM decision_review_bundles
            WHERE content_sha256 = ?
            """,
            (digest,),
        )

        bundle["payload"] = json.loads(bundle["payload"])
        return bundle


def main():
    parser = argparse.ArgumentParser(
        description="Capture current NEXUS review records"
    )

    parser.add_argument(
        "--database",
        default="nexus-farm.sqlite3",
    )
    parser.add_argument(
        "--observation-id",
        type=int,
        required=True,
    )
    parser.add_argument(
        "--weather-id",
        type=int,
    )

    args = parser.parse_args()

    try:
        bundle = capture_review(
            args.database,
            args.observation_id,
            args.weather_id,
        )

        folder = Path("exports")
        folder.mkdir(exist_ok=True)

        output = folder / (
            f"decision-review-bundle-{bundle['id']}.json"
        )

        output.write_text(
            json.dumps(
                bundle,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    except (ValueError, sqlite3.Error, OSError) as error:
        parser.exit(
            1,
            f"Could not finish review capture: {error}\n"
            "Check saved bundles before retrying; a file-export "
            "error may occur after saving.\n",
        )

    print(f"Review bundle stored: #{bundle['id']}")
    print(f"Captured at: {bundle['captured_at']}")
    print(f"JSON copy: {output.resolve()}")
    print(
        "Unchanged content reuses the existing bundle. "
        "Tasks and original snapshots are unchanged."
    )


if __name__ == "__main__":
    main()