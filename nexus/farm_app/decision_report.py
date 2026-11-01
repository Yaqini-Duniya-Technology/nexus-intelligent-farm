import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from nexus.farm_app.review_bundles import local_time, text


def reviewed_evidence(db, review):
    bundle_id = review.get("evidence_bundle_id")
    if bundle_id is None:
        return None
    info = {"bundle_id": bundle_id, "reference_sha256": review.get("evidence_bundle_sha256"),
            "status": "Referenced bundle is unavailable."}
    row = db.execute(
        "SELECT captured_at, content_sha256, payload FROM decision_review_bundles WHERE id=?",
        (bundle_id,),
    ).fetchone()
    if row is None:
        return info
    info["captured_at"] = row["captured_at"]
    try:
        payload = json.loads(row["payload"])
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False)
        computed = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if computed == row["content_sha256"] == info["reference_sha256"]:
            info["status"] = "Stored reference and current saved bundle content hashes match."
        else:
            info["status"] = "Hash mismatch: the saved bundle could not be matched to this review reference."
    except (ValueError, TypeError):
        info["status"] = "Referenced bundle content could not be checked."
    return info


def render_review_evidence(review):
    bundle_id = review.get("evidence_bundle_id")
    if bundle_id is None:
        return "<p>No additional evidence bundle reference recorded for this review.</p>"
    info = review.get("evidence_reference") or {}
    content = "<h4>Evidence referenced by this review</h4>"
    if type(bundle_id) is int and bundle_id > 0:
        content += ('<p><a href="/review-bundles?bundle_id=' + str(bundle_id)
                    + '">Read reviewed evidence bundle #' + text(bundle_id) + '</a></p>')
    content += details([
        ("Evidence bundle ID", bundle_id),
        ("Evidence bundle captured", local_time(info.get("captured_at"))),
        ("SHA-256 saved with review", review.get("evidence_bundle_sha256")),
        ("Reference check at report load", info.get("status", "Not checked in this report")),
    ])
    return content + "<p>This reference does not replace the decision's original supporting bundle. Hash checks do not verify the reported findings or authenticate the reviewer.</p>"


def read_report(store, decision_id=None):
    with closing(sqlite3.connect(store.path)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")

        if decision_id is None:
            rows = db.execute(
                """
                SELECT id, bundle_id, recorded_at, payload
                FROM human_decisions
                ORDER BY id DESC
                """
            ).fetchall()

            decisions = []

            for row in rows:
                item = dict(row)
                item["payload"] = json.loads(item["payload"])
                decisions.append(item)

            return decisions

        row = db.execute(
            """
            SELECT *
            FROM human_decisions
            WHERE id = ?
            """,
            (decision_id,),
        ).fetchone()

        if not row:
            raise ValueError("Human decision not found")

        decision = dict(row)
        decision["payload"] = json.loads(decision["payload"])

        row = db.execute(
            """
            SELECT *
            FROM decision_review_bundles
            WHERE id = ?
            """,
            (decision["bundle_id"],),
        ).fetchone()

        if not row:
            raise ValueError("Supporting bundle not found")

        bundle = dict(row)
        bundle["payload"] = json.loads(bundle["payload"])

        events = [
            dict(row)
            for row in db.execute(
                """
                SELECT *
                FROM decision_events
                WHERE decision_id = ?
                ORDER BY occurred_at, id
                """,
                (decision_id,),
            )
        ]

        reviews_available = db.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'human_decision_reviews'
            """
        ).fetchone() is not None

        reviews = []

        if reviews_available:
            reviews = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT *
                    FROM human_decision_reviews
                    WHERE decision_id = ?
                    ORDER BY id DESC
                    """,
                    (decision_id,),
                )
            ]

        season_evidence = []
        seen = set()
        for review in reviews:
            review["evidence_reference"] = reviewed_evidence(db, review)
            ref = review["evidence_reference"]
            bid = review.get("evidence_bundle_id")
            if ref and bid not in seen and ref.get("status") == "Stored reference and current saved bundle content hashes match.":
                evidence = db.execute("SELECT payload FROM decision_review_bundles WHERE id=?", (bid,)).fetchone()
                season_evidence.append({"bundle_id": bid, "payload": json.loads(evidence["payload"])})
                seen.add(bid)

        return {
            "season_evidence": season_evidence,
            "decision": decision,
            "bundle": bundle,
            "events": events,
            "reviews": reviews,
            "reviews_available": reviews_available,
            "loaded_at": datetime.now(timezone.utc).isoformat(),
        }


