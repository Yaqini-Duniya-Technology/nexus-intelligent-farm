"""Append-only, hashed field ledgers shared by the evidence studio."""
import json
from datetime import datetime,timezone
from nexus.farm_app.operations_common import canonical,digest,positive,table_names

TABLES=('field_measurements','field_case_entries','field_notebook','field_evidence_links','saved_studio_views')


def initialize(store):
    with store.connect() as db:
        for table in TABLES:
            db.execute(f'''CREATE TABLE IF NOT EXISTS {table}(
                id INTEGER PRIMARY KEY,field_id INTEGER REFERENCES fields(id),
                observation_id INTEGER REFERENCES observations(id),root_id INTEGER REFERENCES {table}(id),
                parent_id INTEGER UNIQUE REFERENCES {table}(id),recorded_at TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,payload TEXT NOT NULL)''')
            db.execute(f'CREATE INDEX IF NOT EXISTS {table}_field ON {table}(field_id,id)')


def context(db,field_id,observation_id=None):
    positive(field_id,'field ID')
    field=db.execute('SELECT * FROM fields WHERE id=?',(field_id,)).fetchone()
    if field is None:raise ValueError('Field not found')
    if observation_id is not None:
        positive(observation_id,'observation ID')
        observation=db.execute('SELECT field_id FROM observations WHERE id=?',(observation_id,)).fetchone()
        if observation is None or observation[0]!=field_id:raise ValueError('Observation must belong to this field')
    return dict(field)


def read(db,table):
    if table not in TABLES:raise ValueError('Unsupported evidence ledger')
    if table not in table_names(db):return []
    rows=[];by_id={};children=set()
    for raw in db.execute(f'SELECT * FROM {table} ORDER BY id'):
        row=dict(raw)
        try:
            row['payload']=json.loads(row['payload']);p=row['payload']
            if digest(p)!=row['content_sha256'] or p.get('ledger_version')!='field-ledger-v1':raise ValueError()
            for key in ('field_id','observation_id','root_id','parent_id'):
                if p.get(key)!=row[key] or type(p.get(key)) is not type(row[key]):raise ValueError()
            positive(row['id'],'ledger entry ID')
            if table=='saved_studio_views':
                if row['field_id'] is not None or row['observation_id'] is not None:raise ValueError()
            else:positive(row['field_id'],'field ID')
            if row['observation_id'] is not None:positive(row['observation_id'],'observation ID')
            if not isinstance(p.get('data'),dict):raise ValueError()
            if table=='field_measurements':
                from nexus.farm_app.field_measurements import normalize
                from nexus.farm_app.operations_common import word
                normalized=normalize(p['data'])
                if normalized!={k:v for k,v in p['data'].items() if k!='reason'}:raise ValueError()
                word(p['data'].get('reason'),'measurement reason',1000)
            elif table in ('field_case_entries','field_notebook','saved_studio_views'):
                from nexus.farm_app.studio_cases import normalize
                kind={'field_case_entries':'case','field_notebook':'note','saved_studio_views':'view'}[table]
                if normalize(kind,p['data'])!=p['data']:raise ValueError()
            elif table=='field_evidence_links':
                d=p['data']
                if d.get('state') not in ('active','withdrawn') or d.get('kind') not in ('measurement','inspection','photo','adviser','decision_action'):raise ValueError()
                positive(d.get('target_id'),'target ID')
                if digest(d.get('record'))!=d.get('target_sha256'):raise ValueError()
                if d.get('field_id')!=row['field_id']:raise ValueError()
            parent=row['parent_id'];root=row['root_id']
            if parent is None:
                if root is not None:raise ValueError()
            else:
                if parent not in by_id or parent in children or root not in by_id:raise ValueError()
                old=by_id[parent]
                if (old['root_id'] or old['id'])!=root or old['field_id']!=row['field_id'] or old['observation_id']!=row['observation_id']:raise ValueError()
                children.add(parent)
            by_id[row['id']]=row;rows.append(row)
        except (ValueError,TypeError,KeyError) as error:
            raise ValueError(f'Invalid {table} hash, structure or correction chain at #{row["id"]}') from error
    for row in rows:row['latest']=row['id'] not in children
    return rows[::-1]


def append(db,table,field_id,observation_id,data,root_id=None,base_id=None):
    if table not in TABLES:raise ValueError('Unsupported evidence ledger')
    rows=read(db,table)
    if root_id is None:
        if base_id is not None:raise ValueError('New entries cannot have a base ID')
        payload={'ledger_version':'field-ledger-v1','field_id':field_id,'observation_id':observation_id,'root_id':None,'parent_id':None,'data':data}
        hashed=digest(payload)
        same=next((r for r in rows if r['content_sha256']==hashed),None)
        if same:return {'id':same['id'],'root_id':same['id'],'reused':True}
    else:
        positive(root_id,'root ID')
        chain=[r for r in rows if (r['root_id'] or r['id'])==root_id]
        if not chain:raise ValueError('Original entry not found')
        latest=chain[0]
        if latest['field_id']!=field_id or latest['observation_id']!=observation_id:raise ValueError('Entry context cannot be changed by a revision')
        if latest['payload']['data']==data:return {'id':latest['id'],'root_id':root_id,'reused':True}
        if type(base_id) is not int or base_id!=latest['id']:raise ValueError('Entry changed; refresh before saving')
        payload={'ledger_version':'field-ledger-v1','field_id':field_id,'observation_id':observation_id,'root_id':root_id,'parent_id':base_id,'data':data};hashed=digest(payload)
    cursor=db.execute(f'INSERT INTO {table}(field_id,observation_id,root_id,parent_id,recorded_at,content_sha256,payload) VALUES(?,?,?,?,?,?,?)',
                      (field_id,observation_id,root_id,base_id,datetime.now(timezone.utc).isoformat(),hashed,canonical(payload)))
    return {'id':cursor.lastrowid,'root_id':root_id or cursor.lastrowid,'reused':False}
