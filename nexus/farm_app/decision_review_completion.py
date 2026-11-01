import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, timezone
from urllib.parse import urlparse
from uuid import UUID

from nexus.farm_app.human_decisions import LAGOS
from nexus.farm_app.decision_events import parse_time
from nexus.farm_app.decision_reviews import review_timing


def initialize_reviews(store):
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("""
            CREATE TABLE IF NOT EXISTS human_decision_reviews (
                id INTEGER PRIMARY KEY,
                decision_id INTEGER NOT NULL
                    REFERENCES human_decisions(id),
                reviewed_at TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                reviewer TEXT NOT NULL,
                conclusion TEXT NOT NULL,
                disposition TEXT NOT NULL
                    CHECK(disposition IN ('keep','revise','close')),
                next_review_date TEXT,
                request_id TEXT NOT NULL UNIQUE,
                request_sha256 TEXT NOT NULL
            )
        """)
        columns = {row[1] for row in db.execute("PRAGMA table_info(human_decision_reviews)")}
        if "evidence_bundle_id" not in columns:
            db.execute("ALTER TABLE human_decision_reviews ADD COLUMN evidence_bundle_id INTEGER REFERENCES decision_review_bundles(id)")
        if "evidence_bundle_sha256" not in columns:
            db.execute("ALTER TABLE human_decision_reviews ADD COLUMN evidence_bundle_sha256 TEXT")


