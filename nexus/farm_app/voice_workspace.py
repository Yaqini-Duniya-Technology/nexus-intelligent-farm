import hashlib
import json
import sqlite3
from urllib.parse import urlparse

from nexus.farm_app import (
    server,
    voice_confirm,
    voice_pipeline,
    voice_response_review,
    voice_review_confirm,
)
from nexus.farm_app.import_voice_response import parse_json


NAVIGATION = """
<nav style="padding:14px;background:#e7efe5;color:#183c2c;
display:flex;flex-wrap:wrap;gap:16px;font:16px system-ui">
<a href="/">Workspace</a>
<a href="/workbench">Operations workbench</a>
<a href="/evidence-studio">Evidence studio</a>
<a href="/field-inspections">Field inspections</a>
<a href="/voice">Voice drafts</a>
<a href="/voice-extraction-review">Extraction review</a>
<a href="/voice-reviewed-confirmation">Reviewed confirmation</a>
<a href="/voice-pipeline">Voice pipeline</a>
</nav>
"""


def local_html(html):
    replacements = {
        "http://127.0.0.1:8080/voice": "/voice",
        "http://127.0.0.1:8080/": "/",
        "http://127.0.0.1:8083/": "/voice-extraction-review",
        "http://127.0.0.1:8084/": "/voice-reviewed-confirmation",
        "http://127.0.0.1:8083": "/voice-extraction-review",
        "http://127.0.0.1:8084": "/voice-reviewed-confirmation",
    }

    for original, replacement in replacements.items():
        html = html.replace(original, replacement)

    # Repair common encoding artifacts in the older review HTML.
    html = html.replace("Â·", "·")
    html = html.replace("â€¦", "...")
    html = html.replace("â€”", "—")

    return html.replace("<main>", NAVIGATION + "<main>", 1)


def review_html():
    html = local_html(voice_response_review.HTML)
    return (
        html.replace(
            "/api/records",
            "/api/voice-extraction-records",
        )
        .replace(
            "/api/reviews",
            "/api/voice-extraction-reviews",
        )
    )


def confirmation_html():
    html = local_html(voice_review_confirm.HTML)
    return (
        html.replace(
            "/api/records",
            "/api/voice-reviewed-records",
        )
        .replace(
            "/api/confirm",
            "/api/voice-reviewed-confirm",
        )
    )


def pipeline_html():
    return local_html(voice_pipeline.HTML).replace(
        "/api/pipeline",
        "/api/voice-pipeline",
    )


def confirmed_voice_context(store):
    """Read the review frozen in each confirmation, not later edits."""
    records = []
    with store.connect() as db:
        if not db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='natlas_voice_observation_links'"
        ).fetchone():
            return {"records": []}
        for row in db.execute(
            "SELECT observation_id, task_id, review_id, confirmed_at, provenance "
            "FROM natlas_voice_observation_links ORDER BY id DESC"
        ):
            try:
                captured = parse_json(row["provenance"])
                review = captured["human_review"]
                canonical = json.dumps(
                    review, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"), allow_nan=False,
                ).encode("utf-8")
                if hashlib.sha256(canonical).hexdigest() != captured["human_review_sha256"]:
                    raise ValueError("Saved review hash mismatch")
                extraction = review["extraction"]
                if not isinstance(extraction, dict):
                    raise ValueError("Invalid saved extraction")
                records.append({
                    "observation_id": row["observation_id"],
                    "task_id": row["task_id"],
                    "review_id": row["review_id"],
                    "confirmed_at": row["confirmed_at"],
                    "extraction": extraction,
                    "reviewer_as_reported": review.get("reviewer_as_reported", ""),
                    "notes": review.get("notes", ""),
                })
            except (ValueError, KeyError, TypeError):
                records.append({
                    "observation_id": row["observation_id"],
                    "task_id": row["task_id"],
                    "error": "Saved voice review could not be checked.",
                })
    return {"records": records}


def make_handler(base, store):
    voice_response_review.initialize(store.path)

    pages = {
        "/voice-extraction-review": review_html(),
        "/voice-reviewed-confirmation": confirmation_html(),
        "/voice-pipeline": pipeline_html(),
    }

    class Handler(base):
        def do_GET(self):
            path = urlparse(self.path).path

            supported = (
                *pages,
                "/api/voice-extraction-records",
                "/api/voice-reviewed-records",
                "/api/voice-pipeline",
                "/api/confirmed-voice-context",
            )

            if path not in supported:
                return super().do_GET()

            try:
                if path in pages:
                    return self.respond(
                        200,
                        pages[path].encode("utf-8"),
                        "text/html; charset=utf-8",
                    )

                if path == "/api/confirmed-voice-context":
                    result = confirmed_voice_context(store)
                elif path == "/api/voice-extraction-records":
                    result = voice_response_review.records(
                        store.path
                    )
                elif path == "/api/voice-reviewed-records":
                    result = voice_review_confirm.page_records(
                        store
                    )
                else:
                    result = voice_pipeline.pipeline(store.path)

                return self.respond(200, result)

            except (ValueError, UnicodeError) as error:
                return self.respond(
                    400,
                    {"error": str(error)},
                )
            except (KeyError, TypeError):
                return self.respond(
                    400,
                    {"error": "Saved voice records could not be checked."},
                )
            except sqlite3.Error:
                return self.respond(
                    500,
                    {"error": "Could not read saved voice records."},
                )

        def do_POST(self):
            path = urlparse(self.path).path

            if path not in (
                "/api/voice-extraction-reviews",
                "/api/voice-reviewed-confirm",
            ):
                return super().do_POST()

            expected_origin = (
                "http://" + self.headers.get("Host", "")
            )

            if self.headers.get("Origin") != expected_origin:
                return self.respond(
                    403,
                    {
                        "error": (
                            "Same-origin browser request required"
                        )
                    },
                )

            try:
                size = int(
                    self.headers.get("Content-Length", "0")
                )

                limit = (
                    65536
                    if path == "/api/voice-extraction-reviews"
                    else 16384
                )

                if not 0 < size <= limit:
                    raise ValueError("Invalid request size")

                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError("Incomplete request")

                data = parse_json(raw.decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("Expected a JSON object")

                if path == "/api/voice-extraction-reviews":
                    result = voice_response_review.save_review(
                        store.path,
                        data,
                    )
                else:
                    result = voice_review_confirm.save_confirmation(
                        store,
                        data,
                    )

                return self.respond(200, result)

            except (ValueError, UnicodeError) as error:
                return self.respond(
                    400,
                    {"error": str(error)},
                )
            except sqlite3.Error:
                return self.respond(
                    500,
                    {
                        "error": (
                            "Database error. Refresh saved reviews "
                            "and confirmation links before retrying."
                        )
                    },
                )

    return Handler


def main():
    original = server.make_handler

    def combined_handler(store):
        return make_handler(original(store), store)

    server.make_handler = combined_handler

    print("Voice drafts: /voice", flush=True)
    print(
        "Extraction review: /voice-extraction-review",
        flush=True,
    )
    print(
        "Reviewed confirmation: /voice-reviewed-confirmation",
        flush=True,
    )
    print("Voice pipeline: /voice-pipeline", flush=True)

    try:
        # Retain the existing voice, decision-cycle and farm routes.
        voice_confirm.main()
    finally:
        server.make_handler = original


if __name__ == "__main__":
    main()