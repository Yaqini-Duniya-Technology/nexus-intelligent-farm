import argparse
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from nexus.farm_app.audit import initialize_audit
from nexus.farm_app.confirm_voice_review import confirm_review
from nexus.farm_app.import_voice_response import parse_json
from nexus.farm_app.store import FarmStore
from nexus.farm_app.voice_response_review import initialize, records


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS reviewed voice confirmation</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#f1f5ee;color:#183c2c;font:16px system-ui}
header{background:#163f30;color:white;padding:24px}
main{max-width:900px;margin:auto;padding:20px}
section{background:white;padding:22px;border-radius:14px;margin:18px 0}
label{display:block;margin:16px 0 6px}
input,select,button{width:100%;padding:12px;font:inherit;
border:1px solid #b8c8ba;border-radius:8px}
button{background:#1d5c40;color:white;margin-top:16px;cursor:pointer}
button:disabled{opacity:.5;cursor:not-allowed}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef3ed;padding:16px}
a{color:inherit}
#message{padding:14px;background:#fff1c6}
.check{display:flex;gap:10px;align-items:flex-start}
.check input{width:auto;margin-top:5px}
article{border-top:1px solid #ccc;padding:12px 0}
</style>
</head>
<body>
<header>
<small>LOCAL PILOT · REVIEWED VOICE CONFIRMATION</small>
<h1>NEXUS Voice confirmation</h1>
<a href="http://127.0.0.1:8080/">Workspace</a> ·
<a href="http://127.0.0.1:8083/">Human extraction review</a>
</header>
<main>
<p>Review a saved human extraction and its frozen transcript before
creating an observation and human-review task for the selected field.
Synthetic and human test recordings cannot be converted.</p>
<p id="message" role="status" aria-live="polite">Loading saved reviews...</p>

<section>
<button id="refresh" type="button">Refresh reviews and links</button>
<label for="review">Saved human review</label>
<select id="review"></select>
</section>

<div id="details" hidden>
<section>
<h2>Reviewed recording</h2>
<p id="source"></p>
<p id="eligibility"></p>
<h3>Frozen corrected Hausa transcript</h3>
<p id="transcript"></p>
<h3>Human-reviewed extraction</h3>
<pre id="extraction"></pre>
<p id="reviewer"></p>
<p id="notes"></p>
</section>

<section>
<h2>Confirm an actual field observation</h2>
<form id="confirmation">
<label for="field">Field</label>
<select id="field" required></select>

<label for="condition">Field condition</label>
<select id="condition">
<option value="unknown">Unknown</option>
<option value="stable">Stable</option>
<option value="worsening">Worsening</option>
</select>

<label for="observed">Observed at
(local time; blank means submission time)</label>
<input id="observed" type="datetime-local">

<label class="check">
<input id="confirmed" type="checkbox" required>
<span>I reviewed the displayed transcript and extraction and confirm
that this actual farmer recording describes an observation for the
selected field.</span>
</label>
<button id="save">Confirm &amp; create observation</button>
</form>
<p>The corrected Hausa transcript becomes the observation text.
The extraction and model provenance are retained with the confirmation.
Possible causes remain unconfirmed.</p>
</section>
</div>

<section>
<h2>Saved reviewed voice observation links</h2>
<div id="links"></div>
</section>
<p>No diagnosis or equipment action is performed. Recording source and
reviewer identity are user-reported. Hashes do not authenticate a model run.</p>
<p>N-ATLaS is an initiative of the Federal Ministry of Communications,
Innovation and Digital Economy, and powered by Awarri Technologies.</p>
</main>

<script>
const $=id=>document.getElementById(id);
let state={responses:[],reviews:[],fields:[],links:[],old_links:[]};
let selected=null;
let busy=false;

function node(tag,text){
 const element=document.createElement(tag);
 element.textContent=text;
 return element;
}
function message(text){$('message').textContent=text}
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
function eligibility(row){
 const payload=row.payload;
 if(payload.source!=='farmer')
  return 'Test recording: cannot create a farm observation.';
 const link=state.links.find(x=>x.draft_id===payload.draft_id);
 if(link)
  return `Already saved as observation #${link.observation_id}, task #${link.task_id}.`;
 const old=state.old_links.find(x=>x.draft_id===payload.draft_id);
 if(old)
  return `Already saved through earlier voice confirmation as observation #${old.observation_id}.`;
 const latest=state.reviews.find(
  x=>x.response_record_id===row.response_record_id
 );
 if(latest && latest.id!==row.id)
  return 'A newer human review exists. Select the latest review.';
 return '';
}
function render(){
 selected=state.reviews.find(x=>String(x.id)===$('review').value);
 $('details').hidden=!selected;
 $('confirmation').reset();
 if(!selected)return;

 const response=state.responses.find(
  x=>x.id===selected.response_record_id
 );
 const payload=selected.payload;
 const reason=eligibility(selected);
 $('source').textContent=
  `Review #${selected.id} · Draft #${payload.draft_id} · `+
  `Version ${payload.draft_version} · Source: ${payload.source}`;
 $('eligibility').textContent=reason||
  'Farmer recording. The server will check the current draft and saved linkage before saving.';
 $('transcript').textContent=response?.request.input.corrected_transcript||'';
 $('extraction').textContent=JSON.stringify(payload.extraction,null,2);
 $('reviewer').textContent=
  `Reviewer as reported: ${payload.reviewer_as_reported}`;
 $('notes').textContent=payload.notes;

 for(const control of $('confirmation').elements)
  control.disabled=busy||Boolean(reason)||!response;
}
function renderLinks(){
 $('links').replaceChildren();
 if(!state.links.length){
  $('links').append(node('p','No reviewed voice observations confirmed yet.'));
  return;
 }
 for(const link of state.links){
  const article=node('article','');
  article.append(
   node('h3',`Review #${link.review_id} · Draft #${link.draft_id}`),
   node('p',`Observation #${link.observation_id} · Task #${link.task_id}`),
   node('p',`Confirmed: ${new Date(link.confirmed_at).toLocaleString()}`)
  );
  $('links').append(article);
 }
}
async function refresh(preferred){
 state=await request('/api/records');
 const old=preferred||$('review').value;
 $('review').replaceChildren();
 for(const row of state.reviews){
  const option=node('option',
   `Review #${row.id} · Draft #${row.payload.draft_id} · ${row.payload.source}`);
  option.value=String(row.id);
  $('review').append(option);
 }
 if(state.reviews.some(x=>String(x.id)===String(old)))
  $('review').value=String(old);

 $('field').replaceChildren();
 const placeholder=node('option','Select a field...');
 placeholder.value='';
 $('field').append(placeholder);
 for(const field of state.fields){
  const option=node('option',`${field.farm_name} / ${field.name} · ${field.crop}`);
  option.value=String(field.id);
  $('field').append(option);
 }
 render();
 renderLinks();
}
$('review').onchange=render;
$('refresh').onclick=async()=>{
 if(busy)return;
 try{await refresh();message('Records refreshed.')}
 catch(error){message(error.message)}
};
$('confirmation').onsubmit=async event=>{
 event.preventDefault();
 if(busy||!selected||eligibility(selected))return;

 const reviewId=selected.id;
 const localTime=$('observed').value;
 const data={
  review_id:reviewId,
  field_id:Number($('field').value),
  condition:$('condition').value,
  observed_at:localTime?new Date(localTime).toISOString():null,
  confirmed:$('confirmed').checked
 };
 busy=true;
 $('save').disabled=true;
 $('review').disabled=true;
 $('refresh').disabled=true;
 try{
  const result=await request('/api/confirm',data);
  const text=(result.reused?'Existing confirmation reused.':'Observation saved.')+
   ` Observation #${result.observation_id}; task #${result.task_id}.`;
  try{
   await refresh(String(reviewId));
   message(text);
  }catch(error){
   message(text+' Saved links could not refresh. Refresh records before retrying.');
  }
 }catch(error){
  message(error.message);
 }finally{
  busy=false;
  $('review').disabled=false;
  $('refresh').disabled=false;
  if(selected){
   const blocked=Boolean(eligibility(selected));
   for(const control of $('confirmation').elements)
    control.disabled=blocked;
  }
 }
};
refresh().then(()=>message('Reviewed voice confirmation ready.'))
.catch(error=>message(error.message));
</script>
</body>
</html>
"""


def table_exists(db, name):
    return db.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (name,),
    ).fetchone() is not None


def page_records(store):
    state = records(store.path)

    with store.connect() as db:
        state["fields"] = [
            dict(row)
            for row in db.execute(
                """
                SELECT fields.*, farms.name AS farm_name
                FROM fields
                JOIN farms ON farms.id = fields.farm_id
                ORDER BY fields.id
                """
            )
        ]

        state["links"] = []
        if table_exists(db, "natlas_voice_observation_links"):
            state["links"] = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT review_id, draft_id, observation_id,
                           task_id, confirmed_at
                    FROM natlas_voice_observation_links
                    ORDER BY id DESC
                    """
                )
            ]

        state["old_links"] = []
        if table_exists(db, "voice_observation_links"):
            state["old_links"] = [
                dict(row)
                for row in db.execute(
                    """
                    SELECT draft_id, observation_id
                    FROM voice_observation_links
                    """
                )
            ]

    return state


def save_confirmation(store, data):
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")

    observed_at = data.get("observed_at")
    if observed_at is not None:
        if not isinstance(observed_at, str):
            raise ValueError("Invalid observation timestamp")
        if not observed_at.strip() or len(observed_at) > 100:
            raise ValueError("Invalid observation timestamp")

    return confirm_review(
        store,
        data.get("review_id"),
        data.get("field_id"),
        data.get("confirmed"),
        data.get("condition", "unknown"),
        observed_at,
    )


def make_handler(store):
    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, body, html=False):
            raw = (
                body.encode("utf-8")
                if html
                else json.dumps(body).encode("utf-8")
            )
            self.send_response(status)
            self.send_header(
                "Content-Type",
                "text/html; charset=utf-8"
                if html
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
                    self.respond(200, page_records(store))
                else:
                    self.respond(404, {"error": "Not found"})
            except ValueError as error:
                self.respond(400, {"error": str(error)})
            except sqlite3.Error:
                self.respond(
                    500,
                    {"error": "Could not read saved records."},
                )

        def do_POST(self):
            if urlparse(self.path).path != "/api/confirm":
                self.respond(404, {"error": "Not found"})
                return

            expected_origin = (
                "http://" + self.headers.get("Host", "")
            )
            if self.headers.get("Origin") != expected_origin:
                self.respond(
                    403,
                    {"error": "Same-origin browser request required"},
                )
                return

            try:
                size = int(
                    self.headers.get("Content-Length", "0")
                )
                if not 0 < size <= 16384:
                    raise ValueError("Invalid request size")

                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError("Incomplete request")

                data = parse_json(raw.decode("utf-8"))
                result = save_confirmation(store, data)
                self.respond(200, result)

            except (ValueError, UnicodeError) as error:
                self.respond(400, {"error": str(error)})
            except sqlite3.Error:
                self.respond(
                    500,
                    {
                        "error": (
                            "Database error. Refresh saved links "
                            "and the workspace before retrying."
                        )
                    },
                )

    return Handler


def main():
    parser = argparse.ArgumentParser(
        description="NEXUS reviewed voice browser confirmation"
    )
    parser.add_argument(
        "--database",
        default="nexus-farm.sqlite3",
    )
    parser.add_argument("--port", type=int, default=8084)
    args = parser.parse_args()

    database = Path(args.database).expanduser().resolve()
    if not database.is_file():
        parser.exit(1, "Existing NEXUS database not found\n")

    try:
        store = FarmStore(str(database))
        initialize_audit(store)
        initialize(database)
    except (ValueError, sqlite3.Error) as error:
        parser.exit(1, f"Could not start confirmation page: {error}\n")

    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        make_handler(store),
    )

    print(
        f"Reviewed voice confirmation: http://127.0.0.1:{args.port}/",
        flush=True,
    )
    print("Press Ctrl+C to stop.", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()