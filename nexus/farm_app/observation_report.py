import argparse
import base64
import html
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def escape(value):
    return html.escape(
        "" if value is None else str(value),
        quote=True,
    )


def paragraph(label, value):
    return (
        f"<p><strong>{escape(label)}:</strong> "
        f"{escape(value)}</p>"
    )


def create_report(database, observation_id, output):
    path = Path(database).resolve(strict=True)

    with closing(
        sqlite3.connect(
            path.as_uri() + "?mode=ro",
            uri=True,
        )
    ) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")

        observation = db.execute(
            """
            SELECT
                o.*,
                f.name AS field_name,
                f.crop,
                farms.name AS farm_name,
                farms.location
            FROM observations o
            JOIN fields f ON f.id = o.field_id
            JOIN farms ON farms.id = f.farm_id
            WHERE o.id = ?
            """,
            (observation_id,),
        ).fetchone()

        if observation is None:
            raise ValueError("Observation not found")

        parts = [
            "<h1>NEXUS observation report</h1>",
            paragraph("Observation ID", observation_id),
            paragraph("Farm", observation["farm_name"]),
            paragraph("Location", observation["location"]),
            paragraph(
                "Field / crop",
                f"{observation['field_name']} / "
                f"{observation['crop']}",
            ),
            paragraph(
                "Observed at",
                observation["observed_at"]
                or observation["created"],
            ),
            paragraph("Recorded at", observation["created"]),
            paragraph(
                "Category / source",
                f"{observation['category']} / "
                f"{observation['source']}",
            ),
            paragraph("Condition", observation["condition"]),
            paragraph("Observation", observation["note"]),
        ]

        if observation["soil_moisture_pct"] is not None:
            parts.append(
                paragraph(
                    "Volumetric soil moisture (%)",
                    observation["soil_moisture_pct"],
                )
            )

        parts.append(
            "<h2>Review task and action records</h2>"
        )

        tasks = db.execute(
            "SELECT * FROM tasks WHERE observation_id = ?",
            (observation_id,),
        ).fetchall()

        if not tasks:
            parts.append("<p>No linked task.</p>")

        for task in tasks:
            parts.extend([
                paragraph(
                    "Task / status",
                    f"#{task['id']} / {task['status']}",
                ),
                paragraph(
                    "Saved recommendation",
                    task["recommendation"],
                ),
                paragraph(
                    "Recorded completion",
                    task["outcome"] or "Not recorded",
                ),
            ])

            actions = db.execute(
                "SELECT * FROM task_actions WHERE task_id = ?",
                (task["id"],),
            ).fetchall()

            for action in actions:
                parts.extend([
                    paragraph("Action type", action["action_type"]),
                    paragraph("Performed at", action["performed_at"]),
                    paragraph(
                        "Action / findings",
                        action["description"],
                    ),
                ])

            if not actions:
                parts.append(
                    "<p>No structured action record.</p>"
                )

            parts.append(
                "<h3>Follow-up reports</h3>"
                "<p>Raw reported records are listed here, including "
                "any historically invalid dates. This report does "
                "not apply the workspace eligibility checks. Use "
                "the workspace evidence summary for eligible "
                "counts.</p>"
            )

            followups = db.execute(
                """
                SELECT *
                FROM followups
                WHERE task_id = ?
                ORDER BY id
                """,
                (task["id"],),
            ).fetchall()

            for followup in followups:
                parts.extend([
                    paragraph(
                        "Report / result",
                        f"#{followup['id']} / {followup['result']}",
                    ),
                    paragraph(
                        "Observed at",
                        followup["observed_at"],
                    ),
                    paragraph(
                        "Recorded at",
                        followup["recorded_at"],
                    ),
                    paragraph(
                        "Reported evidence",
                        followup["evidence"],
                    ),
                ])

            if not followups:
                parts.append("<p>No follow-up reports.</p>")

        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

        parts.append("<h2>Adviser reviews</h2>")

        reviews = (
            db.execute(
                """
                SELECT *
                FROM adviser_reviews
                WHERE observation_id = ?
                ORDER BY id
                """,
                (observation_id,),
            ).fetchall()
            if "adviser_reviews" in tables
            else []
        )

        for review in reviews:
            for label, key in [
                ("Adviser name (as entered)", "adviser_name"),
                ("Reported role", "adviser_role"),
                ("Consultation time", "reviewed_at"),
                ("Findings", "findings"),
                ("Reported assessment", "assessment"),
                ("Evidence / limitations", "basis"),
                ("Agreed next step", "next_step"),
            ]:
                parts.append(paragraph(label, review[key]))

        if not reviews:
            parts.append(
                "<p>No adviser reviews recorded.</p>"
            )

        parts.append("<h2>Attached photos</h2>")

        photos = (
            db.execute(
                """
                SELECT *
                FROM observation_photos
                WHERE observation_id = ?
                ORDER BY id
                """,
                (observation_id,),
            ).fetchall()
            if "observation_photos" in tables
            else []
        )

        for photo in photos:
            source = (
                photo["source_kind"]
                if "source_kind" in photo.keys()
                else "unknown"
            )

            if source == "test_image":
                parts.append(
                    "<p><strong>"
                    "TEST IMAGE — NOT REAL FARM EVIDENCE"
                    "</strong></p>"
                )

            parts.extend([
                paragraph(
                    "Photo source (user declaration)",
                    source,
                ),
                paragraph("Caption", photo["caption"]),
                paragraph("Uploaded at", photo["uploaded_at"]),
            ])

            encoded = base64.b64encode(
                bytes(photo["image_data"])
            ).decode("ascii")

            parts.append(
                f'<img src="data:image/jpeg;base64,{encoded}" '
                f'alt="{escape(photo["caption"])}">'
            )

        if not photos:
            parts.append("<p>No attached photos.</p>")

    generated = datetime.now(timezone.utc)

    parts.append(
        paragraph(
            "Report generated (UTC)",
            generated.isoformat(),
        )
    )

    document = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS Observation Report</title>