def page(content):
    return (
        """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS decision report</title>
<style>
*{box-sizing:border-box}
body{
    margin:0;
    background:#f1f5ee;
    color:#183c2c;
    font:16px system-ui;
}
header{
    background:#163f30;
    color:white;
    padding:28px;
}
main{max-width:1000px;margin:auto;padding:24px}
section{
    background:white;
    padding:22px;
    border-radius:14px;
    margin:18px 0;
}
article{
    border-top:1px solid #ccd8ce;
    padding:16px 0;
}
a{color:inherit;margin-right:18px}
dt{font-weight:bold;margin-top:14px}
dd{
    margin:4px 0;
    white-space:pre-wrap;
    overflow-wrap:anywhere;
}
p{white-space:pre-wrap;overflow-wrap:anywhere}
button{font:inherit;padding:12px;cursor:pointer}
@media print{
    nav,button,.screen-only{display:none}
    body{background:white}
    header{color:#183c2c}
    section{border:1px solid #ccc}
}
</style>
</head>
<body>
<header>
<small>LOCAL PILOT · DECISION REPORT</small>
<h1>NEXUS decision report</h1>
<nav>
<a href="/decision-report">All decision reports</a>
<a href="/human-decisions">Human decisions</a>
<a href="/decision-reviews">Decision reviews</a>
<a href="/decision-events">Actions & outcomes</a>
<a href="/review-bundles">Saved bundles</a>
<a href="/overview">Dashboard</a>
</nav>
</header>
<main>
<p>This report combines a saved human plan, its supporting bundle and
current linked action/outcome records and review history. Refresh before printing.
It is not a frozen capture of the complete decision cycle.</p>
"""
        + content
        + "</main></body></html>"
    )


def details(pairs):
    result = "<dl>"

    for label, value in pairs:
        result += (
            "<dt>"
            + text(label)
            + "</dt><dd>"
            + text(value)
            + "</dd>"
        )

    return result + "</dl>"


def review_tracking(report):
    reviews = report.get("reviews", [])
    latest = reviews[0] if reviews else None
    original = report["decision"]["payload"].get("review_date")

    if not report.get("reviews_available", False):
        return "Review tracking unavailable", None

    if latest and latest["disposition"] == "close":
        return "Review tracking closed", None

    active = latest["next_review_date"] if latest else original

    try:
        planned = date.fromisoformat(active)

        if planned.isoformat() != active:
            raise ValueError("Non-canonical date")

    except (TypeError, ValueError):
        return "Review date unavailable", active

    today = datetime.fromisoformat(
        report["loaded_at"]
    ).astimezone(
        timezone(timedelta(hours=1))
    ).date()

    if planned < today:
        days = (today - planned).days
        label = f"Planned review date overdue by {days} day(s)"

    elif planned == today:
        label = "Planned review date is today"

    else:
        label = "Planned review date is upcoming"

    if latest and latest["disposition"] == "revise":
        label += " · Plan revision requested"

    return label, active


