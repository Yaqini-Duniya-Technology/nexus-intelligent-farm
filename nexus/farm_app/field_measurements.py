"""Numeric field records with explicit units, source labels and reviewed CSV staging."""
import csv
import io
import json
from datetime import datetime,timedelta,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path
from nexus.farm_app.operations_common import canonical,digest,word,instant,readonly
from nexus.farm_app import studio_ledger as ledger

# Broad entry bounds, not agronomic thresholds or advice.
METRICS={'soil_moisture':('%','0','100'),'rainfall':('mm','0','10000'),
         'air_temperature':('C','-100','100'),'soil_temperature':('C','-100','100'),
         'cob_length':('cm','0','10000'),'plant_height':('cm','0','10000'),
         'soil_ph':('pH','0','14'),'sample_weight':('kg','0','1000000000')}
SOURCES=('farmer_measurement','adviser_measurement','sensor_reading','test_measurement')
COLUMNS=('metric','unit','value','observed_at','area','method','instrument','reporter','notes','unknown_reason')


def initialize(store):
    ledger.initialize(store)
    with store.connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS measurement_imports(
            id INTEGER PRIMARY KEY,created_at TEXT NOT NULL,content_sha256 TEXT NOT NULL UNIQUE,
            payload TEXT NOT NULL,committed_at TEXT,reviewer TEXT,result_json TEXT)''')


def normalize(data):
    metric=data.get('metric')
    if not isinstance(metric,str) or metric not in METRICS:raise ValueError('Select a supported metric')
    unit,minimum,maximum=METRICS[metric]
    if data.get('unit')!=unit:raise ValueError('Unit must be '+unit+' for '+metric)
    source=data.get('source')
    if source not in SOURCES:raise ValueError('Choose a measurement source')
    when=instant(data.get('observed_at'))
    if when>datetime.now(timezone.utc):raise ValueError('Measurement cannot be in the future')
    result={'metric':metric,'unit':unit,'source':source,'observed_at':when.isoformat()}
    for key,limit in [('area',500),('method',1000),('instrument',500),('reporter',200),('notes',3000)]:result[key]=word(data.get(key),key,limit)
    value=data.get('value');unknown=data.get('unknown_reason','')
    if value is None or value=='':
        result['value']=None;result['unknown_reason']=word(unknown,'reason value is unknown',1000)
    else:
        if isinstance(value,bool) or not isinstance(value,(str,int,float)):raise ValueError('Enter a numeric value or leave blank for unknown')
        try:
            v=Decimal(str(value))
            if not v.is_finite() or v<Decimal(minimum) or v>Decimal(maximum) or v.as_tuple().exponent<-6:raise ValueError()
            result['value']='0' if v==0 else format(v.normalize(),'f')
        except (ValueError,InvalidOperation):raise ValueError('Value is outside the entry bounds or has more than six decimal places') from None
        result['unknown_reason']=''
    return result


def save_in_transaction(db,data):
    fid,oid=data.get('field_id'),data.get('observation_id');ledger.context(db,fid,oid)
    normalized=normalize(data)
    root=data.get('root_id')
    if root is not None:
        old=next((r for r in ledger.read(db,'field_measurements') if (r['root_id'] or r['id'])==root),None)
        if old is None:raise ValueError('Measurement not found')
        if (old['payload']['data']['source']=='test_measurement')!=(normalized['source']=='test_measurement'):
            raise ValueError('A test measurement cannot be relabelled as farm evidence')
    normalized['reason']=word(data.get('reason'),'entry or correction reason',1000)
    return ledger.append(db,'field_measurements',fid,oid,normalized,root,data.get('base_id'))


def save(store,data):
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE');return save_in_transaction(db,data)


def readings(database,filters=None):
    filters=filters or {}
    from nexus.farm_app.operations_records import filter_id
    fid=filter_id(filters.get('field_id'));metric=filters.get('metric','');source=filters.get('source','')
    if metric and metric not in METRICS:raise ValueError('Unknown metric')
    if source and source not in SOURCES:raise ValueError('Unknown measurement source')
    with readonly(database) as db:
        rows=ledger.read(db,'field_measurements');result=[]
        for row in rows:
            d=row['payload']['data']
            if filters.get('history')!='true' and not row['latest']:continue
            if fid is not None and row['field_id']!=fid:continue
            if metric and d['metric']!=metric:continue
            if source and d['source']!=source:continue
            if filters.get('include_tests')!='true' and d['source']=='test_measurement':continue
            result.append(row)
        return result


def template():
    output=io.StringIO(newline='');csv.writer(output).writerow(COLUMNS)
    return output.getvalue().encode('utf-8-sig')


def preview(store,data):
    raw=data.get('csv_text')
    if not isinstance(raw,str) or not raw or len(raw.encode('utf-8'))>200000:raise ValueError('CSV must contain text and be at most 200 KB')
    field_id=data.get('field_id');oid=data.get('observation_id');source=data.get('source')
    label=word(data.get('filename','measurement-upload.csv'),'filename',200)
    reader=csv.DictReader(io.StringIO(raw.lstrip('\ufeff'),newline=''))
    if reader.fieldnames is None or len(reader.fieldnames)!=len(set(reader.fieldnames)) or set(reader.fieldnames)!=set(COLUMNS):
        raise ValueError('Use the measurement CSV template with exactly its named columns')
    normalized=[];errors=[]
    for number,row in enumerate(reader,2):
        if number>501:raise ValueError('CSV import is limited to 500 rows')
        if None in row or any(v is None for v in row.values()):errors.append({'row':number,'error':'Incorrect column count'});continue
        try:normalized.append(normalize({**row,'source':source}))
        except ValueError as error:errors.append({'row':number,'error':str(error)})
    if not normalized and not errors:raise ValueError('CSV contains no data rows')
    if errors:return {'preview_id':None,'errors':errors,'valid_rows':len(normalized),'can_commit':False}
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE');field=ledger.context(db,field_id,oid)
        payload={'import_version':'measurement-import-v1','field_id':field_id,'observation_id':oid,
                 'field_sha256':digest(field),'filename':label,'input_sha256':__import__('hashlib').sha256(raw.encode()).hexdigest(),
                 'rows':normalized,'source':source}
        hashed=digest(payload)
        row=db.execute('SELECT id,created_at,committed_at FROM measurement_imports WHERE content_sha256=?',(hashed,)).fetchone()
        if row is not None and row['committed_at'] is None and instant(row['created_at'])<datetime.now(timezone.utc)-timedelta(days=1):
            payload['replaces_expired_preview']=row['id'];payload['renewed_at']=datetime.now(timezone.utc).isoformat()
            hashed=digest(payload);row=None
        if row is None:
            cursor=db.execute('INSERT INTO measurement_imports(created_at,content_sha256,payload) VALUES(?,?,?)',
                              (datetime.now(timezone.utc).isoformat(),hashed,canonical(payload)))
            pid=cursor.lastrowid
        else:pid=row['id']
        existing={digest({'field_id':r['field_id'],'observation_id':r['observation_id'],
                          'data':{k:v for k,v in r['payload']['data'].items() if k!='reason'}}) for r in ledger.read(db,'field_measurements')}
        seen=set();duplicates=0
        for row in normalized:
            fingerprint=digest({'field_id':field_id,'observation_id':oid,'data':row})
            if fingerprint in seen or fingerprint in existing:duplicates+=1
            seen.add(fingerprint)
        return {'preview_id':pid,'preview_sha256':hashed,'errors':[],'can_commit':True,
                'rows':normalized,'duplicate_rows':duplicates,'new_rows':len(normalized)-duplicates,
                'source':source,'notice':'Preview only. No measurement or observation was saved.'}


def commit(store,data):
    from nexus.farm_app.operations_common import positive
    pid=positive(data.get('preview_id'),'preview ID')
    reviewer=word(data.get('reviewer'),'reviewer',200)
    if data.get('confirm') is not True:raise ValueError('Review the preview and explicitly confirm import')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT * FROM measurement_imports WHERE id=?',(pid,)).fetchone()
        if row is None:raise ValueError('Preview not found')
        payload=json.loads(row['payload'])
        if digest(payload)!=row['content_sha256'] or data.get('preview_sha256')!=row['content_sha256']:raise ValueError('Preview hash mismatch')
        if row['committed_at']:
            return {**json.loads(row['result_json']),'reused':True}
        if instant(row['created_at'])<datetime.now(timezone.utc)-timedelta(days=1):raise ValueError('Preview expired; upload again for a new reviewed preview')
        field=ledger.context(db,payload['field_id'],payload['observation_id'])
        if digest(field)!=payload['field_sha256']:raise ValueError('Field context changed; review a new preview')
        results=[]
        existing={digest({'field_id':r['field_id'],'observation_id':r['observation_id'],
                          'data':{k:v for k,v in r['payload']['data'].items() if k!='reason'}}):r['id']
                  for r in ledger.read(db,'field_measurements')}
        for reading in payload['rows']:
            fingerprint=digest({'field_id':payload['field_id'],'observation_id':payload['observation_id'],'data':reading})
            if fingerprint in existing:
                results.append({'id':existing[fingerprint],'reused':True})
            else:
                saved=save_in_transaction(db,{**reading,'field_id':payload['field_id'],'observation_id':payload['observation_id'],
                                             'reason':'Reviewed CSV import'})
                results.append(saved);existing[fingerprint]=saved['id']
        result={'preview_id':pid,'record_ids':[r['id'] for r in results],
                'inserted':sum(not r['reused'] for r in results),'reused_rows':sum(r['reused'] for r in results),'reused':False}
        db.execute('UPDATE measurement_imports SET committed_at=?,reviewer=?,result_json=? WHERE id=?',
                   (datetime.now(timezone.utc).isoformat(),reviewer,canonical(result),pid))
        return result
