import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import urlparse

from nexus.farm_app.atomic import create_observation_atomic


def initialize(store):
    with store.connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS voice_observation_links (
                id INTEGER PRIMARY KEY,
                draft_id INTEGER NOT NULL UNIQUE
                    REFERENCES voice_drafts(id),
                observation_id INTEGER NOT NULL UNIQUE
                    REFERENCES observations(id),
                task_id INTEGER NOT NULL UNIQUE
                    REFERENCES tasks(id),
                confirmed_at TEXT NOT NULL,
                request_sha256 TEXT NOT NULL,
                provenance TEXT NOT NULL
            )
        """)


class BorrowedConnection:
    """Keep the existing atomic function inside our transaction."""

    def __init__(self, db):
        self.db = db

    def execute(self, sql, *args):
        if sql.strip().upper() == "BEGIN IMMEDIATE":
            if not self.db.in_transaction:
                raise RuntimeError("Outer transaction is missing")

            return self.db.execute("SELECT 1")

        return self.db.execute(sql, *args)


class BorrowedStore:
    def __init__(self, store, db):
        self.store = store
        self.db = db

    def __getattr__(self, name):
        return getattr(self.store, name)

    @contextmanager
    def connect(self):
        # The outer connection owns commit, rollback and closure.
        yield BorrowedConnection(self.db)


def confirm(store, data):
    for key in ("draft_id", "version", "field_id"):
        value = data.get(key)

        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
        ):
            raise ValueError(f"Invalid {key}")

    if data.get("confirmed") is not True:
        raise ValueError(
            "Confirm the corrected text describes "
            "an actual farm observation"
        )

    category = data.get("category")
    condition = data.get("condition")

    if category not in (
        "general",
        "crop_health",
        "water",
        "pest",
        "operations",
    ):
        raise ValueError("Choose a valid category")

    if condition not in ("unknown", "stable", "worsening"):
        raise ValueError("Choose a valid field condition")

    observed_at = data.get("observed_at") or None

    if (
        observed_at is not None
        and not isinstance(observed_at, str)
    ):
        raise ValueError("Invalid observation time")

    request = {
        key: data[key]
        for key in ("draft_id", "version", "field_id")
    }

    request.update(
        category=category,
        condition=condition,
        observed_at=observed_at,
    )

    digest = hashlib.sha256(
        json.dumps(request, sort_keys=True).encode()
    ).hexdigest()

    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")

        draft = db.execute(
            "SELECT * FROM voice_drafts WHERE id=?",
            (data["draft_id"],),
        ).fetchone()

        if not draft:
            raise ValueError("Voice draft not found")

        if draft["source"] != "farmer":
            raise ValueError(
                "Test recordings cannot create farm observations"
            )

        existing = db.execute(
            """
            SELECT *
            FROM voice_observation_links
            WHERE draft_id=?
            """,
            (draft["id"],),
        ).fetchone()

        if existing:
            if existing["request_sha256"] != digest:
                raise ValueError(
                    "This draft already created an observation. "
                    "Read the saved link before making another record."
                )

            return {
                "observation_id": existing["observation_id"],
                "task_id": existing["task_id"],
                "reused": True,
            }

        if draft["version"] != data["version"]:
            raise ValueError(
                "Draft changed. Refresh and review its latest text."
            )

        provenance = {
            "version": "confirmed-voice-observation-v1",
            "draft_id": draft["id"],
            "draft_version": draft["version"],
            "source": draft["source"],
            "audio_sha256": draft["audio_sha256"],
            "original_transcript": draft["original_transcript"],
            "corrected_transcript": draft["corrected_transcript"],
            "model": draft["model"],
            "revision": draft["revision"],
            "metrics": json.loads(draft["metrics"]),
            "draft_recorded_at": draft["recorded_at"],
            "verification": "farmer_reported",
        }

        result = create_observation_atomic(
            BorrowedStore(store, db),
            {
                "field_id": data["field_id"],
                "note": draft["corrected_transcript"],
                "source": "farmer",
                "category": category,
                "condition": condition,
                "observed_at": observed_at,
            },
        )

        db.execute("""
            INSERT INTO voice_observation_links (
                draft_id,
                observation_id,
                task_id,
                confirmed_at,
                request_sha256,
                provenance
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            draft["id"],
            result["observation_id"],
            result["task_id"],
            datetime.now(timezone.utc).isoformat(),
            digest,
            json.dumps(provenance, ensure_ascii=False),
        ))

        return {
            **result,
            "reused": False,
        }


