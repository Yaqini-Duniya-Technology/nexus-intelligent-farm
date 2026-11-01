import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import parse_qs, urlparse


def text(value):
    if value is None:
        return "Not recorded"
    return escape(str(value))


def local_time(value):
    if not value:
        return "Not recorded"

    try:
        return datetime.fromisoformat(value).astimezone(
            timezone(timedelta(hours=1))
        ).strftime("%d/%m/%Y, %H:%M:%S (Lagos time)")
    except (ValueError, TypeError):
        return str(value)


def read_bundles(store, bundle_id=None):
    with closing(sqlite3.connect(store.path)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")

        exists = db.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'decision_review_bundles'
            """
        ).fetchone()

        if not exists:
            if bundle_id is not None:
                raise ValueError("Review bundle not found")
            return []

        if bundle_id is None:
            return [
                dict(row)
                for row in db.execute(
                    """
                    SELECT id, observation_id, captured_at
                    FROM decision_review_bundles
                    ORDER BY id DESC
                    """
                )
            ]

        row = db.execute(
            """
            SELECT *
            FROM decision_review_bundles
            WHERE id = ?
            """,
            (bundle_id,),
        ).fetchone()

        if not row:
            raise ValueError("Review bundle not found")

        bundle = dict(row)
        bundle["payload"] = json.loads(bundle["payload"])
        return bundle


def record_section(title, records):
    result = "<section><h2>" + text(title) + "</h2>"

    if not records:
        return (
            result
            + "<p>No records captured.</p></section>"
        )

    for record in records:
        result += "<article><dl>"

        for key, value in record.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(
                    value,
                    ensure_ascii=False,
                    indent=2,
                )

            label = key.replace("_", " ").capitalize()

            result += (
                "<dt>"
                + text(label)
                + "</dt><dd>"
                + text(value)
                + "</dd>"
            )

        result += "</dl></article>"

    return result + "</section>"


def page(content):
    return (
        """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS saved review bundles</title>
<style>
* {
    box-sizing: border-box;
}
body {
    margin: 0;
    background: #f1f5ee;
    color: #183c2c;
    font: 16px system-ui;
}
header {
    background: #163f30;
    color: white;
    padding: 28px;
}
main {
    max-width: 1000px;
    margin: auto;
    padding: 24px;
}
section {
    background: white;
    padding: 22px;
    border-radius: 14px;
    margin: 18px 0;
}
article {
    border-top: 1px solid #ccd8ce;
    padding: 14px 0;
}
a {
    color: inherit;
    margin-right: 18px;
}
dt {
    font-weight: 700;
    margin-top: 12px;
}
dd {
    margin: 4px 0;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
}
button {
    font: inherit;
    padding: 10px 16px;
    cursor: pointer;
}
pre {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
}
@media print {
    nav, button, .screen-only {
        display: none;
    }
    body {
        background: white;
    }
    section {
        break-inside: auto;
        border: 1px solid #ccc;
    }
    header {
        color: #183c2c;
    }
}
</style>
</head>
<body>
<header>
<small>LOCAL PILOT · SAVED REVIEW BUNDLES</small>
<h1>NEXUS saved review bundles</h1>
<nav>
<a href="/overview">Farm dashboard</a>
<a href="/decision-review">Current review</a>
<a href="/review-bundles">Saved bundles</a>
<a href="/">Workspace</a>
</nav>
</header>
<main>
<p>
These are saved captures. Later edits to farm records do not
update an earlier bundle. Reports and correction reasons
remain user-entered.
</p>
"""
        + content
        + "</main></body></html>"
    )


def clarification_section(payload):
    result = "<section><h2>Voice clarification answers at capture</h2>"
    if "voice_clarification_history" not in payload:
        return result + "<p>This earlier bundle did not capture voice clarification answers.</p></section>"
    entries = payload["voice_clarification_history"]
    if not isinstance(entries, list):
        return result + "<p>Captured clarification history could not be displayed. Check the saved JSON.</p></section>"
    result += (
        "<p>Newest saved entry first. Earlier answers remain available and may differ. "
        "These are the answers saved in this bundle, not current field records. "
        "Answers and reporter identities are user-entered and not independently verified.</p>"
    )
    if not entries:
        return result + "<p>No clarification answers captured.</p></section>"
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("payload"), dict):
            result += "<article><p>This captured entry could not be displayed. Check the saved JSON.</p></article>"
            continue
        answer_payload = entry["payload"]
        result += "<article><h3>Answer entry #" + text(entry.get("id")) + "</h3><dl>"
        for label, value in [
            ("Recorded", local_time(entry.get("recorded_at"))),
            ("Reporter / role as reported", answer_payload.get("reporter")),
            ("Supporting human review", answer_payload.get("review_id")),
        ]:
            result += "<dt>" + text(label) + "</dt><dd>" + text(value) + "</dd>"
        questions = answer_payload.get("questions")
        answers = answer_payload.get("answers")
        if (isinstance(questions, list) and isinstance(answers, list)
                and len(questions) == len(answers)):
            for question, answer in zip(questions, answers):
                result += "<dt>" + text(question) + "</dt><dd>" + text(answer) + "</dd>"
        else:
            result += "<dd>Captured questions and answers could not be paired. Check the saved JSON.</dd>"
        result += "</dl><details><summary>Captured record references</summary><dl>"
        for label, value in [
            ("Observation ID", entry.get("observation_id")),
            ("Confirmation link ID", entry.get("link_id")),
            ("Answer content SHA-256", entry.get("content_sha256")),
            ("Frozen review SHA-256", answer_payload.get("review_hash")),
        ]:
            result += "<dt>" + text(label) + "</dt><dd>" + text(value) + "</dd>"
        result += "</dl></details></article>"
    return result + "</section>"


def linked_decisions_section(payload):
    result = "<section><h2>Linked human decisions at capture</h2>"
    if "linked_human_decisions" not in payload:
        return result + "<p>This earlier bundle did not capture linked human decisions.</p></section>"
    records = payload["linked_human_decisions"]
    result += "<p>Linked through each decision's supporting bundle and observation. Decision work is separate from workspace task work. Later edits do not update this capture.</p>"
    if not records:
        return result + "<p>No linked human decisions captured.</p></section>"
    for item in records:
        decision = item["decision"]
        result += "<article><h3>Decision #" + text(decision["id"]) + "</h3>"
        result += "<p>Original supporting bundle #" + text(decision["bundle_id"]) + "</p>"
        result += record_section("Saved plan", [decision])
        events = item.get("events")
        if events is None:
            result += "<p>Decision event records were unavailable at capture.</p>"
        else:
            result += record_section("Decision actions — separate from workspace task actions", [e for e in events if e["kind"] == "action"])
            result += record_section("Decision outcome reports — unverified", [e for e in events if e["kind"] == "outcome"])
        result += "</article>"
    return result + "</section>"


def readiness_section(bundle):
    from nexus.farm_app.review_readiness import summarize
    summary = summarize(bundle)
    result = "<section><h2>Review readiness — saved record checks</h2>"
    result += "<p>These checks help a human assess the saved evidence. They do not approve a plan or establish that an answer resolves a question.</p>"
    result += "<h3>Captured records</h3><dl>"
    for key, count in summary["record_counts"].items():
        result += "<dt>" + text(key.replace("_", " ").capitalize()) + "</dt><dd>" + text(count) + "</dd>"
    result += "</dl><h3>Linked decision records — separate counts</h3><dl>"
    for key, count in summary["linked_decision_counts"].items():
        result += "<dt>" + text(key.replace("_", " ").capitalize()) + "</dt><dd>" + text(count) + "</dd>"
    result += "</dl><p>Workspace task actions and decision actions are separate records. These counts do not establish task completion or effectiveness.</p><h3>Details to assess</h3><ul>"
    for finding in summary["record_findings"]:
        result += "<li>" + text(finding) + "</li>"
    result += "</ul><h3>Latest saved clarification answers — human assessment required</h3>"
    if summary["latest_clarification_entry_id"] is not None:
        result += "<p>Answer entry #" + text(summary["latest_clarification_entry_id"]) + "</p>"
    for item in summary["clarification_questions_for_human_assessment"]:
        result += "<article><dl><dt>" + text(item["question"]) + "</dt><dd>" + text(item["saved_answer"]) + "</dd></dl>"
        if item["assessment"] == "explicit_unknown":
            result += "<p>Answer explicitly recorded as Unknown.</p>"
        else:
            result += "<p>A human must assess whether this answer supplies enough information.</p>"
        result += "</article>"
    result += "<h3>Limits of these checks</h3><ul>"
    for limitation in summary["limitations"]:
        result += "<li>" + text(limitation) + "</li>"
    return result + "</ul></section>"


def bundle_page(bundle):
    payload = bundle["payload"]

    content = (
        "<section><h2>Bundle #"
        + text(bundle["id"])
        + "</h2><p>Observation #"
        + text(bundle["observation_id"])
        + "</p><p>Captured: "
        + text(local_time(bundle["captured_at"]))
        + "</p><p>Version: "
        + text(payload.get("bundle_version"))
        + "</p><p>Content SHA-256: "
        + text(bundle["content_sha256"])
        + "</p>"
        '<button onclick="window.print()">'
        "Print / save as PDF</button>"
        '<p class="screen-only">'
        '<a href="/api/review-bundle?bundle_id='
        + str(bundle["id"])
        + '">Open saved JSON</a></p></section>'
    )

    from nexus.farm_app.season_context import render_history
    content += readiness_section(bundle)
    content += render_history(payload)
    from nexus.farm_app.field_inspections import render_history as render_inspections
    content += render_inspections(payload)
    studio = payload.get("evidence_studio")
    if isinstance(studio,dict):
        for label,items in studio.items():
            if isinstance(items,list):content += record_section("Studio capture: "+label.replace("_"," "),items)
        content += "<section><p>Test measurements excluded from farm measurement history: "+text(studio.get("excluded_test_measurements"))+". Explicit link statuses describe the records checked at capture, not current records.</p></section>"
    resource_links=payload.get('resource_case_links')
    if isinstance(resource_links,dict):
        content += "<section><h2>Explicit resource case links at capture</h2><p>"+text(resource_links.get('scope'))+"</p><p>Frozen selected resource versions; current resource records are not substituted.</p></section>"
        content += record_section('Resource case link records — including saved status',resource_links.get('links',[]))
    else:
        content += "<section><h2>Explicit resource case links at capture</h2><p>Not available in this earlier capture. No current records are substituted.</p></section>"
    planned = payload.get("planned_work_orders")
    if planned is None:
        content += "<section><h2>Work orders at capture</h2><p>Not available in this capture.</p></section>"
    else:
        content += record_section("Work orders at capture — separate from workspace task work", planned)

    for title, key in [
        ("Farm", "farm"),
        ("Field", "field"),
        ("Observation", "observation"),
        ("Field context at capture", "latest_field_context"),
        ("Task at capture", "task"),
    ]:
        value = payload.get(key)
        content += record_section(
            title,
            [value] if value else [],
        )

    for title, key in [
        ("Workspace task actions", "task_actions"),
        (
            "Raw follow-up reports — eligibility not assessed here",
            "raw_followups",
        ),
        ("Recorded adviser reviews", "adviser_reviews"),
        (
            "Photo metadata — images not copied into bundle",
            "photo_metadata",
        ),
    ]:
        content += record_section(
            title,
            payload.get(key, []),
        )

    if "record_corrections" in payload:
        content += record_section(
            "Correction history captured",
            payload["record_corrections"],
        )
    else:
        content += (
            "<section><h2>Correction history</h2>"
            "<p>This earlier bundle did not capture "
            "correction history.</p></section>"
        )

    content += linked_decisions_section(payload)
    content += clarification_section(payload)

    weather = payload.get("manually_selected_weather")

    content += record_section(
        "Manually selected weather",
        [weather] if weather else [],
    )

    original = payload.get("original_review_snapshot")

    content += (
        "<section><h2>Original task review snapshot</h2>"
    )

    if original:
        content += (
            "<p>Preserved historical snapshot. Its values "
            "can differ from corrected records above.</p>"
            "<details>"
            "<summary>Show original snapshot</summary><pre>"
            + text(
                json.dumps(
                    original,
                    ensure_ascii=False,
                    indent=2,
                )
            )
            + "</pre></details>"
        )
    else:
        content += "<p>No original snapshot captured.</p>"

    content += (
        "</section><section><h2>Limitations</h2><ul>"
    )

    for limitation in payload.get("limitations", []):
        content += "<li>" + text(limitation) + "</li>"

    unavailable = (
        ", ".join(payload.get("unavailable_tables", []))
        or "None listed"
    )

    content += (
        "</ul><p>Unavailable tables: "
        + text(unavailable)
        + "</p></section>"
    )

    return page(content)


def bundles_handler(base_factory):
    def make_handler(store):
        class Handler(base_factory(store)):
            def do_GET(self):
                parsed = urlparse(self.path)

                if parsed.path not in (
                    "/review-bundles",
                    "/api/review-bundle",
                ):
                    return super().do_GET()

                try:
                    query = parse_qs(
                        parsed.query,
                        keep_blank_values=True,
                    )

                    values = query.get("bundle_id")
                    bundle_id = None

                    if values is not None:
                        if len(values) != 1:
                            raise ValueError(
                                "Provide one bundle ID"
                            )

                        bundle_id = int(values[0])

                        if bundle_id < 1:
                            raise ValueError(
                                "Use a positive bundle ID"
                            )

                    if parsed.path == "/api/review-bundle":
                        if bundle_id is None:
                            raise ValueError(
                                "Provide a bundle ID"
                            )

                        return self.respond(
                            200,
                            read_bundles(store, bundle_id),
                        )

                    if bundle_id is not None:
                        html = bundle_page(
                            read_bundles(store, bundle_id)
                        )
                    else:
                        rows = read_bundles(store)

                        content = (
                            "<section><h2>Saved captures</h2>"
                        )

                        if not rows:
                            content += (
                                "<p>No review bundles "
                                "saved yet.</p>"
                            )

                        for row in rows:
                            content += (
                                "<article><h3>"
                                '<a href="/review-bundles?bundle_id='
                                + str(row["id"])
                                + '">Bundle #'
                                + text(row["id"])
                                + "</a></h3><p>Observation #"
                                + text(row["observation_id"])
                                + " · "
                                + text(
                                    local_time(
                                        row["captured_at"]
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
                                "Could not read saved bundles."
                            )
                        },
                    )

        return Handler

    return make_handler


def main():
    from nexus.farm_app import server, decision_review

    original = server.make_handler
    server.make_handler = bundles_handler(original)

    print(
        "Saved review bundles: /review-bundles",
        flush=True,
    )

    try:
        decision_review.main()
    finally:
        server.make_handler = original


if __name__ == "__main__":
    main()