"""Explicit source references; hashes check consistency, not source authenticity."""
import hashlib
import json
from nexus.farm_app import studio_ledger as ledger
from nexus.farm_app.operations_common import positive,word,digest,readonly,table_names

KINDS=('measurement','inspection','photo','adviser','decision_action')


def target(db,kind,rid):
    positive(rid,'source record ID')
    if kind not in KINDS:raise ValueError('Choose a supported evidence type')
    current=True
    if kind=='measurement':
        row=next((r for r in ledger.read(db,'field_measurements') if r['id']==rid),None)
        if row is None:raise ValueError('Measurement not found')
        if row['payload']['data']['source']=='test_measurement':raise ValueError('Test measurements cannot be attached as farm evidence')
        fid=row['field_id'];source=row['payload']['data']['source'];current=row.pop('latest')
    else:
        table={'inspection':'field_inspections','photo':'observation_photos','adviser':'adviser_reviews','decision_action':'decision_events'}[kind]
        if table not in table_names(db):raise ValueError('Evidence table unavailable')
        raw=db.execute(f'SELECT * FROM {table} WHERE id=?',(rid,)).fetchone()
        if raw is None:raise ValueError('Evidence record not found')
        row=dict(raw)
        if kind=='decision_action':
            if row['kind']!='action':raise ValueError('Select a decision action, not an outcome')
            observed=db.execute('''SELECT b.observation_id FROM human_decisions d JOIN decision_review_bundles b ON b.id=d.bundle_id WHERE d.id=?''',(row['decision_id'],)).fetchone()
            if observed is None:raise ValueError('Decision context unavailable')
            oid=observed[0]
        else:oid=row['observation_id']
        observation=db.execute('SELECT * FROM observations WHERE id=?',(oid,)).fetchone()
        if observation is None:raise ValueError('Source observation unavailable')
        fid=observation['field_id'];source='user_reported_'+kind
        if kind=='inspection':
            from nexus.farm_app.field_inspections import capture_history
            checked=capture_history(db,table_names(db),dict(observation));row=next(r for r in checked if r['id']==rid)
            current=not any(r['supersedes_id']==rid for r in checked)
        if kind=='photo':
            source=row.get('source_kind','unknown')
            if source not in ('farmer_photo','adviser_photo'):raise ValueError('Only a farmer/adviser-labelled photo may be linked as farm evidence')
            if hashlib.sha256(row['image_data']).hexdigest()!=row['sha256']:raise ValueError('Photo bytes do not match the saved hash')
            row.pop('image_data')
    return {'kind':kind,'target_id':rid,'field_id':fid,'source_label':source,'record':row,'target_sha256':digest(row),'current':current}


def save(store,data):
    fid,oid=data.get('field_id'),data.get('observation_id')
    positive(oid,'observation ID')
    state=data.get('state')
    if state not in ('active','withdrawn'):raise ValueError('Choose active or withdrawn')
    reporter=word(data.get('reporter'),'reporter',200);reason=word(data.get('reason'),'relationship or withdrawal reason',1000)
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE');ledger.context(db,fid,oid)
        if state=='withdrawn':
            root=data.get('root_id')
            row=next((r for r in ledger.read(db,'field_evidence_links') if (r['root_id'] or r['id'])==root),None)
            if row is None:raise ValueError('Select an existing link to withdraw')
            content={**row['payload']['data'],'state':state,'reporter':reporter,'reason':reason}
        else:
            content={**target(db,data.get('kind'),data.get('target_id')),'state':state,'reporter':reporter,'reason':reason}
            if content['field_id']!=fid:raise ValueError('Source evidence belongs to a different field')
            if data.get('target_sha256')!=content['target_sha256']:raise ValueError('Source changed or was not previewed; review the source again')
        return ledger.append(db,'field_evidence_links',fid,oid,content,data.get('root_id'),data.get('base_id'))


def assessed(db,rows):
    for row in rows:
        data=row['payload']['data'];row['reference_status']='withdrawn' if data['state']=='withdrawn' else 'unavailable'
        if data['state']=='withdrawn':continue
        try:
            current=target(db,data['kind'],data['target_id'])
            row['reference_status']='changed' if current['target_sha256']!=data['target_sha256'] or current['field_id']!=row['field_id'] else 'superseded' if not current['current'] else 'matches'
        except (ValueError,KeyError):row['reference_status']='unavailable'
    return rows


def entries(database,filters=None):
    from nexus.farm_app.operations_records import filter_id
    filters=filters or {};fid=filter_id(filters.get('field_id'));oid=filter_id(filters.get('observation_id'))
    with readonly(database) as db:
        rows=ledger.read(db,'field_evidence_links')
        selected=[r for r in rows if (filters.get('history')=='true' or r['latest']) and (fid is None or r['field_id']==fid) and (oid is None or r['observation_id']==oid)]
        return assessed(db,selected)


def capture(db,tables,observation):
    if 'field_evidence_links' not in tables:return None
    rows=ledger.read(db,'field_evidence_links')
    return assessed(db,[r for r in rows if r['observation_id']==observation['id']])