def make_handler(base, store):
    initialize(store)

    class Handler(base):
        def do_GET(self):
            path = urlparse(self.path).path

            if path == "/voice-confirm":
                return self.respond(
                    200,
                    HTML.encode("utf-8"),
                    "text/html; charset=utf-8",
                )

            if path == "/api/voice-links":
                with store.connect() as db:
                    rows = [
                        dict(row)
                        for row in db.execute(
                            """
                            SELECT *
                            FROM voice_observation_links
                            ORDER BY id DESC
                            """
                        )
                    ]

                return self.respond(200, rows)

            return super().do_GET()

        def do_POST(self):
            if urlparse(self.path).path != "/api/voice-confirm":
                return super().do_POST()

            origin = self.headers.get("Origin")
            expected_origin = (
                "http://" + self.headers.get("Host", "")
            )

            if origin and origin != expected_origin:
                return self.respond(
                    403,
                    {"error": "Cross-origin request rejected"},
                )

            try:
                size = int(
                    self.headers.get("Content-Length", "0")
                )

                if not 0 < size <= 16384:
                    raise ValueError("Invalid request size")

                data = json.loads(
                    self.rfile.read(size).decode("utf-8")
                )

                if not isinstance(data, dict):
                    raise ValueError("Expected a JSON object")

                result = confirm(store, data)

            except (ValueError, UnicodeDecodeError) as error:
                return self.respond(
                    400,
                    {"error": str(error)},
                )

            except sqlite3.Error:
                return self.respond(
                    500,
                    {
                        "error": (
                            "Save could not be confirmed. "
                            "Refresh saved links before retrying."
                        )
                    },
                )

            self.respond(200, result)

    return Handler


HTML = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS confirm voice observation</title>

<style>
body {
    margin: 0;
    background: #f1f5ee;
    color: #183c2c;
    font: 17px system-ui;
}

main {
    max-width: 850px;
    margin: auto;
    padding: 24px;
}

section {
    background: white;
    padding: 22px;
    margin: 18px 0;
    border-radius: 14px;
}

label {
    display: block;
    margin: 16px 0 8px;
}

select, input, button {
    font: inherit;
    padding: 12px;
    width: 100%;
    box-sizing: border-box;
}

input[type=checkbox] { width: auto; }

button {
    margin-top: 18px;
    background: #1d5c40;
    color: white;
}

pre {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
}

a { color: inherit; }

#message {
    background: #fff1c6;
    padding: 14px;
}
</style>
</head>

<body>
<main>
<small>LOCAL PILOT · CONFIRMED VOICE OBSERVATIONS</small>
<h1>NEXUS Voice confirmation</h1>

<nav>
    <a href="/voice">Saved voice drafts</a> ·
    <a href="/">Workspace</a>
</nav>

<p>
    Review a saved actual farmer transcript before creating
    an observation and human-review task.
    Test recordings cannot be converted.
    This does not verify a cause or generate a diagnosis.
</p>

<p id="message" role="status" aria-live="polite">Loading…</p>

<button id="refresh" type="button">
    Refresh drafts and links
</button>

<section>
<form id="form">
    <label for="draft">Saved voice draft</label>
    <select id="draft" required></select>

    <p id="details"></p>

    <h3>Corrected text to save</h3>
    <pre id="text"></pre>

    <label for="field">Field</label>
    <select id="field" required></select>

    <label for="category">Category</label>
    <select id="category">
        <option value="general">General</option>
        <option value="crop_health">Crop health</option>
        <option value="water">Water</option>
        <option value="pest">Pest observation</option>
        <option value="operations">Operations</option>
    </select>

    <label for="condition">Field condition</label>
    <select id="condition">
        <option value="unknown">Unknown</option>
        <option value="stable">Stable</option>
        <option value="worsening">Worsening</option>
    </select>

    <label for="time">
        Observed at (local time; blank means submission time)
    </label>
    <input id="time" type="datetime-local">

    <label>
        <input id="confirmed" type="checkbox" required>
        I reviewed the corrected transcript and confirm it
        describes an actual observation for the selected field.
    </label>

    <button id="save">Confirm &amp; create observation</button>