def read_review_state(store):
    checked = datetime.now(timezone.utc)

    with closing(sqlite3.connect(store.path)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")

        decisions = []

        for row in db.execute(
            "SELECT * FROM human_decisions ORDER BY id DESC"
        ):
            decision = dict(row)
            decision["payload"] = json.loads(decision["payload"])
            decisions.append(decision)

        reviews = [
            dict(row)
            for row in db.execute(
                """
                SELECT *
                FROM human_decision_reviews
                ORDER BY id DESC
                """
            )
        ]

    with closing(sqlite3.connect(store.path)) as db:
        db.row_factory = sqlite3.Row
        bundles = [dict(row) for row in db.execute(
            "SELECT id, observation_id, captured_at FROM decision_review_bundles ORDER BY id DESC"
        )]

    for decision in decisions:
        latest = next(
            (
                review
                for review in reviews
                if review["decision_id"] == decision["id"]
            ),
            None,
        )

        decision["latest_review"] = latest

        if latest and latest["disposition"] == "close":
            decision["review_status"] = "Review tracking closed"
            decision["active_review_date"] = None
            decision["timing_rank"] = 4

        else:
            due = (
                latest["next_review_date"]
                if latest
                else decision["payload"].get("review_date")
            )

            label, rank, planned = review_timing(
                due,
                checked.astimezone(LAGOS).date(),
            )

            decision["active_review_date"] = due
            decision["review_status"] = label
            decision["timing_rank"] = rank

    decisions.sort(
        key=lambda decision: (
            decision["timing_rank"],
            decision["active_review_date"] or "9999-12-31",
            decision["id"],
        )
    )

    return {
        "checked_at": checked.isoformat(),
        "decisions": decisions,
        "reviews": reviews,
        "bundles": bundles,
    }


def save_review(store, data):
    decision_id = data.get("decision_id")

    if (
        isinstance(decision_id, bool)
        or not isinstance(decision_id, int)
        or decision_id < 1
    ):
        raise ValueError("Select a human decision")

    expected_id = data.get("expected_review_id")

    if expected_id is not None and (
        isinstance(expected_id, bool)
        or not isinstance(expected_id, int)
        or expected_id < 1
    ):
        raise ValueError("Invalid prior review ID")

    try:
        request_id = str(
            UUID(data.get("request_id", ""))
        )
    except (ValueError, TypeError, AttributeError):
        raise ValueError(
            "Invalid save request. Refresh the page."
        ) from None

    content = {
        "decision_id": decision_id,
        "expected_review_id": expected_id,
    }

    for key in ("reviewer", "conclusion"):
        value = data.get(key)

        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 3000
        ):
            raise ValueError(
                "Complete reviewer and conclusion "
                "(maximum 3000 characters)"
            )

        content[key] = value.strip()

    disposition = data.get("disposition")

    if disposition not in ("keep", "revise", "close"):
        raise ValueError(
            "Choose keep, request revision or close tracking"
        )

    content["disposition"] = disposition

    supplied = data.get("reviewed_at", "")

    if not isinstance(supplied, str):
        raise ValueError("Use a valid review time")

    content["reviewed_at"] = supplied

    next_date = data.get("next_review_date", "")

    if not isinstance(next_date, str):
        raise ValueError("Use a valid next review date")

    if disposition == "close":
        next_date = None

    content["next_review_date"] = next_date

    evidence_id = data.get("evidence_bundle_id")
    if evidence_id is not None:
        if type(evidence_id) is not int or evidence_id < 1:
            raise ValueError("Select a valid evidence bundle")
        content["evidence_bundle_id"] = evidence_id

    digest = hashlib.sha256(
        json.dumps(
            content,
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
            FROM human_decision_reviews
            WHERE request_id = ?
            """,
            (request_id,),
        ).fetchone()

        if existing:
            if existing["request_sha256"] != digest:
                raise ValueError(
                    "This request already saved different "
                    "content. Refresh first."
                )

            return dict(existing)

        now = datetime.now(timezone.utc)
        reviewed = parse_time(supplied) if supplied else now

        if reviewed > now:
            raise ValueError("Review time cannot be in the future")

        decision = db.execute(
            """
            SELECT recorded_at, bundle_id
            FROM human_decisions
            WHERE id = ?
            """,
            (decision_id,),
        ).fetchone()

        if not decision:
            raise ValueError("Human decision not found")

        if reviewed < parse_time(decision["recorded_at"]):
            raise ValueError(
                "Review must be on or after "
                "the decision was recorded"
            )

        evidence_hash = None
        if evidence_id is not None:
            original_bundle = db.execute(
                "SELECT observation_id FROM decision_review_bundles WHERE id=?",
                (decision["bundle_id"],),
            ).fetchone()
            evidence = db.execute(
                "SELECT * FROM decision_review_bundles WHERE id=?", (evidence_id,)
            ).fetchone()
            if (not original_bundle or not evidence
                    or evidence["observation_id"] != original_bundle["observation_id"]):
                raise ValueError("Choose a bundle for this decision's observation")
            if parse_time(evidence["captured_at"]) > reviewed:
                raise ValueError("Evidence bundle was captured after the review time")
            parsed = json.loads(evidence["payload"])
            canonical = json.dumps(parsed, sort_keys=True, ensure_ascii=False, allow_nan=False)
            evidence_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if evidence_hash != evidence["content_sha256"]:
                raise ValueError("Evidence bundle hash mismatch")

        latest = db.execute(
            """
            SELECT *
            FROM human_decision_reviews
            WHERE decision_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (decision_id,),
        ).fetchone()

        latest_id = latest["id"] if latest else None

        if latest_id != expected_id:
            raise ValueError(
                "A newer review was saved. Refresh and "
                "read it before submitting."
            )

        if (
            latest
            and reviewed < parse_time(latest["reviewed_at"])
        ):
            raise ValueError(
                "Review time cannot predate "
                "the latest saved review"
            )

        if next_date is not None:
            try:
                planned = date.fromisoformat(next_date)
            except ValueError:
                raise ValueError(
                    "Choose a next review date"
                ) from None

            if planned.isoformat() != next_date:
                raise ValueError(
                    "Use YYYY-MM-DD for the next review date"
                )

            if planned < now.astimezone(LAGOS).date():
                raise ValueError(
                    "Next review date cannot be before "
                    "today (Lagos time)"
                )

        cursor = db.execute(
            """
            INSERT INTO human_decision_reviews (
                decision_id,
                reviewed_at,
                recorded_at,
                reviewer,
                conclusion,
                disposition,
                next_review_date,
                request_id,
                request_sha256,
                evidence_bundle_id,
                evidence_bundle_sha256
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision_id,
                reviewed.isoformat(),
                now.isoformat(),
                content["reviewer"],
                content["conclusion"],
                disposition,
                next_date,
                request_id,
                digest,
                evidence_id,
                evidence_hash,
            ),
        )

        return dict(
            db.execute(
                """
                SELECT *
                FROM human_decision_reviews
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
<title>NEXUS decision reviews</title>
<style>
*{box-sizing:border-box}
body{
    margin:0;
    background:#f1f5ee;
    color:#183c2c;
    font:16px system-ui;
}
header{background:#163f30;color:white;padding:28px}
main{max-width:1000px;margin:auto;padding:24px}
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
    cursor:pointer;
    margin-top:16px;
}
button:disabled{opacity:.5}
a{color:inherit;margin-right:18px}
p{white-space:pre-wrap;overflow-wrap:anywhere}
article{border-top:1px solid #ccd8ce;padding:14px 0}
#message{padding:14px;background:#fff1c6}
</style>
</head>
<body>
<header>
<small>LOCAL PILOT · DECISION REVIEWS</small>
<h1>NEXUS decision reviews</h1>
<nav>
<a href="/decision-report">Decision reports</a>
<a href="/human-decisions">Human decisions</a>
<a href="/decision-events">Actions & outcomes</a>
<a href="/overview">Dashboard</a>
</nav>
</header>
<main>
<p>Record an actual review. Reviewer identities and conclusions are user-entered.
Keeping a plan sets its next review date. Requesting revision records that need;
save any changed plan separately under Human decisions.
Closing ends review tracking for this decision. It does not establish successful work,
complete workspace tasks or change the saved plan or evidence bundle.</p>

<div id="message" role="status" aria-live="polite">Loading…</div>

<section>
<h2>Review queue</h2>
<button id="refresh" type="button">Refresh reviews</button>
<div id="queue"></div>
</section>

<section>
<h2>Record a review</h2>
<form id="form">
<label for="decision">Human decision</label>
<select id="decision" required></select>
<div id="selected"></div>

<label for="evidence-bundle">Evidence bundle reviewed (optional)</label>
<select id="evidence-bundle" name="evidence_bundle_id"></select>
<p>The selected bundle is referenced by ID and content hash. It does not replace the decision's original supporting bundle. Select only evidence you actually reviewed.</p>
<div id="evidence-link"></div>
<label for="reviewer">Reviewer / role as reported</label>
<input id="reviewer" name="reviewer" required maxlength="3000">

<label for="time">Reviewed at (local time; blank means now)</label>
<input id="time" name="reviewed_at" type="datetime-local">

<label for="conclusion">
What did you review and conclude? Include unresolved issues.
</label>
<textarea id="conclusion" name="conclusion"
required maxlength="3000"></textarea>

<label for="disposition">Review conclusion</label>
<select id="disposition" name="disposition">
<option value="keep">Keep plan and set next review date</option>
<option value="revise">Request plan revision and set next review date</option>
<option value="close">Close this decision's review tracking</option>
</select>

<label for="next">
Next review date (Lagos date; required unless closing)
</label>
<input id="next" name="next_review_date" type="date" required>

<p>Saving a keep review for a closed decision reopens its review tracking.
No background notification is created.</p>

<button id="save">Save review</button>
</form>
</section>

<section>
<h2>Review history for selected decision</h2>
<p>Earlier reviews remain available. A later review updates tracking without erasing them.</p>
<div id="history"></div>
</section>
</main>

<script>
const $ = id => document.getElementById(id);

let state = {decisions: [], reviews: []};
let busy = false;
let token = crypto.randomUUID();

function node(tag, value) {
    const element = document.createElement(tag);
    element.textContent = value;
    return element;
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

function disposition() {
    const closed = $('disposition').value === 'close';
    $('next').disabled = closed;
    $('next').required = !closed;
}

function evidenceLink() {
    $('evidence-link').replaceChildren();
    const id = Number($('evidence-bundle').value);
    if (id) {
        const link = node('a', 'Read selected evidence bundle #' + id);
        link.href = '/review-bundles?bundle_id=' + id;
        $('evidence-link').append(link);
    }
}

function selected() {
    const decision = state.decisions.find(
        d => d.id === Number($('decision').value)
    );

    const priorEvidence = $('evidence-bundle').value;
    $('evidence-bundle').replaceChildren(new Option('No additional bundle selected', ''));
    if (decision) {
        const original = (state.bundles || []).find(b => b.id === decision.bundle_id);
        for (const b of (state.bundles || []).filter(b => original && b.observation_id === original.observation_id)) {
            $('evidence-bundle').add(new Option('Bundle #' + b.id + ' · ' + local(b.captured_at), b.id));
        }
        if ([...$('evidence-bundle').options].some(o => o.value === priorEvidence)) $('evidence-bundle').value = priorEvidence;
    }
    $('evidence-bundle').disabled = busy || !decision;
    evidenceLink();
    $('selected').replaceChildren();
    $('history').replaceChildren();

    if (decision) {
        const link = node(
            'a',
            'Read Decision #' + decision.id
        );

        link.href =
            '/decision-report?decision_id=' + decision.id;

        $('selected').append(
            node('p', decision.payload.next_step),
            node('p', decision.review_status),
            link
        );

        for (const review of state.reviews.filter(
            r => r.decision_id === decision.id
        )) {
            const article = node('article', '');

            article.append(
                node(
                    'h3',
                    'Review #' + review.id +
                    ' · ' + review.disposition
                ),
                node(
                    'p',
                    'Reviewed: ' + local(review.reviewed_at)
                ),
                node(
                    'p',
                    'Recorded: ' + local(review.recorded_at)
                ),
                node('p', 'Reviewer: ' + review.reviewer),
                node('p', review.conclusion),
                node(
                    'p',
                    'Next review: ' +
                    (review.next_review_date || 'Tracking closed')
                )
            );

            if (review.evidence_bundle_id) {
                const evidence = node('a', 'Evidence bundle reviewed #' + review.evidence_bundle_id);
                evidence.href = '/review-bundles?bundle_id=' + review.evidence_bundle_id;
                article.append(evidence, node('p', 'Captured reference SHA-256: ' + review.evidence_bundle_sha256));
            } else {
                article.append(node('p', 'No additional evidence bundle reference recorded.'));
            }
            $('history').append(article);
        }

        if (!state.reviews.some(
            r => r.decision_id === decision.id
        )) {
            $('history').append(
                node('p', 'No review recorded yet.')
            );
        }
    }

    $('save').disabled = busy || !decision;
}

async function load() {
    const previous = $('decision').value;

    state = await request('/api/decision-reviews');

    $('decision').replaceChildren(
        new Option('Select a human decision…', '')
    );

    $('queue').replaceChildren(
        node('p', 'Checked: ' + local(state.checked_at))
    );

    if (!state.decisions.length) {
        $('queue').append(
            node('p', 'No decisions recorded.')
        );
    }

    for (const decision of state.decisions) {
        $('decision').add(
            new Option(
                'Decision #' + decision.id +
                ' · ' + decision.review_status,
                decision.id
            )
        );

        const article = node('article', '');
        const link = node('a', 'Read decision report');

        link.href =
            '/decision-report?decision_id=' + decision.id;

        article.append(
            node('h3', 'Decision #' + decision.id),
            node('p', decision.review_status),
            node(
                'p',
                'Active review date: ' +
                (decision.active_review_date || 'None')
            ),
            node('p', decision.payload.next_step),
            link
        );

        if (decision.latest_review) {
            article.append(
                node(
                    'p',
                    'Latest review #' +
                    decision.latest_review.id +
                    ' · ' + decision.latest_review.disposition
                )
            );
        }

        $('queue').append(article);
    }

    if (state.decisions.some(
        d => String(d.id) === previous
    )) {
        $('decision').value = previous;
    }

    selected();
}

$('decision').onchange = () => { $('evidence-bundle').value = ''; selected(); };
$('evidence-bundle').onchange = evidenceLink;
$('disposition').onchange = disposition;

$('refresh').onclick = () => {
    load()
        .then(() => {
            $('message').textContent = 'Reviews refreshed.';
        })
        .catch(error => {
            $('message').textContent = error.message;
        });
};

$('form').onsubmit = async event => {
    event.preventDefault();

    if (busy) return;

    const decision = state.decisions.find(
        d => d.id === Number($('decision').value)
    );

    if (!decision) return;

    const data = Object.fromEntries(
        new FormData(event.currentTarget)
    );

    data.evidence_bundle_id = data.evidence_bundle_id ? Number(data.evidence_bundle_id) : null;
    data.decision_id = decision.id;
    data.expected_review_id =
        decision.latest_review?.id ?? null;
    data.request_id = token;

    if (data.reviewed_at) {
        data.reviewed_at =
            new Date(data.reviewed_at).toISOString();
    }

    busy = true;
    $('decision').disabled = true;
    $('refresh').disabled = true;
    selected();

    let saved = false;

    try {
        const result = await request(
            '/api/decision-reviews',
            data
        );

        saved = true;
        token = crypto.randomUUID();
        $('form').reset();
        disposition();
        await load();

        $('message').textContent =
            'Review #' + result.id +
            ' saved. Review tracking updated.';
    } catch (error) {
        $('message').textContent = saved
            ? 'Review saved, but refresh failed. Refresh before submitting another review.'
            : error.message;
    } finally {
        busy = false;
        $('decision').disabled = false;
        $('refresh').disabled = false;
        selected();
    }
};

disposition();

load()
    .then(() => {
        $('message').textContent = 'Decision reviews ready.';
    })
    .catch(error => {
        $('message').textContent = error.message;
    });
</script>
</body>
</html>
"""


def completion_handler(base_factory):
    def make_handler(store):
        base = base_factory(store)
        initialize_reviews(store)

        class Handler(base):
            def do_GET(self):
                path = urlparse(self.path).path

                try:
                    if path == "/decision-reviews":
                        return self.respond(
                            200,
                            PAGE.encode("utf-8"),
                            "text/html; charset=utf-8",
                        )

                    if path == "/api/decision-reviews":
                        return self.respond(
                            200,
                            read_review_state(store),
                        )

                    return super().do_GET()

                except (ValueError, sqlite3.Error):
                    self.respond(
                        500,
                        {
                            "error": (
                                "Could not read decision reviews."
                            )
                        },
                    )

            def do_POST(self):
                if urlparse(self.path).path != "/api/decision-reviews":
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

                    result = save_review(store, data)

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
                                "Could not save this review."
                            )
                        },
                    )

                self.respond(200, result)

        return Handler

    return make_handler


def main():
    from nexus.farm_app import server, decision_report

    original = server.make_handler
    server.make_handler = completion_handler(original)

    print(
        "Decision reviews: /decision-reviews",
        flush=True,
    )

    try:
        decision_report.main()
    finally:
        server.make_handler = original


if __name__ == "__main__":
    main()