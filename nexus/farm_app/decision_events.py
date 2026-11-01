import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import UUID

from nexus.farm_app.human_decisions import decision_state


def initialize_events(store):
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("""
            CREATE TABLE IF NOT EXISTS decision_events (
                id INTEGER PRIMARY KEY,
                decision_id INTEGER NOT NULL
                    REFERENCES human_decisions(id),
                kind TEXT NOT NULL
                    CHECK(kind IN ('action','outcome')),
                action_id INTEGER
                    REFERENCES decision_events(id),
                occurred_at TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                description TEXT NOT NULL,
                result TEXT,
                request_id TEXT NOT NULL UNIQUE,
                request_sha256 TEXT NOT NULL,
                CHECK(
                    (
                        kind='action'
                        AND action_id IS NULL
                        AND result IS NULL
                    )
                    OR
                    (
                        kind='outcome'
                        AND action_id IS NOT NULL
                        AND result IN (
                            'improved','unchanged',
                            'worsened','uncertain'
                        )
                    )
                )
            )
        """)


def parse_time(value):
    if not isinstance(value, str):
        raise ValueError("Use a valid time")

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("Use a valid time") from None

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Time must include its timezone")

    return parsed.astimezone(timezone.utc)


def positive_id(value, label):
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
    ):
        raise ValueError("Select a valid " + label)

    return value


def event_state(store):
    state = decision_state(store)

    with closing(sqlite3.connect(store.path)) as db:
        db.row_factory = sqlite3.Row
        state["events"] = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM decision_events ORDER BY id DESC"
            )
        ]

    return state


