"""Append-only answers to questions frozen in confirmed voice reviews."""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlparse


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def initialize(store):
    with store.connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS voice_clarification_answers (
            id INTEGER PRIMARY KEY,
            observation_id INTEGER NOT NULL REFERENCES observations(id),
            link_id INTEGER NOT NULL,
            recorded_at TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            payload TEXT NOT NULL
        )''')


def frozen_link(db, observation_id):
    row = db.execute('SELECT * FROM natlas_voice_observation_links '
                     'WHERE observation_id=?', (observation_id,)).fetchone()
    if row is None:
        raise ValueError('Select a confirmed voice observation')
    capture = json.loads(row['provenance'])
    review = capture['human_review']
    digest = hashlib.sha256(canonical(review).encode()).hexdigest()
    if digest != capture['human_review_sha256']:
        raise ValueError('Saved human review hash mismatch')
    questions = review['extraction']['clarification_questions']
    if (not isinstance(questions, list) or not 1 <= len(questions) <= 3
            or any(not isinstance(q, str) or not q.strip() for q in questions)):
        raise ValueError('Saved review has no usable clarification questions')
    return row, questions, digest


def state(store):
    with store.connect() as db:
        db.execute('BEGIN')
        observations = []
        if db.execute("SELECT 1 FROM sqlite_master WHERE name=?",
                      ('natlas_voice_observation_links',)).fetchone():
            rows = db.execute('''SELECT o.id, o.note, f.name AS field_name
                FROM observations o JOIN fields f ON f.id=o.field_id
                JOIN natlas_voice_observation_links l ON l.observation_id=o.id
                ORDER BY o.id DESC''').fetchall()
            for row in rows:
                item = dict(row)
                try:
                    link, questions, digest = frozen_link(db, row['id'])
                    item.update(questions=questions, review_hash=digest,
                                review_id=link['review_id'])
                except (ValueError, KeyError, TypeError):
                    item['error'] = 'Saved review could not be checked'
                observations.append(item)
        history = [dict(row) for row in db.execute(
            'SELECT * FROM voice_clarification_answers ORDER BY id DESC')]
        for entry in history:
            entry['payload'] = json.loads(entry['payload'])
        return {'observations': observations, 'history': history}


def save(store, data):
    if not isinstance(data, dict):
        raise ValueError('Expected a JSON object')
    observation_id = data.get('observation_id')
    if type(observation_id) is not int or observation_id < 1:
        raise ValueError('Select an observation')
    base_id = data.get('base_id')
    if type(base_id) is not int or base_id < 0:
        raise ValueError('Refresh the answer history')
    reporter = data.get('reporter')
    if not isinstance(reporter, str) or not reporter.strip() or len(reporter) > 200:
        raise ValueError('Enter your name / role (maximum 200 characters)')
    answers = data.get('answers')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        link, questions, digest = frozen_link(db, observation_id)
        if data.get('review_hash') != digest:
            raise ValueError('Saved question context changed; refresh')
        if (not isinstance(answers, list) or len(answers) != len(questions)
                or any(not isinstance(a, str) or not a.strip() or len(a) > 3000
                       for a in answers)):
            raise ValueError('Answer every question; enter Unknown where needed (maximum 3000 characters each)')
        payload = {'version': 'voice-clarification-answers-v1',
                   'observation_id': observation_id, 'review_id': link['review_id'],
                   'review_hash': digest, 'reporter': reporter.strip(),
                   'questions': questions, 'answers': [a.strip() for a in answers]}
        raw = canonical(payload)
        content_hash = hashlib.sha256(raw.encode()).hexdigest()
        latest = db.execute('SELECT id, content_sha256 FROM voice_clarification_answers '
                            'WHERE observation_id=? ORDER BY id DESC LIMIT 1',
                            (observation_id,)).fetchone()
        if latest and latest['content_sha256'] == content_hash:
            return {'id': latest['id'], 'reused': True}
        if base_id != (latest['id'] if latest else 0):
            raise ValueError('Another answer entry was saved; refresh before saving')
        cursor = db.execute('''INSERT INTO voice_clarification_answers
            (observation_id, link_id, recorded_at, content_sha256, payload)
            VALUES (?, ?, ?, ?, ?)''', (observation_id, link['id'],
            datetime.now(timezone.utc).isoformat(), content_hash, raw))
        return {'id': cursor.lastrowid, 'reused': False}


HTML = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS voice clarifications</title><style>
body{font:17px system-ui;background:#f3f6f1;color:#183c2c;margin:0}main{max-width:850px;margin:24px auto;padding:24px;background:white}label{display:block;margin:18px 0}select,input,textarea,button{font:inherit;padding:10px;box-sizing:border-box;max-width:100%}textarea,input,select{display:block;width:100%}article{border-top:1px solid #ddd;padding:16px 0}p{white-space:pre-wrap}button{cursor:pointer}a{color:#245b3c}
</style><main><small>LOCAL PILOT · VOICE CLARIFICATIONS</small>
<h1>NEXUS clarification answers</h1><nav><a href="/">Workspace</a> · <a href="/voice-pipeline">Voice pipeline</a></nav>
<p>Answer the questions saved with a confirmed voice observation. Use Unknown when you do not know. Names and answers are user-reported. Saving adds context; it does not diagnose a cause, change recommendations or complete a task.</p>
<p id="status" role="status">Loading…</p><button id="refresh">Refresh records</button>
<label>Confirmed voice observation<select id="observation"></select></label><p id="note"></p>
<form id="form"><label>Your name / role as reported<input id="reporter" maxlength="200" required></label><div id="questions"></div><button id="save">Save clarification answers</button></form>
<h2>Saved answer history</h2><p>Newest saved entry first. Earlier entries remain available. For a correction, save revised answers and explain the correction in the relevant answer. These entries do not rewrite the original voice capture.</p><div id="history"></div></main>
<script>
let records={observations:[],history:[]};let selected;let baseId=0;let busy=false;
const el=id=>document.getElementById(id);
function paragraph(parent,text){const p=document.createElement('p');p.textContent=text;parent.append(p)}
function render(){selected=records.observations.find(o=>o.id===Number(el('observation').value));el('questions').replaceChildren();el('history').replaceChildren();el('note').textContent=selected?selected.note:'';el('form').hidden=!selected||!!selected.error;if(!selected)return;if(selected.error){el('status').textContent=selected.error;return}const history=records.history.filter(h=>h.observation_id===selected.id);baseId=history.length?history[0].id:0;el('reporter').value='';selected.questions.forEach(q=>{const label=document.createElement('label');label.textContent=q;const t=document.createElement('textarea');t.required=true;t.maxLength=3000;t.rows=3;label.append(t);el('questions').append(label)});if(!history.length)paragraph(el('history'),'No answers saved yet.');history.forEach(h=>{const a=document.createElement('article');paragraph(a,'Entry #'+h.id+' · '+new Date(h.recorded_at).toLocaleString()+' · '+h.payload.reporter);h.payload.questions.forEach((q,i)=>{paragraph(a,q);paragraph(a,h.payload.answers[i])});el('history').append(a)})}
async function request(path,options){const r=await fetch(path,options);const d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d}
async function load(){const old=el('observation').value;records=await request('/api/voice-clarifications');el('observation').replaceChildren();records.observations.forEach(o=>{const option=document.createElement('option');option.value=o.id;option.textContent='#'+o.id+' · '+o.field_name;el('observation').append(option)});if(records.observations.some(o=>String(o.id)===old))el('observation').value=old;render();el('status').textContent=records.observations.length?'Clarifications ready.':'No confirmed voice observations available.'}
el('observation').onchange=render;el('refresh').onclick=()=>{if(!busy)load().catch(e=>el('status').textContent=e.message)};
el('form').onsubmit=async e=>{e.preventDefault();if(busy||!selected)return;busy=true;el('save').disabled=true;el('observation').disabled=true;try{const result=await request('/api/voice-clarifications',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({observation_id:selected.id,base_id:baseId,review_hash:selected.review_hash,reporter:el('reporter').value,answers:[...el('questions').querySelectorAll('textarea')].map(t=>t.value)})});await load();el('status').textContent=result.reused?'Identical answers reused.':'Answers saved. Task and original capture are unchanged.'}catch(err){el('status').textContent=err.message}finally{busy=false;el('save').disabled=false;el('observation').disabled=false}};
load().catch(e=>el('status').textContent=e.message);
</script></html>'''


