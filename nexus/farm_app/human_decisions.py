import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

from nexus.farm_app.review_bundles import read_bundles


LAGOS = timezone(timedelta(hours=1))


def initialize_decisions(store):
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("""
            CREATE TABLE IF NOT EXISTS human_decisions (
                id INTEGER PRIMARY KEY,
                bundle_id INTEGER NOT NULL
                    REFERENCES decision_review_bundles(id),
                recorded_at TEXT NOT NULL,
                content_sha256 TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL
            )
        """)


def decision_state(store):
    with closing(sqlite3.connect(store.path)) as db:
        db.row_factory = sqlite3.Row
        decisions = []

        for row in db.execute(
            "SELECT * FROM human_decisions ORDER BY id DESC"
        ):
            decision = dict(row)
            decision["payload"] = json.loads(decision["payload"])
            decisions.append(decision)

    return {
        "bundles": read_bundles(store),
        "decisions": decisions,
    }


def save_decision(store, data):
    bundle_id = data.get("bundle_id")

    if (
        isinstance(bundle_id, bool)
        or not isinstance(bundle_id, int)
        or bundle_id < 1
    ):
        raise ValueError("Select a saved bundle")

    content = {
        "decision_version": "human-decision-v1",
        "decision_source": "workspace_user",
        "bundle_id": bundle_id,
    }

    for key in (
        "decision_maker",
        "next_step",
        "supporting_evidence",
        "uncertainties",
        "constraints",
    ):
        value = data.get(key)

        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 3000
        ):
            raise ValueError(
                "Complete every text field "
                "(maximum 3000 characters). "
                "State unknown or none identified when appropriate."
            )

        content[key] = value.strip()

    review_date = data.get("review_date")

    if not isinstance(review_date, str):
        raise ValueError("Choose a review date")

    try:
        parsed_date = date.fromisoformat(review_date)
    except ValueError:
        raise ValueError("Choose a valid review date") from None

    if parsed_date.isoformat() != review_date:
        raise ValueError(
            "Use a review date in YYYY-MM-DD format"
        )

    if parsed_date < datetime.now(LAGOS).date():
        raise ValueError(
            "Review date cannot be before today (Lagos time)"
        )

    content["review_date"] = review_date

    with closing(sqlite3.connect(store.path)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")

        bundle = db.execute(
            """
            SELECT observation_id, content_sha256
            FROM decision_review_bundles
            WHERE id = ?
            """,
            (bundle_id,),
        ).fetchone()

        if not bundle:
            raise ValueError("Saved bundle not found")

        content["observation_id"] = bundle["observation_id"]
        content["bundle_content_sha256"] = bundle["content_sha256"]

        raw = json.dumps(
            content,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )

        digest = hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()

        db.execute(
            """
            INSERT INTO human_decisions (
                bundle_id,
                recorded_at,
                content_sha256,
                payload
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(content_sha256) DO NOTHING
            """,
            (
                bundle_id,
                datetime.now(timezone.utc).isoformat(),
                digest,
                raw,
            ),
        )

        row = db.execute(
            """
            SELECT *
            FROM human_decisions
            WHERE content_sha256 = ?
            """,
            (digest,),
        ).fetchone()

        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        return result


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS human decisions</title>
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
    max-width:950px;
    margin:auto;
    padding:24px;
}
section{
    background:white;
    padding:22px;
    border-radius:14px;
    margin:18px 0;
}
label{display:block;margin:16px 0 6px}
input,select,textarea,button{
    width:100%;
    font:inherit;
    padding:12px;
    border:1px solid #bdcbbb;
    border-radius:8px;
}
textarea{min-height:90px}
button{
    background:#1d5c40;
    color:white;
    margin-top:16px;
    cursor:pointer;
}
button:disabled{opacity:.5}
a{color:inherit;margin-right:18px}
article{border-top:1px solid #ccd8ce;padding:16px 0}
p{white-space:pre-wrap;overflow-wrap:anywhere}
#message{padding:14px;background:#fff1c6}
</style>
</head>
<body>
<header>
<small>LOCAL PILOT · HUMAN DECISIONS</small>
<h1>NEXUS human decisions</h1>
<nav>
<a href="/overview">Dashboard</a>
<a href="/review-bundles">Saved bundles</a>
<a href="/decision-review">Current review</a>
<a href="/">Workspace</a>
</nav>
</header>
<main>
<p>Record a human-selected plan based on a saved review bundle.
Saving does not execute the plan, complete a task or verify a diagnosis.
Names are user-entered; NEXUS does not authenticate the decision maker.</p>

<div id="message" role="status" aria-live="polite">Loading…</div>

<section>
<h2>Record a decision</h2>
<form id="decision">
<label for="bundle">Saved review bundle</label>
<select id="bundle" name="bundle_id" required></select>
<p><a id="bundle-link" hidden>Read selected bundle</a></p>

<label for="maker">Decision maker / role as reported</label>
<input id="maker" name="decision_maker" required maxlength="3000">

<label for="step">Chosen next step</label>
<textarea id="step" name="next_step" required maxlength="3000"></textarea>

<label for="evidence">Supporting evidence from the selected bundle</label>
<textarea id="evidence" name="supporting_evidence"
required maxlength="3000"></textarea>

<label for="unknown">Uncertainties / information still needed</label>
<textarea id="unknown" name="uncertainties"
required maxlength="3000"></textarea>

<label for="constraints">Resources / constraints considered</label>
<textarea id="constraints" name="constraints"
required maxlength="3000"></textarea>

<label for="date">Review date (Lagos calendar date)</label>
<input id="date" name="review_date" type="date" required>

<p>This date records the plan. No reminder or notification is created.
Use scheduled follow-ups in the workspace for a separate reminder.</p>

<button id="save">Save human decision</button>
</form>
</section>

<section>
<h2>Saved decisions</h2>
<p>Earlier entries are retained. Record a new decision to document a
revised plan. An identical submission reuses its existing record.</p>
<button id="refresh" type="button">Refresh saved decisions</button>
<div id="history"></div>
</section>
</main>

<script>
const $ = id => document.getElementById(id);

function node(tag, value) {
    const n = document.createElement(tag);
    n.textContent = value;
    return n;
}

function local(value) {
    return new Date(value).toLocaleString(
        'en-GB',
        {timeZone: 'Africa/Lagos'}
    ) + ' (Lagos time)';
}

async function request(path, data) {
    const response = await fetch(
        path,
        data ? {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(data)
        } : {}
    );

    const result = await response.json();

    if (!response.ok) {
        throw Error(result.error || 'Request failed');
    }

    return result;
}

function link() {
    const id = $('bundle').value;
    $('bundle-link').hidden = !id;

    if (id) {
        $('bundle-link').href =
            '/review-bundles?bundle_id=' + encodeURIComponent(id);
    }
}

async function load() {
    const state = await request('/api/human-decisions');
    const previous = $('bundle').value;

    $('bundle').replaceChildren(
        new Option('Select a saved bundle…', '')
    );

    for (const b of state.bundles) {
        $('bundle').add(
            new Option(
                'Bundle #' + b.id +
                ' · observation #' + b.observation_id +
                ' · ' + local(b.captured_at),
                b.id
            )
        );
    }

    if (state.bundles.some(b => String(b.id) === previous)) {
        $('bundle').value = previous;
    }

    link();
    $('save').disabled = !state.bundles.length;
    $('history').replaceChildren();

    if (!state.decisions.length) {
        $('history').append(
            node('p', 'No human decisions recorded.')
        );
    }

    for (const d of state.decisions) {
        const p = d.payload;
        const a = node('article', '');
        const l = node(
            'a',
            'Read supporting bundle #' + d.bundle_id
        );

        l.href = '/review-bundles?bundle_id=' + d.bundle_id;

        a.append(
            node('h3', 'Decision #' + d.id),
            l,
            node('p', 'Recorded: ' + local(d.recorded_at))
        );

        for (const [label, key] of [
            ['Decision maker', 'decision_maker'],
            ['Chosen next step', 'next_step'],
            ['Supporting evidence', 'supporting_evidence'],
            ['Uncertainties', 'uncertainties'],
            ['Resources / constraints', 'constraints'],
            ['Review date', 'review_date']
        ]) {
            a.append(
                node('h4', label),
                node('p', p[key])
            );
        }

        $('history').append(a);
    }
}

$('bundle').onchange = link;

$('refresh').onclick = () => {
    load()
        .then(() => {
            $('message').textContent = 'Saved decisions refreshed.';
        })
        .catch(error => {
            $('message').textContent = error.message;
        });
};

$('decision').onsubmit = async event => {
    event.preventDefault();
    $('save').disabled = true;

    const data = Object.fromEntries(
        new FormData(event.currentTarget)
    );

    data.bundle_id = Number(data.bundle_id);
    let saved = false;

    try {
        const result = await request(
            '/api/human-decisions',
            data
        );

        saved = true;
        $('decision').reset();
        await load();

        $('message').textContent =
            'Decision #' + result.id +
            ' saved. The plan has not been executed.';
    } catch (error) {
        $('message').textContent = saved
            ? 'Decision saved, but the list could not refresh. Refresh before retrying.'
            : error.message;
    } finally {
        $('save').disabled =
            $('bundle').options.length <= 1;
    }
};

load()
    .then(() => {
        $('message').textContent = 'Human decisions ready.';
    })
    .catch(error => {
        $('message').textContent = error.message;
    });
</script>
</body>
</html>
"""


def decisions_handler(base_factory):
    def make_handler(store):
        initialize_decisions(store)

        class Handler(base_factory(store)):
            def do_GET(self):
                path = urlparse(self.path).path

                try:
                    if path == "/human-decisions":
                        return self.respond(
                            200,
                            PAGE.encode("utf-8"),
                            "text/html; charset=utf-8",
                        )

                    if path == "/api/human-decisions":
                        return self.respond(
                            200,
                            decision_state(store),
                        )

                    return super().do_GET()

                except sqlite3.Error:
                    self.respond(
                        500,
                        {"error": "Could not read human decisions."},
                    )

            def do_POST(self):
                if urlparse(self.path).path != "/api/human-decisions":
                    return super().do_POST()

                origin = self.headers.get("Origin")

                if (
                    origin
                    and origin != "http://" + self.headers.get("Host", "")
                ):
                    return self.respond(
                        403,
                        {"error": "Cross-origin request rejected"},
                    )

                try:
                    size = int(
                        self.headers.get("Content-Length", "0")
                    )

                    if not 0 < size <= 32768:
                        raise ValueError("Invalid request size")

                    data = json.loads(
                        self.rfile.read(size).decode("utf-8")
                    )

                    if not isinstance(data, dict):
                        raise ValueError("Expected a JSON object")

                    result = save_decision(store, data)

                except (ValueError, UnicodeDecodeError) as error:
                    return self.respond(
                        400,
                        {"error": str(error)},
                    )

                except sqlite3.Error:
                    return self.respond(
                        500,
                        {"error": "Could not save the decision."},
                    )

                self.respond(200, result)

        return Handler

    return make_handler


def main():
    from nexus.farm_app import server, review_bundles

    original = server.make_handler
    server.make_handler = decisions_handler(original)

    print("Human decisions: /human-decisions", flush=True)

    try:
        review_bundles.main()
    finally:
        server.make_handler = original


if __name__ == "__main__":
    main()