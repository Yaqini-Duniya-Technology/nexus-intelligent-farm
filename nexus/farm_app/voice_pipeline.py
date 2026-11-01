import argparse
import json
import sqlite3
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from nexus.farm_app.voice_response_review import records


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS Voice pipeline</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#f1f5ee;color:#183c2c;font:16px system-ui}
header{padding:24px;background:#163f30;color:white}
main{max-width:1050px;margin:auto;padding:20px}
article{background:white;padding:22px;border-radius:14px;margin:20px 0}
button{padding:12px 20px;background:#1d5c40;color:white;
border:0;border-radius:8px;font:inherit;cursor:pointer}
a{color:inherit}
nav{display:flex;flex-wrap:wrap;gap:14px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef3ed;padding:14px}
#message{padding:14px;background:#fff1c6}
li{margin:10px 0}
</style>
</head>
<body>
<header>
<small>LOCAL PILOT · VOICE PIPELINE STATUS</small>
<h1>NEXUS Voice pipeline</h1>
<nav>
<a href="http://127.0.0.1:8080/voice">Saved voice drafts</a>
<a href="http://127.0.0.1:8083/">Human extraction review</a>
<a href="http://127.0.0.1:8084/">Reviewed confirmation</a>
<a href="http://127.0.0.1:8080/">Workspace</a>
</nav>
</header>
<main>
<p>Follow each saved recording through the voice workflow.
This page reads records; it does not run a model or save farm observations.</p>
<button id="refresh">Refresh pipeline</button>
<p id="message" role="status" aria-live="polite">Loading...</p>
<div id="drafts"></div>
<p>Recording sources and reviewer identities are user-reported.
Test recordings remain test material. Record linkage and hash checks
do not establish agricultural accuracy or authenticate a model run.</p>
<p>N-ATLaS is an initiative of the Federal Ministry of Communications,
Innovation and Digital Economy, and powered by Awarri Technologies.</p>
</main>
<script>
const $=id=>document.getElementById(id);
function node(tag,text){
 const item=document.createElement(tag);
 item.textContent=text;
 return item;
}
async function refresh(){
 $('refresh').disabled=true;
 try{
  const response=await fetch('/api/pipeline');
  const data=await response.json();
  if(!response.ok)throw new Error(data.error||'Could not load pipeline');
  $('drafts').replaceChildren();

  for(const draft of data.drafts){
   const article=node('article','');
   article.append(
    node('h2',`Draft #${draft.id} · ${draft.source}`),
    node('p',`Current saved version: ${draft.version}`),
    node('p',draft.corrected_transcript)
   );
   if(draft.source!=='farmer'){
    article.append(node('p',
     'Test material: cannot create a farm observation.'));
   }
   const requests=data.requests.filter(x=>x.draft_id===draft.id);
   if(!requests.length){
    article.append(node('p','No N-ATLaS request exported for this draft.'));
   }
   for(const request of requests){
    const section=node('section','');
    section.append(
     node('h3',`Request: ${request.request_id}`),
     node('p',`Exported draft version: ${request.draft_version}`),
     node('p',request.matches_current_draft
      ?'Request input matches the current saved draft.'
      :'Historical request: the current draft differs from its frozen input.')
    );
    const responses=data.responses.filter(
     x=>x.payload.request_id===request.request_id);
    if(!responses.length){
     section.append(node('p','Awaiting an imported model response.'));
    }
    for(const response of responses){
     const list=node('ul','');
     list.append(node('li',
      `Response #${response.id}: structure ${response.payload.structure_check}.`));
     const reviews=data.reviews.filter(
      x=>x.response_record_id===response.id);
     list.append(node('li',reviews.length
      ?`Human reviews saved: ${reviews.length}. Latest saved entry: #${reviews[0].id}.`
      :'Awaiting human extraction review.'));
     const link=data.links.find(x=>x.draft_id===draft.id);
     const old=data.old_links.find(x=>x.draft_id===draft.id);
     let status;
     if(link){
      status=`Confirmed through review #${link.review_id}: `+
       `observation #${link.observation_id}, task #${link.task_id}.`;
     }else if(old){
      status=`Earlier voice confirmation created observation #${old.observation_id}.`;
     }else if(draft.source!=='farmer'){
      status='Confirmation blocked: test recording.';
     }else if(!request.matches_current_draft){
      status='Export the current draft and review its new response before confirmation.';
     }else if(!reviews.length){
      status='Save a human review before confirmation.';
     }else{
      status='No confirmation saved. Open reviewed confirmation to check the field and save.';
     }
     list.append(node('li',status));
     section.append(list);
    }
    article.append(section);
   }
   $('drafts').append(article);
  }
  if(!data.drafts.length){
   $('drafts').append(node('p','No voice drafts saved.'));
  }
  $('message').textContent=
   `Loaded ${data.drafts.length} drafts. Checked: ${new Date().toLocaleString()}.`;
 }catch(error){
  $('message').textContent=error.message;
 }finally{
  $('refresh').disabled=false;
 }
}
$('refresh').onclick=refresh;
refresh();
</script>
</body>
</html>
"""


def read_rows(db, table, columns):
    exists = db.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table,),
    ).fetchone()

    if not exists:
        return []

    return [
        dict(row)
        for row in db.execute(
            f"SELECT {columns} FROM {table} ORDER BY id DESC"
        )
    ]


def pipeline(database):
    # Reuse the existing response and human-review hash checks.
    state = records(database)

    uri = Path(database).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")

        drafts = read_rows(
            db,
            "voice_drafts",
            """
            id, version, source, corrected_transcript,
            original_transcript, audio_sha256,
            model, revision, updated_at
            """,
        )
        requests = read_rows(
            db,
            "natlas_voice_requests",
            "id, request_id, draft_id, draft_version, payload",
        )
        links = read_rows(
            db,
            "natlas_voice_observation_links",
            "id, review_id, draft_id, observation_id, task_id",
        )
        old_links = read_rows(
            db,
            "voice_observation_links",
            "id, draft_id, observation_id",
        )

    by_id = {draft["id"]: draft for draft in drafts}

    for request in requests:
        payload = json.loads(request.pop("payload"))
        frozen = payload["input"]
        draft = by_id.get(request["draft_id"])

        mapping = {
            "draft_version": "version",
            "source": "source",
            "corrected_transcript": "corrected_transcript",
            "original_transcript": "original_transcript",
            "audio_sha256": "audio_sha256",
            "asr_model": "model",
            "asr_revision": "revision",
            "draft_updated_at": "updated_at",
        }
        request["matches_current_draft"] = (
            draft is not None
            and all(
                frozen.get(key) == draft[column]
                for key, column in mapping.items()
            )
        )

    return {
        **state,
        "drafts": drafts,
        "requests": requests,
        "links": links,
        "old_links": old_links,
    }


def make_handler(database):
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
                elif path == "/api/pipeline":
                    self.respond(200, pipeline(database))
                else:
                    self.respond(404, {"error": "Not found"})
            except (ValueError, KeyError, TypeError):
                self.respond(
                    400,
                    {"error": "Saved voice records could not be checked."},
                )
            except sqlite3.Error:
                self.respond(
                    500,
                    {"error": "Could not read the local database."},
                )

    return Handler


def main():
    parser = argparse.ArgumentParser(
        description="NEXUS Voice pipeline status"
    )
    parser.add_argument("--port", type=int, default=8085)
    parser.add_argument("--database", default="nexus-farm.sqlite3")
    args = parser.parse_args()

    database = Path(args.database).expanduser().resolve()
    if not database.is_file():
        parser.exit(1, "Existing NEXUS database not found\n")

    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        make_handler(database),
    )
    print(
        f"Voice pipeline: http://127.0.0.1:{args.port}/",
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