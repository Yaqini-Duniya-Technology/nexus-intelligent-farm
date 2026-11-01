import hashlib
import json
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from nexus.farm_app.voice_review import transcribe


SOURCES = ("synthetic_test", "human_test", "farmer")


def initialize(store):
    with store.connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS voice_drafts (
                id INTEGER PRIMARY KEY,
                request_id TEXT NOT NULL UNIQUE,
                audio_sha256 TEXT NOT NULL,
                source TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                original_transcript TEXT NOT NULL,
                corrected_transcript TEXT NOT NULL,
                model TEXT NOT NULL,
                revision TEXT NOT NULL,
                metrics TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            )
        """)


def records(store):
    with store.connect() as db:
        return [
            dict(row)
            for row in db.execute(
                "SELECT * FROM voice_drafts ORDER BY id DESC"
            )
        ]


def save_transcription(store, raw, source, request_id):
    if source not in SOURCES:
        raise ValueError("Choose a recording source")

    try:
        request_id = str(uuid.UUID(request_id))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Invalid upload request ID") from None

    digest = hashlib.sha256(raw).hexdigest()

    with store.connect() as db:
        existing = db.execute(
            "SELECT * FROM voice_drafts WHERE request_id=?",
            (request_id,),
        ).fetchone()

        if existing:
            if (
                existing["audio_sha256"] != digest
                or existing["source"] != source
            ):
                raise ValueError(
                    "Upload request ID was reused with different data"
                )

            return dict(existing)

    result = transcribe(raw)
    now = datetime.now(timezone.utc).isoformat()

    metrics = {
        key: result[key]
        for key in (
            "duration_seconds",
            "load_seconds",
            "inference_seconds",
            "confidence",
        )
    }

    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")

        db.execute("""
            INSERT INTO voice_drafts (
                request_id,
                audio_sha256,
                source,
                recorded_at,
                original_transcript,
                corrected_transcript,
                model,
                revision,
                metrics,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(request_id) DO NOTHING
        """, (
            request_id,
            digest,
            source,
            now,
            result["original_transcript"],
            result["original_transcript"],
            result["model"],
            result["revision"],
            json.dumps(metrics),
            now,
        ))

        row = db.execute(
            "SELECT * FROM voice_drafts WHERE request_id=?",
            (request_id,),
        ).fetchone()

        if (
            row["audio_sha256"] != digest
            or row["source"] != source
        ):
            raise ValueError(
                "Upload request ID was reused with different data"
            )

        return dict(row)


def correct(store, data):
    draft_id = data.get("id")
    version = data.get("version")
    text = data.get("corrected_transcript")

    if any(
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        for value in (draft_id, version)
    ):
        raise ValueError("Invalid draft ID or version")

    if (
        not isinstance(text, str)
        or not text.strip()
        or len(text) > 3000
    ):
        raise ValueError(
            "Enter corrected text, maximum 3000 characters"
        )

    with store.connect() as db:
        cursor = db.execute("""
            UPDATE voice_drafts
            SET corrected_transcript=?,
                version=version+1,
                updated_at=?
            WHERE id=? AND version=?
        """, (
            text.strip(),
            datetime.now(timezone.utc).isoformat(),
            draft_id,
            version,
        ))

        if cursor.rowcount != 1:
            raise ValueError(
                "Draft changed or is unavailable. "
                "Refresh before editing."
            )


def make_handler(base, store):
    initialize(store)

    class Handler(base):
        def do_GET(self):
            path = urlparse(self.path).path

            if path == "/voice":
                return self.respond(
                    200,
                    HTML.encode("utf-8"),
                    "text/html; charset=utf-8",
                )

            if path == "/api/voice-drafts":
                return self.respond(200, records(store))

            return super().do_GET()

        def do_POST(self):
            path = urlparse(self.path).path

            if path not in (
                "/api/voice-drafts",
                "/api/voice-draft-correction",
            ):
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

                limit = (
                    2000000
                    if path == "/api/voice-drafts"
                    else 16384
                )

                if not 0 < size <= limit:
                    raise ValueError("Invalid request size")

                raw = self.rfile.read(size)

                if len(raw) != size:
                    raise ValueError("Incomplete request")

                if path == "/api/voice-drafts":
                    result = save_transcription(
                        store,
                        raw,
                        self.headers.get("X-Recording-Source"),
                        self.headers.get("X-Request-ID"),
                    )

                else:
                    data = json.loads(raw.decode("utf-8"))

                    if not isinstance(data, dict):
                        raise ValueError(
                            "Expected a JSON object"
                        )

                    correct(store, data)
                    result = {"saved": True}

            except (ValueError, UnicodeDecodeError) as error:
                return self.respond(
                    400,
                    {"error": str(error)},
                )

            except Exception:
                import traceback

                traceback.print_exc()

                return self.respond(
                    500,
                    {
                        "error": (
                            "Operation could not be confirmed. "
                            "Refresh drafts before retrying; "
                            "see server terminal."
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
<title>NEXUS saved voice drafts</title>

<style>
* { box-sizing: border-box; }

body {
    margin: 0;
    background: #f1f5ee;
    color: #183c2c;
    font: 17px system-ui;
}

header {
    padding: 24px;
    background: #163f30;
    color: white;
}

main {
    max-width: 850px;
    margin: auto;
    padding: 24px;
}

section {
    padding: 22px;
    background: white;
    border-radius: 14px;
    margin: 20px 0;
}

label {
    display: block;
    margin: 16px 0 8px;
}

input, select, textarea, button {
    width: 100%;
    padding: 12px;
    font: inherit;
}

textarea { min-height: 180px; }

button {
    margin-top: 14px;
    background: #1d5c40;
    color: white;
    cursor: pointer;
}

button:disabled { opacity: .5; }

pre {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
}

a { color: inherit; }

#status {
    padding: 14px;
    background: #fff1c6;
}

audio { width: 100%; }
</style>
</head>

<body>
<header>
    <small>LOCAL PILOT · SAVED VOICE DRAFTS</small>
    <h1>NEXUS Voice</h1>
    <a href="/overview">Dashboard</a> ·
    <a href="/">Workspace</a>
</header>

<main>
<p>
    Transcribe Hausa speech and save corrected drafts.
    No farm observation or recommendation is created here.
    Recording source is user-reported.
    Synthetic and human test recordings remain test material.
</p>

<p id="status" role="status" aria-live="polite">
    Loading drafts…
</p>

<section>
    <form id="upload">
        <label for="source">Recording source</label>

        <select id="source" required>
            <option value="">Select…</option>
            <option value="synthetic_test">
                Synthetic / generated test speech
            </option>
            <option value="human_test">
                Human test recording
            </option>
            <option value="farmer">
                Actual farmer recording
            </option>
        </select>

        <label for="file">
            16 kHz mono WAV, up to 30 seconds and 2 MB
        </label>

        <input id="file" type="file" accept=".wav" required>
        <audio id="player" controls></audio>

        <button id="transcribe">
            Transcribe &amp; save draft
        </button>
    </form>

    <p>
        The model stays loaded while this server runs.
        Audio bytes are not retained; keep the original
        recording separately.
    </p>
</section>

<section>
    <h2>Saved voice drafts</h2>

    <button id="refresh" type="button">Refresh drafts</button>

    <label for="draft">Select a saved draft</label>
    <select id="draft"></select>
</section>

<section id="review" hidden>
    <h2>Review saved draft</h2>
    <p id="details"></p>
    <p id="metrics"></p>

    <h3>Original ASR text</h3>
    <pre id="original"></pre>

    <form id="edit">
        <label for="corrected">Corrected Hausa transcript</label>

        <textarea
            id="corrected"
            required
            maxlength="3000"
        ></textarea>

        <button id="save">Save corrected draft</button>
    </form>

    <p>
        Saved corrections survive refresh. Unsaved edits do not.
        The original ASR transcript remains unchanged.
        No calibrated confidence score is provided.
    </p>
</section>

<p>
    Awarri Technologies and the Federal Government of Nigeria,
    developers of N-ATLaS (Hausa-ASR).
</p>
</main>

<script>
const $ = id => document.getElementById(id);

let rows = [];
let selected = null;
let audioUrl = null;
let requestId = null;

const say = text => $("status").textContent = text;

function show() {
    selected = rows.find(
        row => String(row.id) === $("draft").value
    ) || null;

    $("review").hidden = !selected;

    if (!selected) return;

    $("original").textContent = selected.original_transcript;
    $("corrected").value = selected.corrected_transcript;

    $("details").textContent =
        `Draft #${selected.id} · ${selected.source} · ` +
        `Version ${selected.version} · Saved ` +
        new Date(selected.updated_at).toLocaleString();

    const metrics = JSON.parse(selected.metrics);

    $("metrics").textContent =
        `Duration ${metrics.duration_seconds}s · ` +
        `Loading ${metrics.load_seconds}s · ` +
        `Inference ${metrics.inference_seconds}s`;
}

async function load(id) {
    const response = await fetch("/api/voice-drafts");
    const data = await response.json();

    if (!response.ok) {
        throw Error(data.error || "Could not load drafts");
    }

    rows = data;

    const previous = id ? String(id) : $("draft").value;

    $("draft").replaceChildren(
        new Option("Select a draft…", "")
    );

    rows.forEach(row => {
        $("draft").add(new Option(
            `#${row.id} · ${row.source} · ` +
            row.corrected_transcript.slice(0, 60),
            row.id
        ));
    });

    $("draft").value = rows.some(
        row => String(row.id) === previous
    ) ? previous : "";

    show();
}

$("draft").onchange = show;

$("refresh").onclick = () => {
    load()
        .then(() => say("Drafts refreshed."))
        .catch(error => say(error.message));
};

$("source").onchange = () => {
    requestId = null;
};

$("file").onchange = () => {
    requestId = null;

    if (audioUrl) URL.revokeObjectURL(audioUrl);

    const file = $("file").files[0];
    audioUrl = file ? URL.createObjectURL(file) : null;

    if (audioUrl) {
        $("player").src = audioUrl;
    } else {
        $("player").removeAttribute("src");
    }
};

$("upload").onsubmit = async event => {
    event.preventDefault();

    const file = $("file").files[0];

    if (!file || file.size > 2000000) {
        say("Select a WAV file no larger than 2 MB.");
        return;
    }

    requestId = requestId || crypto.randomUUID();

    const source = $("source").value;

    $("transcribe").disabled = true;
    $("file").disabled = true;
    $("source").disabled = true;

    say("Transcribing and saving… Allow the CPU to finish.");

    try {
        const response = await fetch("/api/voice-drafts", {
            method: "POST",
            headers: {
                "Content-Type": "audio/wav",
                "X-Recording-Source": source,
                "X-Request-ID": requestId
            },
            body: file
        });

        const data = await response.json();

        if (!response.ok) {
            throw Error(data.error || "Upload failed");
        }

        await load(data.id);

        say(
            "Voice draft saved. " +
            "No farm observation was created."
        );

    } catch (error) {
        say(error.message);

    } finally {
        $("transcribe").disabled = false;
        $("file").disabled = false;
        $("source").disabled = false;
    }
};

$("edit").onsubmit = async event => {
    event.preventDefault();

    if (!selected) return;

    const id = selected.id;
    const version = selected.version;

    $("save").disabled = true;

    try {
        const response = await fetch(
            "/api/voice-draft-correction",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    id,
                    version,
                    corrected_transcript: $("corrected").value
                })
            }
        );

        const data = await response.json();

        if (!response.ok) {
            throw Error(data.error || "Save failed");
        }

        await load(id);

        say("Correction saved. Original ASR text retained.");

    } catch (error) {
        say(error.message);

    } finally {
        $("save").disabled = false;
    }
};

load()
    .then(() => say("Saved voice drafts ready."))
    .catch(error => say(error.message));
</script>
</body>
</html>
"""


def main():
    from nexus.farm_app import server, decision_cycles

    previous = server.make_handler

    server.make_handler = (
        lambda store: make_handler(previous(store), store)
    )

    decision_cycles.main()


if __name__ == "__main__":
    main()