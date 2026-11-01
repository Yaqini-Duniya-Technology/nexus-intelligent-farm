import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False,
    )


def capture_review_evidence(db, reviews, supporting_bundle):
    """Freeze referenced bundles once, with the reviews that reference them."""
    captured = {}
    for review in reviews:
        bundle_id = review.get("evidence_bundle_id")
        expected = review.get("evidence_bundle_sha256")
        if bundle_id is None and expected is None:
            continue
        if (isinstance(bundle_id, bool) or not isinstance(bundle_id, int)
                or bundle_id < 1 or not isinstance(expected, str)):
            raise ValueError("Invalid review evidence reference")
        row = db.execute(
            "SELECT * FROM decision_review_bundles WHERE id=?", (bundle_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Reviewed evidence bundle not found")
        bundle = dict(row)
        try:
            bundle["payload"] = json.loads(bundle["payload"])
            # Review bundles use default JSON separators, unlike cycle snapshots.
            raw = json.dumps(bundle["payload"], sort_keys=True,
                             ensure_ascii=False, allow_nan=False)
            actual = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            def time(value):
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("Timezone missing")
                return parsed.astimezone(timezone.utc)
            if time(bundle["captured_at"]) > time(review["reviewed_at"]):
                raise ValueError("Evidence bundle postdates its review")
        except (TypeError, KeyError, AttributeError) as error:
            raise ValueError("Invalid reviewed evidence bundle") from error
        if actual != bundle["content_sha256"] or actual != expected:
            raise ValueError("Reviewed evidence bundle hash mismatch")
        if bundle["observation_id"] != supporting_bundle["observation_id"]:
            raise ValueError("Reviewed evidence belongs to another observation")
        if bundle_id not in captured:
            captured[bundle_id] = {"bundle": bundle, "review_ids": []}
        captured[bundle_id]["review_ids"].append(review["id"])
    return [captured[key] for key in sorted(captured)]


def capture(database, decision_id):
    if isinstance(decision_id, bool) or not isinstance(decision_id, int) or decision_id < 1:
        raise ValueError("Use a positive decision ID")
    path = Path(database).resolve()
    # mode=rw prevents accidentally creating an empty database.
    with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("""
                CREATE TABLE IF NOT EXISTS decision_cycle_snapshots (
                    id INTEGER PRIMARY KEY,
                    decision_id INTEGER NOT NULL REFERENCES human_decisions(id),
                    captured_at TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL
                )
            """)
            row = db.execute(
                "SELECT * FROM human_decisions WHERE id=?", (decision_id,)
            ).fetchone()
            if row is None:
                raise ValueError("Human decision not found")
            decision = dict(row)
            decision["payload"] = json.loads(decision["payload"])
            row = db.execute(
                "SELECT * FROM decision_review_bundles WHERE id=?",
                (decision["bundle_id"],),
            ).fetchone()
            if row is None:
                raise ValueError("Supporting bundle not found")
            bundle = dict(row)
            bundle["payload"] = json.loads(bundle["payload"])
            events = [dict(row) for row in db.execute(
                "SELECT * FROM decision_events WHERE decision_id=? ORDER BY id",
                (decision_id,),
            )]
            available = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='human_decision_reviews'"
            ).fetchone() is not None
            reviews = []
            if available:
                reviews = [dict(row) for row in db.execute(
                    "SELECT * FROM human_decision_reviews "
                    "WHERE decision_id=? ORDER BY id DESC", (decision_id,),
                )]
            latest = reviews[0] if reviews else None
            closed = bool(latest and latest["disposition"] == "close")
            active_date = None
            if available and not closed:
                active_date = (
                    latest["next_review_date"] if latest
                    else decision["payload"].get("review_date")
                )
            payload = {
                "snapshot_version": "decision-cycle-v2",
                "review_evidence_bundles": capture_review_evidence(db, reviews, bundle),
                "decision": decision,
                "supporting_bundle": bundle,
                "events": events,
                "reviews": reviews,
                "review_tracking": {
                    "records_available": available,
                    "latest_review_id": latest["id"] if latest else None,
                    "closed": closed if available else None,
                    "active_review_date": active_date,
                },
                "limitations": [
                    "Referenced review evidence bundles are frozen at capture; the original supporting bundle remains separate.",
                    "This captures records available at capture time, not the original decision time.",
                    "Actions, outcomes, identities and conclusions are user-entered.",
                    "Reported improvement does not establish an action's effectiveness or causation.",
                    "Supporting bundle photo metadata does not include image bytes.",
                    "Review tracking is separate from work completion and outcome verification.",
                    "Corrections remain separate entries; earlier entries are not automatically excluded.",
                    "A content hash detects changed content when checked; it does not authenticate the author.",
                ],
            }
            raw = canonical(payload)
            digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            db.execute(
                "INSERT INTO decision_cycle_snapshots "
                "(decision_id,captured_at,content_sha256,payload) VALUES (?,?,?,?) "
                "ON CONFLICT(content_sha256) DO NOTHING",
                (decision_id, datetime.now(timezone.utc).isoformat(), digest, raw),
            )
            result = dict(db.execute(
                "SELECT * FROM decision_cycle_snapshots WHERE content_sha256=?",
                (digest,),
            ).fetchone())
            db.commit()
        except Exception:
            db.rollback()
            raise
    result["payload"] = json.loads(result["payload"])
    return result


def main():
    parser = argparse.ArgumentParser(description="Save a NEXUS decision-cycle snapshot")
    parser.add_argument("--database", default="nexus-farm.sqlite3")
    parser.add_argument("--decision-id", type=int, required=True)
    parser.add_argument("--output-dir", default="exports")
    args = parser.parse_args()
    try:
        saved = capture(args.database, args.decision_id)
    except (ValueError, sqlite3.Error) as error:
        parser.exit(1, f"Capture failed: {error}\n")
    directory = Path(args.output_dir)
    target = directory / f"decision-cycle-{saved['id']}.json"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(saved, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except OSError as error:
        parser.exit(
            1, f"Snapshot #{saved['id']} was saved in the database, "
            f"but its JSON export failed: {error}\n",
        )
    print(f"Decision-cycle snapshot stored: #{saved['id']}")
    print(f"Captured at: {saved['captured_at']}")
    print(f"Content SHA-256: {saved['content_sha256']}")
    print(f"JSON copy: {target.resolve()}")
    print("Unchanged content reuses its existing snapshot and capture time.")
    print("Plans, bundles, actions, outcomes and reviews are unchanged.")


if __name__ == "__main__":
    main()
