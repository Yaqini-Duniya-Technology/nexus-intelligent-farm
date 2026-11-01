import sqlite3
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

from nexus.farm_app.decision_report import page, read_report
from nexus.farm_app.review_bundles import local_time, text


LAGOS = timezone(timedelta(hours=1))


def review_timing(value, today):
    if not isinstance(value, str) or not value:
        return "Review date unavailable", 3, None

    try:
        planned = date.fromisoformat(value)
    except ValueError:
        return "Review date unavailable", 3, None

    if planned.isoformat() != value:
        return "Review date unavailable", 3, None

    if planned < today:
        days = (today - planned).days

        return (
            f"Planned review date overdue by {days} "
            + ("day" if days == 1 else "days"),
            0,
            planned,
        )

    if planned == today:
        return "Planned review date is today", 1, planned

    return "Planned review date is upcoming", 2, planned


def render_queue(decisions, checked_at=None):
    checked_at = checked_at or datetime.now(timezone.utc)
    today = checked_at.astimezone(LAGOS).date()

    items = []
    counts = [0, 0, 0, 0]

    for decision in decisions:
        timing, rank, planned = review_timing(
            decision["payload"].get("review_date"),
            today,
        )

        counts[rank] += 1

        items.append(
            (
                rank,
                planned or date.max,
                decision["id"],
                timing,
                decision,
            )
        )

    items.sort(key=lambda item: item[:3])

    content = (
        "<section><h2>Decision review queue</h2>"
        "<p>Checked: "
        + text(local_time(checked_at.isoformat()))
        + "</p><p>"
        + text(counts[0])
        + " overdue dates · "
        + text(counts[1])
        + " due today · "
        + text(counts[2])
        + " upcoming · "
        + text(counts[3])
        + " dates unavailable</p>"
        '<p class="screen-only">'
        '<a href="/decision-reviews">'
        "Refresh review dates</a></p>"
        "<p>Labels compare the saved planned date with "
        "today's Lagos date. This queue does not track "
        "whether the review happened. Recording an action "
        "or outcome does not clear a date from this queue.</p>"
        "<p>Each saved decision is listed separately, "
        "including earlier plans. A later decision does "
        "not automatically replace an earlier one. "
        "No background alerts or SMS are sent.</p>"
        "</section>"
    )

    if not items:
        content += (
            "<section>"
            "<p>No human decisions recorded yet.</p>"
            '<a href="/human-decisions">'
            "Record a human decision</a>"
            "</section>"
        )

    for rank, planned, decision_id, timing, decision in items:
        payload = decision["payload"]

        content += (
            "<section><h2>Decision #"
            + text(decision_id)
            + "</h2><p><strong>"
            + text(timing)
            + "</strong></p><p>Planned review: "
            + text(payload.get("review_date"))
            + "</p><p>Recorded: "
            + text(local_time(decision["recorded_at"]))
            + "</p><h3>Chosen next step</h3><p>"
            + text(payload.get("next_step"))
            + "</p><p>Decision maker as reported: "
            + text(payload.get("decision_maker"))
            + "</p>"
            '<p><a href="/decision-report?decision_id='
            + str(decision_id)
            + '">Read decision report</a>'
            '<a href="/review-bundles?bundle_id='
            + str(decision["bundle_id"])
            + '">Read supporting bundle</a>'
            '<a href="/decision-events">'
            "Record actual work / outcome</a></p>"
            "</section>"
        )

    return (
        page(content)
        .replace(
            "<nav>",
            '<nav><a href="/decision-reviews">'
            "Review queue</a>",
        )
        .replace(
            "This report combines a saved human plan, "
            "its supporting bundle and\n"
            "current linked action/outcome records. "
            "Refresh before printing.\n"
            "It is not a frozen capture of the complete "
            "decision cycle.",
            "Review dates are calculated when this page "
            "loads. Refresh to update them.",
        )
        .replace(
            "<title>NEXUS decision report</title>",
            "<title>NEXUS decision review queue</title>",
        )
        .replace(
            "<h1>NEXUS decision report</h1>",
            "<h1>NEXUS decision review queue</h1>",
        )
        .replace(
            "LOCAL PILOT · DECISION REPORT",
            "LOCAL PILOT · DECISION REVIEW DATES",
        )
    )


def queue_handler(base_factory):
    def make_handler(store):
        class Handler(base_factory(store)):
            def do_GET(self):
                if urlparse(self.path).path != "/decision-reviews":
                    return super().do_GET()

                try:
                    html = render_queue(
                        read_report(store)
                    )

                    self.respond(
                        200,
                        html.encode("utf-8"),
                        "text/html; charset=utf-8",
                    )

                except ValueError:
                    self.respond(
                        500,
                        {
                            "error": (
                                "Could not read saved decision dates."
                            )
                        },
                    )

                except sqlite3.Error:
                    self.respond(
                        500,
                        {
                            "error": (
                                "Could not read decision records."
                            )
                        },
                    )

        return Handler

    return make_handler


def main():
    from nexus.farm_app import server, decision_report

    original = server.make_handler
    server.make_handler = queue_handler(original)

    print(
        "Decision review queue: /decision-reviews",
        flush=True,
    )

    try:
        decision_report.main()
    finally:
        server.make_handler = original


if __name__ == "__main__":
    main()