</form>
</section>

<section>
    <h2>Saved voice observation links</h2>
    <div id="links"></div>
</section>

<p>
    Both transcripts and model provenance are captured with the
    save. Later draft edits do not rewrite that capture.
    Original audio is not stored.
    Recommendations remain human-review prompts.
</p>
</main>

<script>
const $ = id => document.getElementById(id);

let drafts = [];
let links = [];
let selected = null;

function show() {
    selected = drafts.find(
        draft => String(draft.id) === $("draft").value
    ) || null;

    $("confirmed").checked = false;

    $("text").textContent = selected
        ? selected.corrected_transcript
        : "";

    const linked = selected && links.find(
        link => link.draft_id === selected.id
    );

    $("details").textContent = selected
        ? `Source: ${selected.source} · ` +
          `Version ${selected.version}` +
          (linked
            ? ` · Already saved as observation #${linked.observation_id}`
            : "")
        : "";

    $("save").disabled =
        !selected ||
        selected.source !== "farmer" ||
        Boolean(linked);
}

async function get(path) {
    const response = await fetch(path);
    const data = await response.json();

    if (!response.ok) {
        throw Error(data.error || "Load failed");
    }

    return data;
}

async function load() {
    const previous = $("draft").value;

    const [draftRecords, state, linkRecords] = await Promise.all([
        get("/api/voice-drafts"),
        get("/api/state"),
        get("/api/voice-links")
    ]);

    drafts = draftRecords;
    links = linkRecords;

    $("draft").replaceChildren(
        new Option("Select a draft…", "")
    );

    drafts.forEach(draft => {
        $("draft").add(new Option(
            `#${draft.id} · ${draft.source}`,
            draft.id
        ));
    });

    $("draft").value = previous;

    const field = $("field").value;

    $("field").replaceChildren(
        new Option("Select a field…", "")
    );

    state.fields.forEach(item => {
        $("field").add(new Option(
            `${item.name} · ${item.crop}`,
            item.id
        ));
    });

    $("field").value = field;

    $("links").replaceChildren();

    links.forEach(link => {
        const paragraph = document.createElement("p");

        paragraph.textContent =
            `Draft #${link.draft_id} → ` +
            `Observation #${link.observation_id} · ` +
            `Task #${link.task_id} · ` +
            new Date(link.confirmed_at).toLocaleString();

        $("links").append(paragraph);
    });

    if (!links.length) {
        $("links").textContent =
            "No confirmed voice observations yet.";
    }

    show();
}

$("draft").onchange = show;

$("refresh").onclick = () => {
    load()
        .then(() => {
            $("message").textContent = "Records refreshed.";
        })
        .catch(error => {
            $("message").textContent = error.message;
        });
};

$("form").onsubmit = async event => {
    event.preventDefault();

    if (!selected) return;

    $("save").disabled = true;

    try {
        const observed = $("time").value;

        const data = {
            draft_id: selected.id,
            version: selected.version,
            field_id: Number($("field").value),
            category: $("category").value,
            condition: $("condition").value,
            observed_at: observed
                ? new Date(observed).toISOString()
                : null,
            confirmed: $("confirmed").checked
        };

        const response = await fetch("/api/voice-confirm", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(data)
        });

        const result = await response.json();

        if (!response.ok) {
            throw Error(result.error || "Save failed");
        }

        await load();

        $("message").textContent =
            `Saved observation #${result.observation_id} ` +
            `and task #${result.task_id}.`;

    } catch (error) {
        $("message").textContent = error.message;

        $("save").disabled =
            !selected || selected.source !== "farmer";
    }
};

load()
    .then(() => {
        $("message").textContent =
            "Voice confirmation ready. " +
            "Test drafts remain test records.";
    })
    .catch(error => {
        $("message").textContent = error.message;
    });
</script>
</body>
</html>
"""


def main():
    from nexus.farm_app import server, voice_drafts

    previous = server.make_handler

    server.make_handler = (
        lambda store: make_handler(previous(store), store)
    )

    voice_drafts.main()


if __name__ == "__main__":
    main()