def render_reviews(report):
    status, active_date = review_tracking(report)

    content = "<section><h2>Current review tracking</h2>"

    content += details([
        ("Tracking status", status),
        ("Active review date", active_date or "None"),
        ("Report loaded", local_time(report["loaded_at"])),
    ])

    content += (
        '<p class="screen-only"><a href="/decision-reviews">'
        'Record or read reviews</a></p>'
        '<p>Review tracking is separate from work and reported outcomes. '
        'Closing tracking does not establish successful work. A revision '
        'request does not replace the saved plan. No background notification '
        'is created.</p></section>'
        '<section><h2>Review history — newest saved entry first</h2>'
    )

    if not report["reviews_available"]:
        content += "<p>The review records table is unavailable.</p>"

    elif not report["reviews"]:
        content += "<p>No review recorded for this decision.</p>"

    labels = {
        "keep": "Keep plan and set next review date",
        "revise": "Request plan revision and set next review date",
        "close": "Close review tracking",
    }

    for review in report["reviews"]:
        content += (
            "<article><h3>Review #"
            + text(review["id"])
            + "</h3>"
        )

        content += details([
            (
                "Reviewer / role as reported",
                review["reviewer"],
            ),
            (
                "Reviewed",
                local_time(review["reviewed_at"]),
            ),
            (
                "Recorded",
                local_time(review["recorded_at"]),
            ),
            (
                "Findings / unresolved issues",
                review["conclusion"],
            ),
            (
                "Review conclusion",
                labels.get(
                    review["disposition"],
                    review["disposition"],
                ),
            ),
            (
                "Next review date",
                review["next_review_date"] or "None",
            ),
        ])

        content += render_review_evidence(review)
        content += "</article>"

    return content + (
        "<p>Earlier entries remain available. The latest saved review "
        "updates tracking without changing the original decision or "
        "supporting bundle. Identities and conclusions are user-entered.</p>"
        "</section>"
    )


def render_report(report):
    decision = report["decision"]
    bundle = report["bundle"]
    payload = decision["payload"]
    captured = bundle["payload"]
    events = report["events"]

    actions = [
        event
        for event in events
        if event["kind"] == "action"
    ]

    outcomes = [
        event
        for event in events
        if event["kind"] == "outcome"
    ]

    if not actions:
        status = "Awaiting recorded work"

    elif not outcomes:
        status = "Work recorded; awaiting a reported outcome"

    else:
        status = (
            "Outcome reports recorded; effectiveness is unverified"
        )

    content = (
        "<section><h2>Decision #"
        + text(decision["id"])
        + "</h2><p>"
        + text(status)
        + "</p>"
        '<button onclick="window.print()">'
        "Print / save as PDF</button>"
        + details([
            (
                "Decision recorded",
                local_time(decision["recorded_at"]),
            ),
            (
                "Decision maker as reported",
                payload.get("decision_maker"),
            ),
            (
                "Chosen next step",
                payload.get("next_step"),
            ),
            (
                "Supporting evidence",
                payload.get("supporting_evidence"),
            ),
            (
                "Uncertainties",
                payload.get("uncertainties"),
            ),
            (
                "Resources / constraints",
                payload.get("constraints"),
            ),
            (
                "Original planned review date",
                payload.get("review_date"),
            ),
        ])
        + "<p>The review date does not create a reminder.</p>"
        "</section>"
    )

    from nexus.farm_app.season_context import render_history
    from nexus.farm_app.field_inspections import render_history as render_inspections
    content += render_inspections(captured, 'Inspections in the original supporting bundle')
    content += render_history(captured, 'Season context in the original supporting bundle')
    for evidence in report.get('season_evidence', []):
        content += render_inspections(evidence['payload'], f"Inspections in reviewed bundle #{evidence['bundle_id']}")
        content += render_history(evidence['payload'], f"Season context in reviewed bundle #{evidence['bundle_id']}")
    content += render_reviews(report)

    farm = captured.get("farm") or {}
    field = captured.get("field") or {}
    observation = captured.get("observation") or {}

    field_label = (
        str(field.get("name", ""))
        + " / "
        + str(field.get("crop", ""))
    )

    content += (
        "<section>"
        "<h2>Original supporting evidence at decision creation</h2>"
        '<p><a href="/review-bundles?bundle_id='
        + str(bundle["id"])
        + '">Read saved bundle #'
        + text(bundle["id"])
        + "</a></p>"
        + details([
            (
                "Bundle captured",
                local_time(bundle["captured_at"]),
            ),
            (
                "Bundle version",
                captured.get("bundle_version"),
            ),
            (
                "Farm",
                farm.get("name"),
            ),
            (
                "Field / crop",
                field_label,
            ),
            (
                "Observation",
                observation.get("note"),
            ),
            (
                "Observation source",
                observation.get("source"),
            ),
        ])
        + "<p>Earlier inspection and follow-up records in "
        "the bundle are supporting evidence. They are not "
        "work performed under this later decision.</p>"
        "</section>"
    )

    content += (
        "<section>"
        "<h2>Linked work and reported outcomes</h2>"
    )

    if not actions:
        content += "<p>No work recorded for this decision.</p>"

    for action in actions:
        content += (
            "<article><h3>Action #"
            + text(action["id"])
            + "</h3>"
            + details([
                (
                    "Performed",
                    local_time(action["occurred_at"]),
                ),
                (
                    "Recorded",
                    local_time(action["recorded_at"]),
                ),
                (
                    "Work / findings",
                    action["description"],
                ),
            ])
        )

        linked = [
            event
            for event in outcomes
            if event["action_id"] == action["id"]
        ]

        if not linked:
            content += (
                "<p>No outcome report linked to this action.</p>"
            )

        for outcome in linked:
            content += (
                "<h4>Reported outcome #"
                + text(outcome["id"])
                + "</h4>"
                + details([
                    (
                        "Reported result",
                        outcome["result"],
                    ),
                    (
                        "Observed",
                        local_time(outcome["occurred_at"]),
                    ),
                    (
                        "Recorded",
                        local_time(outcome["recorded_at"]),
                    ),
                    (
                        "Evidence / limitations",
                        outcome["description"],
                    ),
                ])
                + "<p>Not independently verified.</p>"
            )

        content += "</article>"

    content += (
        "</section><section><h2>Interpretation</h2>"
        "<p>Actions and outcomes are entered by the workspace "
        "user. Chronological linkage does not prove that the "
        "action caused the outcome. No success rate or "
        "diagnosis is calculated.</p>"
        "<p>Record corrections remain separate entries. "
        "This report does not automatically exclude or "
        "replace earlier entries.</p>"
        "</section>"
    )

    return page(content)


