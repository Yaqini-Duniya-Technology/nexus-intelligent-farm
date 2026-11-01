import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from nexus.farm_app.import_voice_response import (
    canonical,
    check_hash,
    digest,
    parse_json,
    validate_extraction,
    validate_response,
)


HTML = r"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS Voice extraction review</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#f1f5ee;color:#183c2c;font:16px system-ui}
header{background:#163f30;color:white;padding:24px}
main{max-width:950px;margin:auto;padding:20px}
section{background:white;padding:22px;border-radius:14px;margin:18px 0}
label{display:block;margin:16px 0 6px}
input,select,textarea,button{width:100%;padding:12px;font:inherit;
border:1px solid #b8c8ba;border-radius:8px}
textarea{min-height:100px}
button{background:#1d5c40;color:white;margin-top:16px;cursor:pointer}
button:disabled{opacity:.5}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef3ed;padding:16px}
article{border-top:1px solid #ccc;padding:16px 0}
a{color:inherit}
#message{padding:12px;background:#fff1c6}
.check{display:flex;gap:10px;align-items:flex-start}
.check input{width:auto;margin-top:5px}
</style>
<header>
<small>LOCAL PILOT · HUMAN EXTRACTION REVIEW</small>
<h1>NEXUS Voice</h1>
<a href="http://127.0.0.1:8080/">Workspace</a>
</header>
<main>
<p>Compare the model output with the frozen transcript.
Corrections are saved separately. This page creates no farm observation,
diagnosis or review task.</p>
<p id="message" role="status" aria-live="polite">Loading responses…</p>
<section>
<button id="refresh" type="button">Refresh saved records</button>
<label for="response">Imported response</label>
<select id="response"></select>
</section>
<div id="details" hidden>
<section>
<h2>Source transcript</h2>
<p id="provenance"></p>
<p id="transcript"></p>
<h2>Original model output</h2>
<pre id="original"></pre>
<p id="structure"></p>
</section>
<section>
<h2>Human-reviewed extraction</h2>
<form id="review">
<label for="reviewer">Your name / role as reported</label>
<input id="reviewer" required maxlength="300">
<label for="crop">Crop name in English (blank if unknown)</label>
<input id="crop" maxlength="200">
<label for="category">Category</label>
<select id="category">
<option value="general">General</option>
<option value="crop_health">Crop health</option>
<option value="water">Water</option>
<option value="pest">Pest observation</option>
<option value="operations">Operations</option>
</select>
<label for="symptoms">Reported symptoms — one per line</label>
<textarea id="symptoms"></textarea>
<label for="causes">Possible causes mentioned by the farmer — one per line</label>
<textarea id="causes"></textarea>
<label for="questions">Human-reviewed clarification questions — at most three</label>
<textarea id="questions"></textarea>
<label for="notes">Describe your corrections, or explain why none were needed</label>
<textarea id="notes" required maxlength="3000"></textarea>
<label class="check">
<input id="confirmed" type="checkbox" required>
<span>I compared this extraction with the displayed transcript.
Possible causes remain unconfirmed.</span>
</label>
<button id="save">Save human review</button>
</form>
<p>Saving another review retains earlier entries.
An identical submission reuses its existing record.</p>
</section>
<section>
<h2>Saved review history</h2>
<div id="history"></div>
</section>
</div>
<p>Recording source and reviewer identity are user-reported.
Hashes do not authenticate the model run. Synthetic and human test
recordings remain test material.</p>
<p>N-ATLaS is an initiative of the Federal Ministry of Communications,
Innovation and Digital Economy, and powered by Awarri Technologies.</p>
</main>
<script>
const $=id=>document.getElementById(id);
let state={responses:[],reviews:[]};
let selected=null;

function message(text){$('message').textContent=text}
function node(tag,text){
 const item=document.createElement(tag);
 item.textContent=text;
 return item;
}
async function request(path,data){
 const response=await fetch(path,data===undefined?{}:{
  method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify(data)
 });
 const body=await response.json();
 if(!response.ok)throw new Error(body.error||'Request failed');
 return body;
}
function lines(id){
 return $(id).value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
}
function render(){
 selected=state.responses.find(x=>String(x.id)===$('response').value);
 $('details').hidden=!selected;
 if(!selected)return;
 const payload=selected.payload;
 const input=selected.request.input;
 $('provenance').textContent=
  `Response #${selected.id} · Draft #${input.draft_id} · `+
  `Version ${input.draft_version} · Source: ${input.source}`;
 $('transcript').textContent=input.corrected_transcript;
 $('original').textContent=payload.raw_model_output;
 $('structure').textContent=
  `Structure check: ${payload.structure_check}. `+
  'Passing this check does not establish accuracy.';
 const previous=state.reviews.filter(x=>x.response_record_id===selected.id);
 const extraction=previous.length
  ?previous[0].payload.extraction
  :(payload.structure_check==='passed'?payload.parsed_extraction:null);
 $('review').reset();
 $('crop').value=extraction?.crop||'';
 $('category').value=extraction?.proposed_category||'general';
 $('symptoms').value=(extraction?.reported_symptoms||[]).join('\n');
 $('causes').value=(extraction?.possible_causes_mentioned_by_farmer||[]).join('\n');
 $('questions').value=(extraction?.clarification_questions||[]).join('\n');
 $('history').replaceChildren();
 if(!previous.length)$('history').append(node('p','No human review saved yet.'));
 for(const row of previous){
  const article=node('article','');
  article.append(
   node('h3',`Review #${row.id}`),
   node('p',row.payload.reviewer_as_reported),
   node('p',`Saved: ${new Date(row.recorded_at).toLocaleString()}`),
   node('p',row.payload.notes),
   node('pre',JSON.stringify(row.payload.extraction,null,2))
  );
  $('history').append(article);
 }
}
async function refresh(preferred){
 state=await request('/api/records');
 const old=preferred||$('response').value;
 $('response').replaceChildren();
 for(const row of state.responses){
  const option=node('option',`Response #${row.id} · ${row.payload.source}`);
  option.value=String(row.id);
  $('response').append(option);
 }
 if(state.responses.some(x=>String(x.id)===String(old)))
  $('response').value=String(old);
 render();
}
$('response').onchange=render;
$('refresh').onclick=async()=>{
 try{await refresh();message('Records refreshed.')}
 catch(error){message(error.message)}
};
$('review').onsubmit=async event=>{
 event.preventDefault();
 if(!selected)return;
 const id=selected.id;
 $('save').disabled=true;
 try{
  const result=await request('/api/reviews',{
   response_record_id:id,
   reviewer_as_reported:$('reviewer').value,
   notes:$('notes').value,
   confirmed:$('confirmed').checked,
   extraction:{
    crop:$('crop').value.trim()||null,
    proposed_category:$('category').value,
    reported_symptoms:lines('symptoms'),
    possible_causes_mentioned_by_farmer:lines('causes'),
    clarification_questions:lines('questions')
   }
  });
  await refresh(String(id));
  message(result.reused?'Existing human review reused.':'Human review saved.');
 }catch(error){message(error.message)}
 finally{$('save').disabled=false}
};
refresh().then(()=>message('Voice response reviews ready.'))
.catch(error=>message(error.message));
</script>
</html>"""


def connect(database):
    db = sqlite3.connect(str(database))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def initialize(database):
    with closing(connect(database)) as db:
        if not db.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name = 'natlas_voice_responses'
            """
        ).fetchone():
            raise ValueError("Import a voice response first")

        with db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS natlas_voice_response_reviews (
                    id INTEGER PRIMARY KEY,
                    response_record_id INTEGER NOT NULL
                        REFERENCES natlas_voice_responses(id),
                    content_sha256 TEXT NOT NULL UNIQUE,
                    recorded_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )


def checked_response(db, record_id):
    row = db.execute(
        "SELECT * FROM natlas_voice_responses WHERE id = ?",
        (record_id,),
    ).fetchone()
    if not row:
        raise ValueError("Select an existing response")

    payload = parse_json(row["payload"])
    validate_response(payload)

    if payload["content_sha256"] != row["content_sha256"]:
        raise ValueError("Stored response hash does not match")

    saved_request = db.execute(
        """
        SELECT * FROM natlas_voice_requests
        WHERE request_id = ?
        """,
        (row["request_id"],),
    ).fetchone()
    if not saved_request:
        raise ValueError("Supporting request is missing")

    request = parse_json(saved_request["payload"])
    check_hash(request)
    frozen = request["input"]

    if (
        request["request_id"] != row["request_id"]
        or payload["request_id"] != row["request_id"]
        or digest(frozen) != request["input_sha256"]
        or request["input_sha256"] != saved_request["input_sha256"]
        or frozen["draft_id"] != saved_request["draft_id"]
        or frozen["draft_version"] != saved_request["draft_version"]
    ):
        raise ValueError("Saved request consistency check failed")

    expected = {
        "request_content_sha256": request["content_sha256"],
        "input_sha256": request["input_sha256"],
        "draft_id": frozen["draft_id"],
        "draft_version": frozen["draft_version"],
        "source": frozen["source"],
        "model": request["model"],
        "model_revision": request["model_revision"],
    }
    for key, value in expected.items():
        if type(payload.get(key)) is not type(value) or payload[key] != value:
            raise ValueError(f"Request linkage failed: {key}")

    return row, payload, request


def records(database):
    with closing(connect(database)) as db:
        db.execute("BEGIN")
        responses = []
        for row in db.execute(
            "SELECT id FROM natlas_voice_responses ORDER BY id DESC"
        ).fetchall():
            stored, payload, request = checked_response(db, row["id"])
            responses.append({
                "id": stored["id"],
                "payload": payload,
                "request": request,
            })

        reviews = []
        for row in db.execute(
            "SELECT * FROM natlas_voice_response_reviews ORDER BY id DESC"
        ):
            payload = parse_json(row["payload"])
            if digest(payload) != row["content_sha256"]:
                raise ValueError("Saved human review hash check failed")
            reviews.append({
                "id": row["id"],
                "response_record_id": row["response_record_id"],
                "recorded_at": row["recorded_at"],
                "payload": payload,
            })
    return {"responses": responses, "reviews": reviews}


def save_review(database, data):
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")

    record_id = data.get("response_record_id")
    if isinstance(record_id, bool) or not isinstance(record_id, int) or record_id < 1:
        raise ValueError("Invalid response record ID")

    if data.get("confirmed") is not True:
        raise ValueError("Confirm that you compared the transcript")

    reviewer = data.get("reviewer_as_reported")
    notes = data.get("notes")
    for value, limit, label in (
        (reviewer, 300, "reviewer name / role"),
        (notes, 3000, "review notes"),
    ):
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError(f"Provide valid {label}")

    extraction = data.get("extraction")
    validate_extraction(extraction)

    with closing(connect(database)) as db:
        with db:
            db.execute("BEGIN IMMEDIATE")
            row, response, request = checked_response(db, record_id)

            payload = {
                "review_version": "natlas-voice-human-review-v1",
                "response_record_id": record_id,
                "response_content_sha256": row["content_sha256"],
                "request_id": response["request_id"],
                "input_sha256": response["input_sha256"],
                "draft_id": response["draft_id"],
                "draft_version": response["draft_version"],
                "source": request["input"]["source"],
                "reviewer_as_reported": reviewer.strip(),
                "notes": notes.strip(),
                "extraction": extraction,
                "transcript_compared": True,
                "farm_observation_saved": False,
            }
            content_hash = digest(payload)
            existing = db.execute(
                """
                SELECT id FROM natlas_voice_response_reviews
                WHERE content_sha256 = ?
                """,
                (content_hash,),
            ).fetchone()

            if existing:
                return {"id": existing["id"], "reused": True}

            cursor = db.execute(
                """
                INSERT INTO natlas_voice_response_reviews (
                    response_record_id, content_sha256,
                    recorded_at, payload
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    record_id,
                    content_hash,
                    datetime.now(timezone.utc).isoformat(),
                    canonical(payload),
                ),
            )
            return {"id": cursor.lastrowid, "reused": False}


def make_handler(database):
    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, body, html=False):
            raw = body.encode("utf-8") if html else json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header(
                "Content-Type",
                "text/html; charset=utf-8" if html
                else "application/json; charset=utf-8",
            )
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            try:
                path = urlparse(self.path).path
                if path == "/":
                    self.respond(200, HTML, html=True)
                elif path == "/api/records":
                    self.respond(200, records(database))
                else:
                    self.respond(404, {"error": "Not found"})
            except ValueError as error:
                self.respond(400, {"error": str(error)})
            except sqlite3.Error:
                self.respond(500, {"error": "Could not read saved records"})

        def do_POST(self):
            if urlparse(self.path).path != "/api/reviews":
                self.respond(404, {"error": "Not found"})
                return

            expected = "http://" + self.headers.get("Host", "")
            if self.headers.get("Origin") != expected:
                self.respond(403, {"error": "Same-origin browser request required"})
                return

            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 65536:
                    raise ValueError("Invalid request size")
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError("Incomplete request")
                data = parse_json(raw.decode("utf-8"))
                self.respond(200, save_review(database, data))
            except (ValueError, UnicodeError) as error:
                self.respond(400, {"error": str(error)})
            except sqlite3.Error:
                self.respond(500, {
                    "error": "Database error. Refresh saved reviews before retrying."
                })

    return Handler


def main():
    parser = argparse.ArgumentParser(description="NEXUS voice response human reviews")
    parser.add_argument("--database", default="nexus-farm.sqlite3")
    parser.add_argument("--port", type=int, default=8083)
    args = parser.parse_args()

    database = Path(args.database).expanduser().resolve()
    if not database.is_file():
        parser.exit(1, "Existing NEXUS database not found\n")

    try:
        initialize(database)
    except (ValueError, sqlite3.Error) as error:
        parser.exit(1, f"Could not start review page: {error}\n")

    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        make_handler(database),
    )
    print(f"Voice response reviews: http://127.0.0.1:{args.port}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()