def save_event(store, data):
    decision_id = positive_id(
        data.get("decision_id"),
        "decision",
    )

    kind = data.get("kind")

    if kind not in ("action", "outcome"):
        raise ValueError("Choose action or outcome")

    description = data.get("description")

    if (
        not isinstance(description, str)
        or not description.strip()
        or len(description) > 3000
    ):
        raise ValueError(
            "Describe what happened (maximum 3000 characters)"
        )

    try:
        request_id = str(
            UUID(data.get("request_id", ""))
        )
    except (ValueError, TypeError, AttributeError):
        raise ValueError(
            "Invalid save request ID. Refresh the page."
        ) from None

    action_id = None
    result = None

    if kind == "outcome":
        action_id = positive_id(
            data.get("action_id"),
            "recorded action",
        )

        result = data.get("result")

        if result not in (
            "improved",
            "unchanged",
            "worsened",
            "uncertain",
        ):
            raise ValueError("Choose a reported result")

    supplied_time = data.get("occurred_at", "")

    if not isinstance(supplied_time, str):
        raise ValueError("Use a valid time")

    request_content = {
        "decision_id": decision_id,
        "kind": kind,
        "action_id": action_id,
        "result": result,
        "description": description.strip(),
        "occurred_at": supplied_time,
    }

    digest = hashlib.sha256(
        json.dumps(
            request_content,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    with closing(sqlite3.connect(store.path)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")

        existing = db.execute(
            """
            SELECT *
            FROM decision_events
            WHERE request_id = ?
            """,
            (request_id,),
        ).fetchone()

        if existing:
            if existing["request_sha256"] != digest:
                raise ValueError(
                    "This save request already stored different "
                    "content. Refresh before saving a new entry."
                )

            return dict(existing)

        now = datetime.now(timezone.utc)
        occurred = (
            parse_time(supplied_time)
            if supplied_time
            else now
        )

        if occurred > now:
            raise ValueError(
                "Recorded event time cannot be in the future"
            )

        decision = db.execute(
            """
            SELECT recorded_at
            FROM human_decisions
            WHERE id = ?
            """,
            (decision_id,),
        ).fetchone()

        if not decision:
            raise ValueError("Human decision not found")

        if occurred < parse_time(decision["recorded_at"]):
            raise ValueError(
                "Event time must be on or after "
                "the decision was recorded"
            )

        if kind == "outcome":
            action = db.execute(
                """
                SELECT *
                FROM decision_events
                WHERE id = ?
                """,
                (action_id,),
            ).fetchone()

            if (
                not action
                or action["kind"] != "action"
                or action["decision_id"] != decision_id
            ):
                raise ValueError(
                    "Choose an action from this decision"
                )

            if occurred < parse_time(action["occurred_at"]):
                raise ValueError(
                    "Outcome time must be on or after its action"
                )

        cursor = db.execute(
            """
            INSERT INTO decision_events (
                decision_id,
                kind,
                action_id,
                occurred_at,
                recorded_at,
                description,
                result,
                request_id,
                request_sha256
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision_id,
                kind,
                action_id,
                occurred.isoformat(),
                now.isoformat(),
                description.strip(),
                result,
                request_id,
                digest,
            ),
        )

        return dict(
            db.execute(
                """
                SELECT *
                FROM decision_events
                WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
        )


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS decision actions and outcomes</title>
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
main{max-width:950px;margin:auto;padding:24px}
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
textarea{min-height:100px}
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
<small>LOCAL PILOT · DECISION ACTIONS & OUTCOMES</small>
<h1>NEXUS decision actions and outcomes</h1>
<nav>
<a href="/human-decisions">Human decisions</a>
<a href="/review-bundles">Saved bundles</a>
<a href="/overview">Dashboard</a>
<a href="/">Workspace</a>
</nav>
</header>

<main>
<p>Record work actually performed after a saved decision, then report what
was observed after that work. These records do not execute equipment,
change workspace tasks or establish that an action caused a result.</p>

<div id="message" role="status" aria-live="polite">Loading…</div>

<section>
<label for="decision">Human decision</label>
<select id="decision"></select>
<div id="plan"></div>
<button id="refresh" type="button">Refresh records</button>
</section>

<section>
<h2>1. Record work actually performed</h2>
<form id="action-form">
<label for="performed">
Performed at (local time; blank means now)
</label>
<input id="performed" name="occurred_at" type="datetime-local">

<label for="work">
What was actually done, by whom, and what was found?
</label>
<textarea id="work" name="description"
required maxlength="3000"></textarea>

<button>Save action record</button>
</form>
</section>

<section>
<h2>2. Record a later reported outcome</h2>
<form id="outcome-form">
<label for="action">Action this report follows</label>
<select id="action" name="action_id" required></select>

<label for="result">Reported result</label>
<select id="result" name="result">
<option value="uncertain">Uncertain</option>
<option value="improved">Improved</option>
<option value="unchanged">Unchanged</option>
<option value="worsened">Worsened</option>
</select>

<label for="observed">
Observed at (local time; blank means now)
</label>
<input id="observed" name="occurred_at" type="datetime-local">

<label for="evidence">
Describe observable evidence and limitations
</label>
<textarea id="evidence" name="description"
required maxlength="3000"></textarea>

<p>Reported outcomes are not independently verified.</p>
<button>Save reported outcome</button>
</form>
</section>

<section>
<h2>Records for selected decision</h2>
<p>Earlier entries remain available. To document a correction, add a new
entry identifying the earlier record and explaining the correction.</p>
<div id="history"></div>
</section>
</main>

<script>
const $ = id => document.getElementById(id);

let state = {decisions: [], events: []};
let busy = false;

const tokens = {
    'action-form': crypto.randomUUID(),
    'outcome-form': crypto.randomUUID()
};

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

function render() {
    const id = Number($('decision').value);
    const decision = state.decisions.find(d => d.id === id);

    $('plan').replaceChildren();
    $('history').replaceChildren();

    const previous = $('action').value;

    $('action').replaceChildren(
        new Option('Select a recorded action…', '')
    );

    const events = state.events.filter(
        e => e.decision_id === id
    );

    if (decision) {
        const link = node(
            'a',
            'Read supporting bundle #' + decision.bundle_id
        );

        link.href =
            '/review-bundles?bundle_id=' + decision.bundle_id;

        $('plan').append(
            node('p', decision.payload.next_step),
            node(
                'p',
                'Decision recorded: ' + local(decision.recorded_at)
            ),
            link
        );
    }

    for (const event of events.filter(e => e.kind === 'action')) {
        $('action').add(
            new Option(
                'Action #' + event.id +
                ' · ' + local(event.occurred_at) +
                ' · ' + event.description.slice(0, 70),
                event.id
            )
        );
    }

    if (
        events.some(
            e => e.kind === 'action' &&
                 String(e.id) === previous
        )
    ) {
        $('action').value = previous;
    }

    if (!events.length) {
        $('history').append(
            node(
                'p',
                'No action or outcome records for this decision.'
            )
        );
    }

    for (const event of events) {
        const article = node('article', '');

        article.append(
            node(
                'h3',
                (event.kind === 'action'
                    ? 'Action'
                    : 'Reported outcome') +
                ' #' + event.id
            ),
            node('p', 'Occurred: ' + local(event.occurred_at)),
            node('p', 'Recorded: ' + local(event.recorded_at)),
            node('p', event.description)
        );

        if (event.kind === 'outcome') {
            article.append(
                node(
                    'p',
                    'Follows action #' + event.action_id +
                    ' · Reported ' + event.result +
                    ' · Not independently verified'
                )
            );
        }

        $('history').append(article);
    }

    $('action-form').querySelector('button').disabled =
        busy || !decision;

    $('outcome-form').querySelector('button').disabled =
        busy || $('action').options.length === 1;

    $('decision').disabled = busy;
    $('refresh').disabled = busy;
}

async function load() {
    const previous = $('decision').value;

    state = await request('/api/decision-events');

    $('decision').replaceChildren(
        new Option('Select a human decision…', '')
    );

    for (const decision of state.decisions) {
        $('decision').add(
            new Option(
                'Decision #' + decision.id +
                ' · ' + decision.payload.next_step.slice(0, 90),
                decision.id
            )
        );
    }

    if (
        state.decisions.some(
            d => String(d.id) === previous
        )
    ) {
        $('decision').value = previous;
    }

    render();
}

$('decision').onchange = render;

$('refresh').onclick = () => {
    load()
        .then(() => {
            $('message').textContent = 'Records refreshed.';
        })
        .catch(error => {
            $('message').textContent = error.message;
        });
};

for (const [formId, kind] of [
    ['action-form', 'action'],
    ['outcome-form', 'outcome']
]) {
    $(formId).onsubmit = async event => {
        event.preventDefault();

        if (busy) return;

        const form = event.currentTarget;
        const data = Object.fromEntries(new FormData(form));

        data.decision_id = Number($('decision').value);
        data.kind = kind;
        data.request_id = tokens[formId];

        if ('action_id' in data) {
            data.action_id = Number(data.action_id);
        }

        if (data.occurred_at) {
            data.occurred_at =
                new Date(data.occurred_at).toISOString();
        }

        busy = true;
        render();
        let saved = false;

        try {
            const result = await request(
                '/api/decision-events',
                data
            );

            saved = true;
            tokens[formId] = crypto.randomUUID();
            form.reset();
            await load();

            $('message').textContent =
                (kind === 'action'
                    ? 'Action'
                    : 'Reported outcome') +
                ' #' + result.id + ' saved.';
        } catch (error) {
            $('message').textContent = saved
                ? 'Record saved, but refresh failed. Refresh before entering another record.'
                : error.message;
        } finally {
            busy = false;
            render();
        }
    };
}

load()
    .then(() => {
        $('message').textContent = 'Decision records ready.';
    })
    .catch(error => {
        $('message').textContent = error.message;
    });
</script>
</body>
</html>
"""


def events_handler(base_factory):
    def make_handler(store):
        base = base_factory(store)
        initialize_events(store)

        class Handler(base):
            def do_GET(self):
                path = urlparse(self.path).path

                try:
                    if path == "/decision-events":
                        return self.respond(
                            200,
                            PAGE.encode("utf-8"),
                            "text/html; charset=utf-8",
                        )

                    if path == "/api/decision-events":
                        return self.respond(
                            200,
                            event_state(store),
                        )

                    return super().do_GET()

                except sqlite3.Error:
                    self.respond(
                        500,
                        {"error": "Could not read decision records."},
                    )

            def do_POST(self):
                if urlparse(self.path).path != "/api/decision-events":
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

                    if not 0 < size <= 16384:
                        raise ValueError("Invalid request size")

                    data = json.loads(
                        self.rfile.read(size).decode("utf-8")
                    )

                    if not isinstance(data, dict):
                        raise ValueError("Expected a JSON object")

                    result = save_event(store, data)

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
                                "Could not save this decision record."
                            )
                        },
                    )

                self.respond(200, result)

        return Handler

    return make_handler


def main():
    from nexus.farm_app import server, human_decisions

    original = server.make_handler
    server.make_handler = events_handler(original)

    print(
        "Decision actions and outcomes: /decision-events",
        flush=True,
    )

    try:
        human_decisions.main()
    finally:
        server.make_handler = original


if __name__ == "__main__":
    main()