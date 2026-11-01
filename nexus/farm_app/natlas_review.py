import argparse
import html
import json
import sqlite3
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from nexus.farm_app.import_natlas import validate


def escape(value):
    return html.escape(str(value), quote=True)


def read_records(database):
    # Read-only connection prevents this viewer from changing records.
    uri = database.as_uri() + "?mode=ro"

    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row

        exists = db.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'natlas_test_imports'
            """
        ).fetchone()

        if not exists:
            return []

        return [
            dict(row)
            for row in db.execute(
                """
                SELECT id, content_sha256, imported_at, payload
                FROM natlas_test_imports
                ORDER BY id DESC
                """
            )
        ]


def render_page(records, selected_id=None):
    links = "".join(
        f'<li><a href="/?id={row["id"]}">'
        f'Test draft #{row["id"]}</a>'
        f' · Imported {escape(row["imported_at"])}</li>'
        for row in records
    )

    selected = next(
        (
            row for row in records
            if row["id"] == selected_id
        ),
        None,
    )

    if selected_id is None and records:
        selected = records[0]

    content = "<p>No imported test drafts available.</p>"

    if selected_id is not None and selected is None:
        content = "<p>Test draft not found.</p>"

    if selected:
        try:
            data = json.loads(selected["payload"])
            calculated_hash = validate(data)

            if calculated_hash != selected["content_sha256"]:
                raise ValueError("Stored record hash does not match")

        except (ValueError, TypeError, KeyError):
            content = (
                "<p class='notice'>This record failed validation. "
                "Its reviewed extraction is not displayed.</p>"
            )
        else:
            reviewed = json.dumps(
                data["reviewed_extraction"],
                ensure_ascii=False,
                indent=2,
            )

            corrections = "".join(
                "<li>"
                f"<strong>{escape(item['field'])}</strong>: "
                f"{escape(item['reason'])}"
                "</li>"
                for item in data["corrections"]
            )

            limitations = "".join(
                f"<li>{escape(item)}</li>"
                for item in data.get("limitations", [])
            )

            error = data.get("original_validation_error")
            error_text = (
                escape(error)
                if error
                else "No original structure error recorded."
            )

            content = f"""
            <section>
              <h2>Imported test draft #{selected["id"]}</h2>
              <p class="notice">
                Synthetic test material — not evidence from a farm.
                The reviewed version includes human-selected content.
              </p>
              <p><strong>Model:</strong>
                {escape(data["model"])}</p>
              <p><strong>Revision:</strong>
                {escape(data["model_revision"])}</p>
              <p><strong>Reviewer as reported:</strong>
                {escape(data["reviewer_as_reported"])}</p>
              <p><strong>Reviewed:</strong>
                {escape(data["reviewed_at"])}</p>
              <p><strong>Imported:</strong>
                {escape(selected["imported_at"])}</p>
              <p><strong>Content hash check:</strong> Passed</p>
              <p class="muted">
                Hash checks detect content differences; they do not
                authenticate the model run or reviewer.
              </p>
            </section>

            <section>
              <h2>Source Hausa transcript</h2>
              <p class="preserve">{escape(data["source_transcript"])}</p>
            </section>

            <div class="grid">
              <section>
                <h2>Original model output</h2>
                <pre>{escape(data["original_model_output"])}</pre>
                <p><strong>Original structure check:</strong>
                  {error_text}</p>
              </section>
              <section>
                <h2>Human-reviewed extraction</h2>
                <pre>{escape(reviewed)}</pre>
                <p class="muted">
                  This is the reviewed version, not the original
                  model response.
                </p>
              </section>
            </div>

            <section>
              <h2>Recorded review notes</h2>
              <ul>{corrections}</ul>
            </section>

            <section>
              <h2>Limitations</h2>
              <ul>{limitations}</ul>
              <p>No farm observation or task is created by this viewer.</p>
            </section>

            <footer>{escape(data.get("attribution", ""))}</footer>
            """

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS N-ATLaS test review</title>
<style>
* {{ box-sizing:border-box; }}
body {{
  margin:0; background:#f1f5ee; color:#183c2c;
  font:16px system-ui,sans-serif;
}}
header {{ background:#163f30; color:white; padding:28px; }}
main {{ max-width:1200px; margin:auto; padding:24px; }}
section {{ background:white; border-radius:14px; padding:22px;
  margin-bottom:20px; }}
.grid {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
pre {{ white-space:pre-wrap; overflow-wrap:anywhere;
  background:#f4f6f3; padding:16px; border-radius:8px; }}
p,li {{ overflow-wrap:anywhere; line-height:1.6; }}
.preserve {{ white-space:pre-wrap; }}
.notice {{ background:#fff1c6; padding:14px; border-radius:8px; }}
.muted {{ color:#58695d; }}
a {{ color:inherit; }}
footer {{ padding:16px 0; }}
@media(max-width:800px) {{ .grid {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<header>
  <small>LOCAL PILOT · N-ATLaS TEST REVIEW</small>
  <h1>NEXUS Voice extraction review</h1>
  <p>Compare model output with recorded human corrections.</p>
</header>
<main>
  <section>
    <h2>Imported test drafts</h2>
    <p>This separate local viewer reads saved imports.
       It does not load an AI model.</p>
    <p><a href="/">Refresh saved drafts</a></p>
    <ul>{links}</ul>
  </section>
  {content}
</main>
</body>
</html>"""


def make_handler(database):
    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, body):
            raw = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            parsed = urlparse(self.path)

            if parsed.path != "/":
                self.respond(404, "Not found")
                return

            try:
                query = parse_qs(parsed.query, keep_blank_values=True)
                selected_id = None

                if "id" in query:
                    values = query["id"]
                    if len(values) != 1:
                        raise ValueError("Provide one draft ID")

                    selected_id = int(values[0])
                    if selected_id < 1:
                        raise ValueError("Invalid draft ID")

                records = read_records(database)
                self.respond(200, render_page(records, selected_id))

            except ValueError:
                self.respond(400, "Invalid draft ID")
            except (sqlite3.Error, OSError):
                self.respond(500, "Could not read the local database")

    return Handler


def main():
    parser = argparse.ArgumentParser(
        description="Read-only N-ATLaS imported test review"
    )
    parser.add_argument("--database", default="nexus-farm.sqlite3")
    parser.add_argument("--port", type=int, default=8082)
    args = parser.parse_args()

    database = Path(args.database).resolve()
    if not database.is_file():
        parser.error("Select an existing NEXUS database")

    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        make_handler(database),
    )

    print(
        f"NEXUS N-ATLaS review: http://127.0.0.1:{args.port}",
        flush=True,
    )
    print("Read-only viewer. Press Ctrl+C to stop.", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()