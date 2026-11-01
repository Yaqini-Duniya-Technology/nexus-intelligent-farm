"""Append-only, user-reported season context for existing observations."""
import hashlib
import json
from datetime import datetime, timezone

STAGES = ('unknown', 'planted', 'seedling', 'vegetative', 'flowering',
          'grain_filling', 'maturing', 'harvested', 'other')


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def initialize_observation_seasons(store):
    with store.connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS observation_season_history (
            id INTEGER PRIMARY KEY,
            observation_id INTEGER NOT NULL REFERENCES observations(id),
            season_id INTEGER REFERENCES crop_seasons(id),
            recorded_at TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            payload TEXT NOT NULL
        )''')
        db.execute('CREATE INDEX IF NOT EXISTS observation_season_history_lookup ON observation_season_history(observation_id,id)')


def state(store):
    with store.connect() as db:
        db.execute('BEGIN')
        observations = [dict(r) for r in db.execute('''
            SELECT o.*, f.name AS field_name, f.crop, farms.name AS farm_name
            FROM observations o JOIN fields f ON f.id=o.field_id
            JOIN farms ON farms.id=f.farm_id ORDER BY o.id DESC''')]
        seasons = [dict(r) for r in db.execute('SELECT * FROM crop_seasons ORDER BY id DESC')]
        history = [dict(r) for r in db.execute('SELECT * FROM observation_season_history ORDER BY id DESC')]
        for row in history:
            row['payload'] = json.loads(row['payload'])
            if digest(row['payload']) != row['content_sha256']:
                raise ValueError('Season context history hash mismatch')
        for season in seasons:
            season['selection_hash'] = digest(season)
        # Use only the raw observation columns in its selection hash.
        raw = {r['id']: dict(r) for r in db.execute('SELECT * FROM observations')}
        for observation in observations:
            observation['selection_hash'] = digest(raw[observation['id']])
    return {'observations': observations, 'seasons': seasons, 'history': history,
            'stages': list(STAGES)}


def positive(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError('Select a valid ' + label)
    return value


def save(store, data):
    observation_id = positive(data.get('observation_id'), 'observation')
    season_id = data.get('season_id')
    if season_id is not None:
        positive(season_id, 'season')
    base_id = data.get('base_id')
    if base_id is not None:
        positive(base_id, 'previous entry')
    stage = data.get('growth_stage')
    if stage not in STAGES:
        raise ValueError('Choose a reported growth stage')
    strings = {}
    for key, limit in [('reporter', 200), ('basis', 3000), ('reason', 3000)]:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError(f'Complete {key} (maximum {limit} characters)')
        strings[key] = value.strip()
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM observations WHERE id=?', (observation_id,)).fetchone()
        if row is None:
            raise ValueError('Observation not found')
        observation = dict(row)
        if digest(observation) != data.get('observation_hash'):
            raise ValueError('Observation changed; refresh before saving')
        season = None
        if season_id is not None:
            row = db.execute('SELECT * FROM crop_seasons WHERE id=?', (season_id,)).fetchone()
            if row is None:
                raise ValueError('Season not found')
            season = dict(row)
            if season['field_id'] != observation['field_id']:
                raise ValueError('Season must belong to the observation field')
            if digest(season) != data.get('season_hash'):
                raise ValueError('Season changed; refresh before saving')
        elif data.get('season_hash') is not None:
            raise ValueError('Unknown season must not include a season hash')
        payload = {'version': 'observation-season-context-v1',
                   'observation_id': observation_id, 'observation_at_capture': observation,
                   'season_id': season_id, 'season_at_capture': season,
                   'growth_stage': stage, **strings}
        raw = canonical(payload)
        row = db.execute('SELECT * FROM observation_season_history WHERE observation_id=? ORDER BY id DESC LIMIT 1', (observation_id,)).fetchone()
        if row:
            previous = json.loads(row['payload'])
            if digest(previous) != row['content_sha256']:
                raise ValueError('Previous season context hash mismatch')
            if previous == payload:
                return {'id': row['id'], 'reused': True}
        if (row['id'] if row else None) != base_id:
            raise ValueError('A newer context entry exists; refresh before saving')
        cursor = db.execute('''INSERT INTO observation_season_history
            (observation_id,season_id,recorded_at,content_sha256,payload) VALUES(?,?,?,?,?)''',
            (observation_id, season_id, datetime.now(timezone.utc).isoformat(), digest(payload), raw))
        return {'id': cursor.lastrowid, 'reused': False}


SEASON_LINK_HTML = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS observation seasons</title><style>
*{box-sizing:border-box}body{margin:0;background:#f1f5ee;color:#183c2c;font:16px system-ui}
header{padding:24px;background:#163f30;color:white}main{max-width:900px;margin:auto;padding:24px}
section{background:white;padding:22px;border-radius:14px;margin:18px 0}a{color:inherit;margin-right:16px}
label{display:block;margin-top:16px}input,select,textarea,button{width:100%;padding:12px;font:inherit;margin-top:6px}
button{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere}article{border-top:1px solid #ccd8ce;padding:16px 0}
</style><header><small>LOCAL PILOT · CROP CONTEXT</small><h1>Observation crop seasons</h1>
<nav><a href="/">Workspace</a><a href="/seasons">Crop seasons</a><a href="/overview">Dashboard</a><a href="/season-overview">Field season overview</a></nav></header>
<main><p>Link an observation to a season only when you have established the connection.
Growth stage describes the plants at the observation time. Select Unknown when uncertain.</p>
<p>Entries preserve the season details available when saved. Later season edits do not rewrite them.
This context does not change recommendations, complete tasks or update earlier saved review bundles.</p>
<p id="message" role="status">Loading…</p><button id="refresh">Refresh records</button>
<section><form id="form"><label>Observation<select id="observation" required></select></label>
<p id="note"></p><label>Crop season<select id="season"></select></label><p id="season-info"></p>
<label>Reported growth stage at observation<select id="stage"></select></label>
<label>Your name / role<input id="reporter" maxlength="200" required></label>
<label>Evidence or basis for the season and growth stage<textarea id="basis" maxlength="3000" required></textarea></label>
<label>Reason for this entry or correction<textarea id="reason" maxlength="3000" required></textarea></label>
<button id="save">Save season context</button></form></section>
<section><h2>Saved context history</h2><p>Newest entry first. Earlier entries remain available.</p><div id="history"></div></section></main>
<script>
const $=id=>document.getElementById(id);let state;
function node(tag,value){const e=document.createElement(tag);e.textContent=value;return e}
function selected(){return state.observations.find(o=>String(o.id)===$('observation').value)}
function seasonInfo(){const s=state.seasons.find(s=>String(s.id)===$('season').value);$('season-info').textContent=s?`Planting date (planned or actual): ${s.planting_date}. Expected harvest: ${s.expected_harvest_date}. These dates alone do not establish growth stage.`:'Season linkage remains unknown.'}
function render(){const o=selected();$('note').textContent=o?`${o.note} / Observed: ${o.observed_at||o.created}`:'';
$('season').replaceChildren(new Option('Unknown / no established season link',''));
for(const s of state.seasons.filter(s=>o&&s.field_id===o.field_id))$('season').add(new Option(`#${s.id} · ${s.name} · ${s.crop}`,s.id));
seasonInfo();const h=$('history');h.replaceChildren();
const entries=state.history.filter(e=>o&&e.observation_id===o.id);
if(!entries.length)h.append(node('p','No season context saved for this observation.'));
for(const e of entries){const a=node('article','');a.append(node('h3',`Entry #${e.id} · ${e.recorded_at}`),node('pre',JSON.stringify(e.payload,null,2)));h.append(a)}
$('save').disabled=!o;$('basis').value='';$('reason').value='';$('stage').value='unknown';}
async function load(){const r=await fetch('/api/observation-seasons');const body=await r.json();if(!r.ok)throw Error(body.error||'Could not load records');state=body;
const old=$('observation').value;$('observation').replaceChildren(new Option('Select an observation…',''));
for(const o of state.observations)$('observation').add(new Option(`#${o.id} · ${o.farm_name} / ${o.field_name}`,o.id));
$('observation').value=old;$('stage').replaceChildren(...state.stages.map(s=>new Option(s.replaceAll('_',' '),s)));render();}
$('observation').onchange=render;$('season').onchange=seasonInfo;
$('refresh').onclick=()=>load().then(()=>$('message').textContent='Records refreshed.').catch(e=>$('message').textContent=e.message);
$('form').onsubmit=async e=>{e.preventDefault();const o=selected();if(!o)return;
const season=state.seasons.find(s=>String(s.id)===$('season').value);const latest=state.history.find(h=>h.observation_id===o.id);
const data={observation_id:o.id,observation_hash:o.selection_hash,season_id:season?season.id:null,season_hash:season?season.selection_hash:null,
base_id:latest?latest.id:null,growth_stage:$('stage').value,reporter:$('reporter').value,basis:$('basis').value,reason:$('reason').value};
$('save').disabled=true;try{const r=await fetch('/api/observation-seasons',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const b=await r.json();if(!r.ok)throw Error(b.error||'Save failed');
$('message').textContent=`Entry #${b.id} ${b.reused?'reused':'saved'}.`;try{await load()}catch(error){$('message').textContent+=` Saved successfully; refresh failed: ${error.message}`}}
catch(error){$('message').textContent=error.message}finally{$('save').disabled=!selected()}};
load().then(()=>$('message').textContent='Season context ready.').catch(e=>$('message').textContent=e.message);
</script></html>'''