def report_handler(base_factory):
    def make_handler(store):
        class Handler(base_factory(store)):
            def do_GET(self):
                parsed = urlparse(self.path)

                if parsed.path != "/decision-report":
                    return super().do_GET()

                try:
                    query = parse_qs(
                        parsed.query,
                        keep_blank_values=True,
                    )

                    values = query.get("decision_id")

                    if values is not None:
                        if len(values) != 1:
                            raise ValueError(
                                "Provide one decision ID"
                            )

                        decision_id = int(values[0])

                        if decision_id < 1:
                            raise ValueError(
                                "Use a positive decision ID"
                            )

                        html = render_report(
                            read_report(store, decision_id)
                        )

                    else:
                        decisions = read_report(store)

                        content = (
                            "<section>"
                            "<h2>Saved human decisions</h2>"
                        )

                        if not decisions:
                            content += (
                                "<p>No human decisions saved yet.</p>"
                            )

                        for decision in decisions:
                            content += (
                                "<article><h3>"
                                '<a href="/decision-report?decision_id='
                                + str(decision["id"])
                                + '">Decision #'
                                + text(decision["id"])
                                + "</a></h3><p>"
                                + text(
                                    decision["payload"].get(
                                        "next_step"
                                    )
                                )
                                + "</p></article>"
                            )

                        html = page(
                            content + "</section>"
                        )

                    self.respond(
                        200,
                        html.encode("utf-8"),
                        "text/html; charset=utf-8",
                    )

                except ValueError as error:
                    self.respond(
                        400,
                        {"error": str(error)},
                    )

                except sqlite3.Error:
                    self.respond(
                        500,
                        {
                            "error": (
                                "Could not read the decision report."
                            )
                        },
                    )

        return Handler

    return make_handler


def main():
    from nexus.farm_app import server, decision_events

    original = server.make_handler
    server.make_handler = report_handler(original)

    print(
        "Decision reports: /decision-report",
        flush=True,
    )

    try:
        decision_events.main()

    finally:
        server.make_handler = original


if __name__ == "__main__":
    main()