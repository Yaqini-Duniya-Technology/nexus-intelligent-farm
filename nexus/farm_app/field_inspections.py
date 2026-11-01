"""Append-only, user-reported inspections. No field-wide or causal inference."""
import hashlib
import json
from datetime import datetime, timezone
from html import escape

VERSION = 'field-inspection-v1'
LIMITS = {'reporter': 200, 'area': 500, 'sampling_method': 1000,
          'observation_definition': 1000, 'findings': 3000, 'reason': 1000}
COUNTS = ('plants_checked', 'plants_affected', 'cobs_checked',
          'newly_forming_cobs', 'mature_small_cobs', 'uncertain_cobs')


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def positive(value):
    return type(value) is int and value > 0


def initialize(store):
    with store.connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS field_inspections (
            id INTEGER PRIMARY KEY,
            observation_id INTEGER NOT NULL REFERENCES observations(id),
            supersedes_id INTEGER REFERENCES field_inspections(id),
            recorded_at TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            payload TEXT NOT NULL)''')
        db.execute('CREATE INDEX IF NOT EXISTS field_inspections_observation ON field_inspections(observation_id, id)')


def validate_data(data):
    if not positive(data.get('observation_id')) or (data.get('supersedes_id') is not None and not positive(data['supersedes_id'])):
        raise ValueError('Invalid inspection record reference')
    if data.get('version') != VERSION:
        raise ValueError('Unsupported inspection version')
    for key, limit in LIMITS.items():
        value = data.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError(f'Complete {key.replace("_", " ")} (maximum {limit} characters)')
    try:
        when = datetime.fromisoformat(data['performed_at'])
        if when.tzinfo is None:
            raise ValueError()
        if when > datetime.now(timezone.utc):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ValueError('Inspection time must include a timezone and cannot be in the future') from None
    for key in COUNTS:
        value = data.get(key)
        if value is not None and (type(value) is not int or value < 0 or value > 1000000):
            raise ValueError('Counts must be whole numbers from 0 to 1000000, or blank for unknown')
    checked, affected = data.get('plants_checked'), data.get('plants_affected')
    if affected is not None and (checked is None or affected > checked):
        raise ValueError('Affected plants require a checked count and cannot exceed it')
    groups = [data.get(key) for key in COUNTS[3:]]
    if any(v is not None for v in groups):
        if data.get('cobs_checked') is None or any(v is None for v in groups):
            raise ValueError('To group cobs, record cobs checked and all three group counts (including zero)')
        if sum(groups) != data['cobs_checked']:
            raise ValueError('Cob maturity group counts must sum to cobs checked')
    frozen = data.get('observation_at_capture')
    if not isinstance(frozen, dict) or frozen.get('id') != data.get('observation_id'):
        raise ValueError('Invalid frozen observation')
    # An inspection can precede submission, but not the observation it follows.
    try:
        observed = datetime.fromisoformat(frozen.get('observed_at') or frozen['created'])
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        if when < observed:
            raise ValueError('Inspection cannot predate this observation')
    except (KeyError, TypeError):
        raise ValueError('Invalid original observation time') from None


def validate_entry(entry, observation):
    data = entry.get('payload')
    if not isinstance(data, dict) or digest(data) != entry.get('content_sha256'):
        raise ValueError('Inspection content hash is invalid')
    validate_data(data)
    if (not positive(entry.get('id')) or entry.get('observation_id') != observation.get('id')
            or data.get('observation_id') != observation.get('id')
            or data['observation_at_capture'].get('field_id') != observation.get('field_id')
            or entry.get('supersedes_id') != data.get('supersedes_id')):
        raise ValueError('Inspection observation or correction reference is inconsistent')


def capture_history(db, tables, observation):
    if 'field_inspections' not in tables:
        return None
    rows = [dict(row) for row in db.execute(
        'SELECT * FROM field_inspections WHERE observation_id=? ORDER BY id DESC', (observation['id'],))]
    seen = {}
    corrected = set()
    for row in reversed(rows):
        row['payload'] = json.loads(row['payload'])
        validate_entry(row, observation)
        prior = row.get('supersedes_id')
        if prior is not None and (prior not in seen or prior >= row['id'] or prior in corrected):
            raise ValueError('Inspection correction target is missing or out of order')
        if prior is not None:
            corrected.add(prior)
        seen[row['id']] = row
    return rows


def state(store):
    with store.connect() as db:
        db.execute('BEGIN')
        observations = [dict(r) for r in db.execute('''SELECT o.*, f.name AS field_name
            FROM observations o JOIN fields f ON f.id=o.field_id ORDER BY o.id DESC''')]
        raw = {r['id']: dict(r) for r in db.execute('SELECT * FROM observations')}
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        history = []
        for observation in observations:
            observation['selection_hash'] = digest(raw[observation['id']])
            history.extend(capture_history(db, tables, raw[observation['id']]) or [])
        return {'observations': observations, 'history': sorted(history, key=lambda r: r['id'], reverse=True)}


def save(store, data):
    oid = data.get('observation_id')
    if not positive(oid):
        raise ValueError('Select an observation')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM observations WHERE id=?', (oid,)).fetchone()
        if row is None:
            raise ValueError('Observation not found')
        observation = dict(row)
        if data.get('observation_hash') != digest(observation):
            raise ValueError('Observation changed; refresh before saving')
        history = capture_history(db, {'field_inspections'}, observation)
        target = data.get('supersedes_id')
        if target is not None and (not positive(target) or not any(r['id'] == target for r in history)):
            raise ValueError('Select a correction target from this observation')
        payload = {'version': VERSION, 'observation_id': oid,
                   'observation_at_capture': observation, 'supersedes_id': target,
                   'performed_at': data.get('performed_at')}
        for key in (*LIMITS, *COUNTS):
            value = data.get(key)
            payload[key] = value.strip() if isinstance(value, str) and key in LIMITS else value
        validate_data(payload)
        payload['performed_at'] = datetime.fromisoformat(payload['performed_at']).astimezone(timezone.utc).isoformat()
        hash_value = digest(payload)
        # A repeated submission is safe even after the first response was lost.
        identical = next((r for r in history if r['content_sha256'] == hash_value), None)
        if identical:
            return {'id': identical['id'], 'reused': True}
        latest = history[0]['id'] if history else None
        base = data.get('base_id')
        if (base is not None and not positive(base)) or base != latest:
            raise ValueError('Inspection history changed; refresh before saving')
        if target is not None and any(r['supersedes_id'] == target for r in history):
            raise ValueError('This entry already has a correction; correct the newer entry instead')
        cursor = db.execute('''INSERT INTO field_inspections
            (observation_id,supersedes_id,recorded_at,content_sha256,payload) VALUES (?,?,?,?,?)''',
            (oid, target, datetime.now(timezone.utc).isoformat(), hash_value, canonical(payload)))
        return {'id': cursor.lastrowid, 'reused': False}


def assess(payload):
    rows = payload.get('field_inspections')
    if rows is None:
        return {'status': 'not_captured', 'entries': None, 'findings': ['Structured inspections were not available in this capture.']}
    if not isinstance(rows, list):
        return {'status': 'invalid', 'entries': None, 'findings': ['Invalid inspection history.']}
    try:
        ids = set()
        corrected = set()
        for row in sorted(rows, key=lambda r: r['id']):
            validate_entry(row, payload.get('observation') or {})
            if row['id'] in ids or (row['supersedes_id'] is not None and (row['supersedes_id'] not in ids or row['supersedes_id'] in corrected)):
                raise ValueError('Invalid inspection correction chain')
            if row['supersedes_id'] is not None:
                corrected.add(row['supersedes_id'])
            ids.add(row['id'])
    except (ValueError, KeyError, TypeError) as error:
        return {'status': 'invalid', 'entries': len(rows), 'findings': [str(error)]}
    findings = ['Counts describe the inspected sample only. Repeated inspections are not independent trials.'] if rows else ['No structured inspection was saved at capture.']
    return {'status': 'recorded' if rows else 'no_entry', 'entries': len(rows), 'findings': findings}


def render_history(payload, title='Structured inspections at capture'):
    t = lambda value: escape(str(value if value is not None else 'Unknown'))
    result = '<section><h2>' + t(title) + '</h2>'
    assessment = assess(payload)
    result += ''.join('<p>' + t(v) + '</p>' for v in assessment['findings'])
    if assessment['status'] != 'recorded':
        return result + '</section>'
    corrected = {r['supersedes_id'] for r in payload['field_inspections'] if r['supersedes_id'] is not None}
    for entry in sorted(payload['field_inspections'], key=lambda r: r['id'], reverse=True):
        data = entry['payload']
        result += '<article><h3>Inspection #' + t(entry['id']) + (' — earlier corrected entry' if entry['id'] in corrected else '') + '</h3><dl>'
        pairs = [('Recorded (UTC)', entry['recorded_at']), ('Corrects inspection', entry['supersedes_id'])]
        pairs += [(key.replace('_', ' ').capitalize(), data.get(key)) for key in ('performed_at', *LIMITS, *COUNTS)]
        result += ''.join('<dt>' + t(k) + '</dt><dd style="white-space:pre-wrap">' + t(v) + '</dd>' for k,v in pairs)
        result += '</dl></article>'
    return result + '<p>Plant counts and cob counts use different units. No field-wide prevalence, diagnosis or outcome is inferred.</p></section>'


HTML = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS field inspections</title><style>body{font:17px system-ui;background:#f1f5ee;color:#183c2c;max-width:950px;margin:30px auto;padding:16px}section{background:white;padding:22px;margin:20px 0;border-radius:12px}label{display:block;margin:14px 0}input,select,textarea,button{display:block;font:inherit;padding:10px;max-width:100%;width:100%}button{cursor:pointer}dd{margin:4px 0}nav a{margin-right:16px}</style>
<h1>NEXUS field inspections</h1><nav><a href="/">Workspace</a><a href="/overview">Dashboard</a><a href="/review-bundles">Saved bundles</a></nav>
<p>Record work actually performed. Blank counts mean unknown; enter zero only when none were observed. Counts describe your inspected sample. Saving does not complete tasks or create decision actions.</p>
<p id="message" role="status"></p><button id="refresh">Refresh records</button><section><form id="form">
<label>Observation<select id="observation" required></select></label><p id="note"></p>
<label>New inspection or correction<select id="correction"></select></label>
<label>Performed at (your local time)<input id="performed_at" type="datetime-local" required></label>
<div id="fields"></div><h2>Plant counts</h2><p>Count plants meeting the observation definition above.</p><div id="plants"></div>
<h2>Cob counts and maturity groups</h2><p>Optional. If grouping cobs, fill all three groups, including zero. Each cob belongs to one group. Their sum must equal cobs checked. Do not copy plant counts into cob counts.</p><div id="cobs"></div>
<button>Save inspection</button></form></section><h2>Saved inspection history</h2><div id="history"></div>
<script>
let records,selected,latest;const el=id=>document.getElementById(id);
const labels={reporter:'Your name / role',area:'Area inspected (e.g. south side)',sampling_method:'How were plants selected?',observation_definition:'What counted as an affected plant?',findings:'Findings and limitations',reason:'Reason for this entry or correction',plants_checked:'Plants checked',plants_affected:'Affected plants',cobs_checked:'Cobs checked',newly_forming_cobs:'Newly forming cobs',mature_small_cobs:'Mature cobs that remain small',uncertain_cobs:'Cobs of uncertain maturity'};
for(const [key,label] of Object.entries(labels)){let l=document.createElement('label');l.textContent=label;let i=document.createElement(key in {reporter:1,area:1}? 'input':key.endsWith('cobs')||key.startsWith('plants_')||key==='cobs_checked'?'input':'textarea');i.id=key;
if(key.startsWith('plants_')||key.includes('cobs')){i.type='number';i.min=0;i.max=1000000;i.step=1;}else{i.required=true;i.maxLength={reporter:200,area:500,sampling_method:1000,observation_definition:1000,findings:3000,reason:1000}[key];}
l.append(i);el(key.startsWith('plants_')?'plants':key.includes('cobs')?'cobs':'fields').append(l);}
async function load(){let r=await fetch('/api/field-inspections');records=await r.json();if(!r.ok)throw Error(records.error||'Load failed');let keep=el('observation').value;el('observation').replaceChildren();for(const o of records.observations){el('observation').add(new Option('#'+o.id+' · '+o.field_name,o.id));}if(keep&&records.observations.some(o=>String(o.id)===keep))el('observation').value=keep;show();}
function show(){selected=records.observations.find(o=>o.id===Number(el('observation').value));el('note').textContent=selected?selected.note:'No observations saved';let rows=records.history.filter(r=>r.observation_id===selected?.id);latest=rows[0]?.id??null;el('correction').replaceChildren(new Option('New inspection',''));for(const r of rows)el('correction').add(new Option('Correction to inspection #'+r.id,r.id));el('history').replaceChildren();for(const r of rows){let a=document.createElement('section'),h=document.createElement('h3');h.textContent='Inspection #'+r.id+(rows.some(x=>x.supersedes_id===r.id)?' — earlier corrected entry':'');a.append(h);let p=document.createElement('pre');p.style.whiteSpace='pre-wrap';p.textContent=JSON.stringify(r.payload,null,2);a.append(p);el('history').append(a);}}
el('observation').onchange=()=>{let oid=el('observation').value;el('form').reset();el('observation').value=oid;show();};el('refresh').onclick=()=>load().catch(e=>el('message').textContent=e.message);
el('form').onsubmit=async e=>{e.preventDefault();try{if(!selected)throw Error('Select an observation');let data={observation_id:selected.id,observation_hash:selected.selection_hash,base_id:latest,supersedes_id:el('correction').value?Number(el('correction').value):null,performed_at:new Date(el('performed_at').value).toISOString()};for(const key of Object.keys(labels)){let v=el(key).value;data[key]=key.startsWith('plants_')||key.includes('cobs')?(v===''?null:Number(v)):v;}let r=await fetch('/api/field-inspections',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});let answer=await r.json();if(!r.ok)throw Error(answer.error||'Save failed');await load();el('form').reset();el('observation').value=String(data.observation_id);show();el('message').textContent='Inspection #'+answer.id+(answer.reused?' reused.':' saved.');}catch(error){el('message').textContent=error.message;}};
load().catch(e=>el('message').textContent=e.message);
</script></html>'''