<style>
body {
    max-width:850px;
    margin:30px auto;
    padding:20px;
    font:16px system-ui;
    color:#183c2c;
}
p {
    white-space:pre-wrap;
    overflow-wrap:anywhere;
}
h2 {
    border-top:1px solid #aaa;
    padding-top:20px;
}
img {
    display:block;
    max-width:100%;
    max-height:450px;
    margin:16px 0;
}
button {
    padding:12px;
    cursor:pointer;
}
@media print {
    button { display:none; }
    body { margin:0; }
    img { break-inside:avoid; }
}
</style>
</head>
<body>
<button onclick="window.print()">Print / save as PDF</button>
<p>Saved records for human review. Adviser identities and findings
are user-entered. Photos and reported outcomes do not establish
diagnosis, effectiveness or causation. Test images are not farm
evidence.</p>
""" + "".join(parts) + "</body></html>"

    folder = Path(output).resolve()
    folder.mkdir(parents=True, exist_ok=True)

    stamp = generated.strftime("%Y%m%dT%H%M%S_%fZ")
    target = folder / (
        f"observation-{observation_id}-{stamp}.html"
    )

    target.write_text(document, encoding="utf-8")
    return target


def main():
    parser = argparse.ArgumentParser(
        description="Create a printable NEXUS observation report"
    )

    parser.add_argument(
        "--observation-id",
        type=int,
        required=True,
    )
    parser.add_argument(
        "--database",
        default="nexus-farm.sqlite3",
    )
    parser.add_argument(
        "--output",
        default="exports",
    )

    args = parser.parse_args()

    if args.observation_id < 1:
        parser.error("Observation ID must be positive")

    try:
        target = create_report(
            args.database,
            args.observation_id,
            args.output,
        )
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"Report failed: {error}\n")

    print("NEXUS observation report created.")
    print(f"File: {target}")
    print(
        "Open this HTML file in your browser "
        "to print or save as PDF."
    )
    print("The source database was opened read-only.")


if __name__ == "__main__":
    main()