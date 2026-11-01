import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from nexus.farm_app.capture_decision_cycle import canonical
from nexus.farm_app.review_bundles import local_time, text


def read_cycles(store, snapshot_id=None):
    uri = Path(store.path).resolve().as_uri() + "?mode=ro"

    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row

        exists = db.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'decision_cycle_snapshots'
            """
        ).fetchone()

        if not exists:
            if snapshot_id is not None:
                raise ValueError(
                    "Decision-cycle snapshot not found"
                )
            return []

        if snapshot_id is None:
            return [
                dict(row)
                for row in db.execute(
                    """
                    SELECT
                        id,
                        decision_id,
                        captured_at,
                        content_sha256
                    FROM decision_cycle_snapshots
                    ORDER BY id DESC
                    """
                )
            ]

        row = db.execute(
            """
            SELECT *
            FROM decision_cycle_snapshots
            WHERE id = ?
            """,
            (snapshot_id,),
        ).fetchone()

        if row is None:
            raise ValueError(
                "Decision-cycle snapshot not found"
            )

        saved = dict(row)

    saved["payload"] = json.loads(saved["payload"])

    digest = hashlib.sha256(
        canonical(saved["payload"]).encode("utf-8")
    ).hexdigest()

    saved["hash_matches"] = (
        digest == saved["content_sha256"]
    )

    return saved


def page(content):
    return (
        """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS saved decision cycles</title>
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
main{
    max-width:1000px;
    margin:auto;
    padding:24px;
}
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
a{color:inherit;margin-right:16px}
dt{font-weight:bold;margin-top:12px}
dd{
    margin:4px 0;
    white-space:pre-wrap;
    overflow-wrap:anywhere;
}
p,li{
    overflow-wrap:anywhere;
}
pre{
    white-space:pre-wrap;
    overflow-wrap:anywhere;
}
button{
    font:inherit;
    padding:12px;
    cursor:pointer;
}
@media print{
    nav,button,.screen-only{display:none}
    body{background:white}
    header{color:#183c2c}
}
</style>
</head>
<body>
<header>
<small>LOCAL PILOT · SAVED DECISION CYCLES</small>
<h1>NEXUS saved decision cycles</h1>
<nav>
<a href="/decision-cycles">Saved cycles</a>
<a href="/decision-report">Live decision reports</a>
<a href="/decision-reviews">Decision reviews</a>
<a href="/overview">Dashboard</a>
</nav>
</header>
<main>
<p>Saved captures retain the records available when captured.
Later entries do not update an earlier capture.
Review dates below describe the saved tracking state;
no current overdue status is calculated.</p>
"""
        + content
        + "</main></body></html>"
    )


def records(title, items):
    content = (
        "<section><h2>"
        + text(title)
        + "</h2>"
    )

    if not items:
        content += "<p>No records captured.</p>"

    for item in items:
        content += "<article><dl>"

        for key, value in item.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(
                    value,
                    indent=2,
                    ensure_ascii=False,
                )

            content += (
                "<dt>"
                + text(
                    key.replace("_", " ").capitalize()
                )
                + "</dt><dd>"
                + text(value)
                + "</dd>"
            )

        content += "</dl></article>"

    return content + "</section>"


def render_check_findings(findings):
    if not findings:
        return "<p>No findings from these checks. This does not verify the evidence.</p>"
    content = "<ul class=check-findings>"
    for finding in findings:
        content += (
            "<li><strong>" + text(finding["code"].replace("_", " "))
            + "</strong><p>" + text(finding["message"])
            + "</p><p>Record reference: <code>" + text(finding["reference"])
            + "</code></p></li>"
        )
    return content + "</ul>"


def render_check_summary(summary):
    """Render derived checks without changing the frozen snapshot."""
    content = (
        "<section><h2>Evidence record checks</h2>"
        "<p>Generated from this saved snapshot using rule version "
        + text(summary["summary_version"])
        + ". These checks are calculated when this page opens; they are not "
        "part of the frozen snapshot or its content hash. Later rule changes "
        "can produce different checks.</p>"
    )
    counts = summary["counts"]
    content += "<p>" + text(
        f"{counts['actions']} actions / {counts['outcome_reports']} outcome reports / "
        f"{counts['reviews']} reviews"
    ) + "</p>"
    content += "<p><strong>Snapshot content hash: </strong>" + text(
        "Matches" if summary["content_hash_matches"] else "MISMATCH"
    ) + "</p>"
    if summary.get("review_evidence_capture_status") == "not_recorded_in_older_snapshot":
        content += (
            "<p>This older snapshot did not capture additional reviewed evidence "
            "bundle contents. Current records are not substituted.</p>"
        )
    grouped = set()
    checks = summary.get("bundle_checks")
    if checks is not None:
        content += (
            "<h3>Checks by captured bundle</h3>"
            "<p>Each bundle is checked separately. Repeated records across "
            "bundles are not independent evidence. Clarification counts do not "
            "establish that questions are resolved.</p>"
        )
        for check in checks:
            role = check.get("role", "captured")
            title = f"{role.capitalize()} bundle #{check.get('bundle_id', 'unknown')}"
            content += "<article class=bundle-check><h4>" + text(title) + "</h4><dl>"
            captured = check.get("captured_at")
            values = [
                ("Observation ID", check.get("observation_id")),
                ("Bundle captured (Lagos time)", local_time(captured) if captured else "Not recorded"),
                ("Bundle content hash", "Matches" if check.get("content_hash_matches") else "MISMATCH"),
                ("Referencing review IDs", ", ".join(str(v) for v in check.get("referencing_review_ids", [])) or "None captured"),
            ]
            for label, value in values:
                content += "<dt>" + text(label) + "</dt><dd>" + text(value) + "</dd>"
            content += "</dl><h5>Captured record counts</h5><dl>"
            for key, value in check.get("counts", {}).items():
                content += "<dt>" + text(key.replace("_", " ").capitalize()) + "</dt><dd>" + text(value) + "</dd>"
            content += "</dl>"
            items = check.get("findings", [])
            grouped.update((f["code"], f["reference"], f["message"]) for f in items)
            content += render_check_findings(items) + "</article>"
    remaining = [f for f in summary["findings"]
                 if (f["code"], f["reference"], f["message"]) not in grouped]
    content += "<h3>Cycle and record-link checks</h3>" + render_check_findings(remaining)
    content += "<h3>Questions for human review</h3><ul>"
    for question in summary["human_review_questions"]:
        content += "<li>" + text(question) + "</li>"
    content += "</ul><h3>Check limitations</h3><ul>"
    for limitation in summary["limitations"]:
        content += "<li>" + text(limitation) + "</li>"
    return content + "</ul></section>"


def render_evidence_summary(saved):
    # Import here to avoid a circular module import.
    from nexus.farm_app.evidence_quality import summarize
    return render_check_summary(summarize(saved))


def render_frozen_review_evidence(payload):
    title = "Reviewed evidence bundles at cycle capture"
    if "review_evidence_bundles" not in payload:
        return ("<section><h2>" + title + "</h2><p>This older snapshot did not "
                "capture additional reviewed bundle contents. No current records "
                "are substituted.</p></section>")
    entries = payload["review_evidence_bundles"]
    if not entries:
        return "<section><h2>" + title + "</h2><p>No additional evidence bundles were referenced by captured reviews.</p></section>"
    content = ("<section><h2>" + title + "</h2><p>Frozen contents from this "
               "snapshot. These do not replace the decision's original supporting "
               "bundle. Hashes do not verify reported findings.</p></section>")
    for entry in entries:
        bundle = entry["bundle"]
        content += records("Reviewed bundle #" + str(bundle["id"]), [
            {"referencing_review_ids": entry["review_ids"], **bundle}
        ])
    return content


def render_cycle(saved):
    payload = saved["payload"]
    sid = saved["id"]

    status = (
        "Matches stored content hash"
        if saved["hash_matches"]
        else (
            "MISMATCH — captured content failed "
            "its hash check"
        )
    )

    content = records(
        f"Snapshot #{sid}",
        [{
            "decision_id": saved["decision_id"],
            "captured_at_lagos": local_time(
                saved["captured_at"]
            ),
            "snapshot_version": payload.get(
                "snapshot_version"
            ),
            "content_sha256": saved["content_sha256"],
            "content_check": status,
        }],
    )

    content += (
        '<section>'
        '<button onclick="window.print()">'
        'Print / save as PDF</button>'
        f'<p><a href="/api/decision-cycle?snapshot_id={sid}">'
        'Open saved JSON</a></p>'
        '<p>The content check compares the payload with '
        'its stored hash. It does not authenticate the '
        'author or verify the reported evidence.</p>'
        '</section>'
    )

    content += render_evidence_summary(saved)

    decision = payload.get("decision") or {}

    content += records(
        "Human decision at capture",
        [decision],
    )

    content += records(
        "Review tracking at capture",
        [payload.get("review_tracking") or {}],
    )

    events = payload.get("events") or []

    content += records(
        "Recorded actions at capture",
        [
            event
            for event in events
            if event.get("kind") == "action"
        ],
    )

    content += records(
        (
            "Reported outcomes at capture "
            "— not independently verified"
        ),
        [
            event
            for event in events
            if event.get("kind") == "outcome"
        ],
    )

    content += records(
        "Review history at capture",
        payload.get("reviews") or [],
    )

    content += render_frozen_review_evidence(payload)

    bundle = payload.get("supporting_bundle") or {}

    content += records(
        "Supporting bundle captured with this cycle",
        [bundle],
    )

    content += (
        "<section><h2>Limitations</h2><ul>"
    )

    for limitation in payload.get("limitations") or []:
        content += (
            "<li>"
            + text(limitation)
            + "</li>"
        )

    return page(
        content + "</ul></section>"
    )


def cycles_handler(base_factory):
    def make_handler(store):
        class Handler(base_factory(store)):
            def do_GET(self):
                parsed = urlparse(self.path)

                if parsed.path not in (
                    "/decision-cycles",
                    "/api/decision-cycle",
                ):
                    return super().do_GET()

                try:
                    query = parse_qs(
                        parsed.query,
                        keep_blank_values=True,
                    )

                    values = query.get("snapshot_id")
                    snapshot_id = None

                    if values is not None:
                        if len(values) != 1:
                            raise ValueError(
                                "Provide one snapshot ID"
                            )

                        snapshot_id = int(values[0])

                        if snapshot_id < 1:
                            raise ValueError(
                                "Use a positive snapshot ID"
                            )

                    if parsed.path == "/api/decision-cycle":
                        if snapshot_id is None:
                            raise ValueError(
                                "Provide a snapshot ID"
                            )

                        return self.respond(
                            200,
                            read_cycles(
                                store,
                                snapshot_id,
                            ),
                        )

                    if snapshot_id is not None:
                        html = render_cycle(
                            read_cycles(
                                store,
                                snapshot_id,
                            )
                        )

                    else:
                        content = (
                            "<section>"
                            "<h2>Saved snapshots</h2>"
                        )

                        rows = read_cycles(store)

                        if not rows:
                            content += (
                                "<p>No decision-cycle "
                                "snapshots saved yet.</p>"
                            )

                        for row in rows:
                            content += (
                                "<article><h3>"
                                '<a href="/decision-cycles?snapshot_id='
                                + str(row["id"])
                                + '">Snapshot #'
                                + text(row["id"])
                                + "</a></h3><p>Decision #"
                                + text(row["decision_id"])
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
                                "Could not read saved "
                                "decision cycles."
                            )
                        },
                    )

        return Handler

    return make_handler


def main():
    from nexus.farm_app import (
        server,
        decision_review_completion,
    )

    original = server.make_handler
    server.make_handler = cycles_handler(original)

    print(
        "Saved decision cycles: /decision-cycles",
        flush=True,
    )

    try:
        decision_review_completion.main()

    finally:
        server.make_handler = original


if __name__ == "__main__":
    main()