def make_handler(base, store):
    initialize(store)
    class Handler(base):
        def do_GET(self):
            path = urlparse(self.path).path
            if path not in ('/voice-clarifications', '/api/voice-clarifications'):
                return super().do_GET()
            try:
                if path == '/voice-clarifications':
                    return self.respond(200, HTML.encode(), 'text/html; charset=utf-8')
                self.respond(200, state(store))
            except (ValueError, KeyError, TypeError, sqlite3.Error):
                self.respond(500, {'error': 'Could not load clarification records.'})

        def do_POST(self):
            if urlparse(self.path).path != '/api/voice-clarifications':
                return super().do_POST()
            if self.headers.get('Origin') != 'http://' + self.headers.get('Host', ''):
                return self.respond(403, {'error': 'Cross-origin request rejected'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 32768:
                    raise ValueError('Invalid request size')
                data = json.loads(self.rfile.read(size).decode('utf-8'))
                result = save(store, data)
            except (ValueError, UnicodeDecodeError) as error:
                return self.respond(400, {'error': str(error)})
            except (KeyError, TypeError, sqlite3.Error):
                return self.respond(500, {'error': 'Could not save clarification answers.'})
            self.respond(200, result)
    return Handler


def main():
    from nexus.farm_app import server, voice_workspace
    original_main = server.main

    def start_with_clarifications():
        original_handler = server.make_handler

        def combined(store):
            return make_handler(original_handler(store), store)

        server.make_handler = combined
        try:
            return original_main()
        finally:
            server.make_handler = original_handler

    server.main = start_with_clarifications
    try:
        print('Voice clarification answers: /voice-clarifications', flush=True)
        voice_workspace.main()
    finally:
        server.main = original_main


if __name__ == '__main__':
    main()
