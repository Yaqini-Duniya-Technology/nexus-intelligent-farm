"""Append-only field resource planning. No equipment, payments or messages are executed."""
import json
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
from nexus.farm_app.operations_common import canonical,digest,positive,word,day,instant,LAGOS,readonly
from nexus.farm_app.resource_catalog import SPECS,EXAMPLES
from nexus.farm_app import resource_logistics as logistics,produce_market as market


def initialize(store):
    with store.connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS resource_entries(
          id INTEGER PRIMARY KEY,root_id INTEGER REFERENCES resource_entries(id),
          previous_id INTEGER UNIQUE REFERENCES resource_entries(id),kind TEXT NOT NULL,
          field_id INTEGER NOT NULL REFERENCES fields(id),recorded_at TEXT NOT NULL,
          content_sha256 TEXT NOT NULL UNIQUE,payload TEXT NOT NULL)''')
        db.execute('CREATE INDEX IF NOT EXISTS resource_roots ON resource_entries(root_id,id)')
        db.execute('CREATE INDEX IF NOT EXISTS resource_fields ON resource_entries(field_id,kind,id)')


def decimal(value,label,places=3,signed=False):
    try:
        if isinstance(value,bool) or not isinstance(value,(str,int,float)):raise ValueError()
        v=Decimal(str(value))
        if not v.is_finite() or abs(v)>Decimal('1000000000') or (not signed and v<0) or v!=v.quantize(Decimal(1).scaleb(-places)):raise ValueError()
        return format(v,'f')
    except (InvalidOperation,ValueError):raise ValueError(f'{label}: enter a finite {"signed" if signed else "nonnegative"} number with at most {places} decimals') from None


def normalize(kind,data):
    if kind not in SPECS:raise ValueError('Choose a resource workflow')
    values={}
    for field in SPECS[kind]['fields']:
        key=field['key'];value=data.get(key);label=field['label'];typ=field['type']
        if value is None or value=='':
            if field['required']:raise ValueError('Complete '+label)
            values[key]=None;continue
        if typ=='select':
            if value not in field['options']:raise ValueError('Choose a valid '+label)
            values[key]=value
        elif typ=='reference':values[key]=positive(value,label)
        elif typ=='date':values[key]=day(value).isoformat()
        elif typ=='datetime':
            parsed=instant(value)
            if parsed>datetime.now(timezone.utc):raise ValueError(label+' cannot be in the future')
            values[key]=parsed.isoformat()
        elif typ in ('quantity','signed_quantity','money'):
            values[key]=decimal(value,label,2 if typ=='money' else 3,typ=='signed_quantity')
        else:values[key]=word(value,label,3000 if typ=='textarea' else 300)
    if kind=='movement':
        qty=Decimal(values['quantity'])
        if qty==0 or (values['direction']!='adjustment' and qty<0):raise ValueError('Receipts and issues need a positive quantity; adjustments need a nonzero signed quantity')
    if kind=='reservation' and Decimal(values['quantity'])<=0:raise ValueError('Reserve a positive quantity')
    if kind=='budget' and values['end_date']<values['start_date']:raise ValueError('Budget end date cannot predate its start')
    if kind in ('maintenance','visit'):
        if values['status']=='completed' and not values['performed_at']:raise ValueError('Record the actual completion time')
        if values['status']!='completed' and values['performed_at']:raise ValueError('Use actual completion time only with completed status')
    if kind=='contact' and values['permission']!='granted' and values['contact'].casefold()!='unknown':raise ValueError('Record permission before storing contact details, or enter Unknown')
    return market.normalize(kind,logistics.normalize(kind,values))


def load(db):
    entries=[];latest={};by_id={}
    for raw in db.execute('SELECT * FROM resource_entries ORDER BY id'):
        row=dict(raw)
        try:p=json.loads(row['payload'])
        except (ValueError,TypeError):raise ValueError('Resource payload is corrupt') from None
        if not isinstance(p,dict) or digest(p)!=row['content_sha256']:raise ValueError('Resource content hash mismatch')
        root=row['root_id'] or row['id'];prev=row['previous_id']
        if (p.get('version')!='field-resource-v1' or p.get('kind')!=row['kind'] or p.get('field_id')!=row['field_id'] or p.get('root_id')!=row['root_id'] or p.get('previous_id')!=prev):raise ValueError('Resource reference mismatch')
        if row['kind'] not in SPECS or p.get('source') not in ('actual','test'):raise ValueError('Invalid resource source or type')
        if prev is None:
            if row['root_id'] is not None:raise ValueError('Invalid resource root')
        else:
            old=latest.get(root)
            if old is None or old['id']!=prev or p.get('previous_sha256')!=old['content_sha256'] or old['kind']!=row['kind'] or old['field_id']!=row['field_id'] or old['payload']['source']!=p['source']:raise ValueError('Resource history chain mismatch')
        if not isinstance(p.get('values'),dict):raise ValueError('Invalid resource fields')
        row['payload']=p;row['record_id']=root;logistics.check_captures(row);market.check_captures(row);entries.append(row);latest[root]=row;by_id[row['id']]=row
    return entries,latest


def validate_links(current):
    for row in current.values():
        kind=row['kind'];p=row['payload'];values=p['values']
        for field in SPECS[kind]['fields']:
            if field['type']!='reference':continue
            if values[field['key']] is None and not field['required']:continue
            if field['ref'] in logistics.EXTERNAL:continue
            target=current.get(values[field['key']])
            if target is None or (field['ref']!='resource' and target['kind']!=field['ref']) or target['field_id']!=row['field_id'] or target['payload']['source']!=p['source']:raise ValueError('Related record must have the expected type, field and actual/test source')
    logistics.validate(current)
    market.calculate(current)
    supplies={};budgets={};labor={}
    for root,row in current.items():
        v=row['payload']['values']
        if row['kind']=='supply':supplies[root]={'supply_id':root,'name':v['name'],'field_id':row['field_id'],'source':row['payload']['source'],'unit':v['unit'],'balance':Decimal(0),'reserved':Decimal(0),'minimum':v['minimum']}
        if row['kind']=='budget':budgets[root]={'budget_id':root,'name':v['name'],'field_id':row['field_id'],'source':row['payload']['source'],'ceiling_ngn':Decimal(v['ceiling_ngn']),'estimates_ngn':Decimal(0),'committed_ngn':Decimal(0)}
    for root,row in current.items():
        kind=row['kind'];v=row['payload']['values']
        if kind=='movement':
            qty=Decimal(v['quantity']);supplies[v['supply_id']]['balance']+=-qty if v['direction']=='issue' else qty
        if kind=='reservation' and v['status']=='active':supplies[v['supply_id']]['reserved']+=Decimal(v['quantity'])
        if kind=='budget_line' and v['status']!='cancelled':budgets[v['budget_id']]['estimates_ngn' if v['status']=='estimate' else 'committed_ngn']+=Decimal(v['amount_ngn'])
        if kind=='labor':labor[root]=None if v['hourly_ngn'] is None else (Decimal(v['hours'])*Decimal(v['hourly_ngn'])).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    for s in supplies.values():
        s['available']=s['balance']-s['reserved']
        if s['balance']<0 or s['available']<0:raise ValueError('Recorded stock cannot be negative or below active reservations. Correct quantities or release reservations first.')
        s['low_stock']=None if s['minimum'] is None else s['available']<=Decimal(s['minimum'])
    for b in budgets.values():b['unallocated_ngn']=b['ceiling_ngn']-b['estimates_ngn']-b['committed_ngn']
    def strings(items):return [{k:format(v,'f') if isinstance(v,Decimal) else v for k,v in item.items()} for item in items]
    return {'supplies':strings(supplies.values()),'budgets':strings(budgets.values()),'labor_costs':{str(k):None if v is None else format(v,'f') for k,v in labor.items()}}


def save(store,data):
    kind=data.get('kind');fid=positive(data.get('field_id'),'field ID');source=data.get('source')
    if source not in ('actual','test'):raise ValueError('Choose actual or test source')
    actor=word(data.get('reporter'),'reporter / role',200);reason=word(data.get('reason'),'entry / correction reason')
    if not isinstance(data.get('values'),dict):raise ValueError('Expected a fields object')
    values=normalize(kind,data['values'])
    root=data.get('record_id');base=data.get('base_id')
    if root is not None:positive(root,'record ID');positive(base,'base entry ID')
    elif base is not None:raise ValueError('Unexpected base ID')
    request_hash=digest({'kind':kind,'field_id':fid,'source':source,'reporter':actor,'reason':reason,'values':values,'record_id':root,'base_id':base})
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT id FROM fields WHERE id=?',(fid,)).fetchone() is None:raise ValueError('Field not found')
        entries,current=load(db)
        same=next((e for e in entries if e['payload'].get('request_sha256')==request_hash),None)
        if same:return {'id':same['id'],'record_id':same['record_id'],'reused':True}
        old=current.get(root) if root else None
        if root is not None:
            if old is None or old['id']!=base:raise ValueError('Record changed; refresh before saving a correction')
            if old['kind']!=kind or old['field_id']!=fid or old['payload']['source']!=source:raise ValueError('Type, field and source are frozen; create a separate record')
            if kind=='supply' and old['payload']['values']['unit']!=values['unit']:
                if any(e['payload']['values'].get('supply_id')==root for e in entries):raise ValueError('Stock unit is frozen after linked entries; create a new supply item')
        market.guard(current,kind,values,old)
        captures=logistics.freeze(db,current,kind,fid,source,values)|market.freeze(db,current,kind,fid,source,values)
        payload={'captures':captures,'version':'field-resource-v1','kind':kind,'field_id':fid,'source':source,'root_id':root,'previous_id':base,'previous_sha256':old['content_sha256'] if old else None,'reporter':actor,'reason':reason,'values':values,'request_sha256':request_hash}
        cursor=db.execute('INSERT INTO resource_entries(root_id,previous_id,kind,field_id,recorded_at,content_sha256,payload) VALUES(?,?,?,?,?,?,?)',(root,base,kind,fid,datetime.now(timezone.utc).isoformat(),digest(payload),canonical(payload)))
        _,projected=load(db);validate_links(projected);market.commitment_guard(projected,kind,values,old)
        return {'id':cursor.lastrowid,'record_id':root or cursor.lastrowid,'reused':False}


def state(store,query=None):
    query=query or {};kind=query.get('kind','');q=query.get('q','').strip().casefold()
    if kind and kind not in SPECS:raise ValueError('Unknown resource workflow')
    if len(q)>200:raise ValueError('Search is limited to 200 characters')
    fid=query.get('field_id');fid=positive(int(fid),'field ID') if fid not in (None,'') else None
    history=query.get('history')=='true';tests=query.get('include_tests')=='true';status=query.get('status','')
    with readonly(store.path) as db:
        entries,current=load(db);totals=validate_links(current)
        fields=[dict(r) for r in db.execute('SELECT id,name,crop FROM fields ORDER BY id')]
        external_options=logistics.options(db)
        logistics_report=logistics.report(db,current)
        market_report=market.report(db,current)
    def eligible(e):return (not fid or e['field_id']==fid) and (tests or e['payload']['source']=='actual')
    scope=[e for e in current.values() if eligible(e)]
    rows=[e for e in (entries if history else current.values()) if eligible(e) and (not kind or e['kind']==kind) and (not status or e['payload']['values'].get('status',e['payload']['values'].get('condition'))==status) and (not q or q in canonical(e['payload']).casefold())]
    reference_scope=list(scope)
    area=query.get('area','')
    if area=='market':rows=[e for e in rows if e['kind'] in market.SPECS];scope=[e for e in scope if e['kind'] in market.SPECS]
    rows.sort(key=lambda e:e['id'],reverse=True)
    totals['supplies']=[s for s in totals['supplies'] if (not fid or s['field_id']==fid) and (tests or s['source']=='actual')]
    totals['budgets']=[s for s in totals['budgets'] if (not fid or s['field_id']==fid) and (tests or s['source']=='actual')]
    totals['labor_costs']={str(e['record_id']):totals['labor_costs'][str(e['record_id'])] for e in scope if e['kind']=='labor'}
    totals['labor_summary']={'hours':format(sum((Decimal(e['payload']['values']['hours']) for e in scope if e['kind']=='labor'),Decimal(0)),'f'),'known_cost_ngn':format(sum((Decimal(v) for v in totals['labor_costs'].values() if v is not None),Decimal(0)),'f'),'unknown_rate_count':sum(v is None for v in totals['labor_costs'].values())}
    today=datetime.now(timezone.utc).astimezone(LAGOS).date().isoformat()
    due=[]
    for e in scope:
        v=e['payload']['values'];date=v.get('due_date')
        if date and v.get('status') not in ('completed','cancelled','released','fulfilled','closed'):
            due.append({'record_id':e['record_id'],'kind':e['kind'],'field_id':e['field_id'],'name':v.get('name',v.get('purpose','Review reservation')),'due_date':date,'timing':'overdue' if date<today else 'today' if date==today else 'upcoming','source':e['payload']['source']})
    due.sort(key=lambda e:(e['due_date'],e['record_id']))
    logistics_report={k:[r for r in values if (not fid or r['field_id']==fid) and (tests or r['source']=='actual')] for k,values in logistics_report.items()}
    market_report={k:[r for r in values if (not fid or r['field_id']==fid) and (tests or r['source']=='actual')] for k,values in market_report.items()}
    return {'market':market_report,'logistics':logistics_report,'external_options':external_options,'entries':rows,'references':reference_scope,'fields':fields,'totals':totals,'due':due,'counts':{k:sum(e['kind']==k for e in scope) for k in SPECS if area!='market' or k in market.SPECS},'limits':['Recorded balances reflect saved entries, not verified physical stock.','Reservation status does not create an issue.','Budgets and labour amounts are not finance expenses or payments.','No background reminder, message, diagnosis or equipment action is created.']}


def metadata():return {'specs':SPECS,'market_kinds':list(market.SPECS),'examples':EXAMPLES,'version':'resources-v1'}


def export(store,query):
    from nexus.farm_app.operations_exports import csv_bytes,printable
    result=state(store,query);format=query.get('format','json');rows=[]
    if len(result['entries'])>10000:raise ValueError('Narrow filters to at most 10000 exported entries')
    for e in result['entries']:rows.append({'record_id':e['record_id'],'entry_id':e['id'],'kind':e['kind'],'field_id':e['field_id'],'recorded_at':e['recorded_at'],'source':e['payload']['source'],'reporter':e['payload']['reporter'],'reason':e['payload']['reason'],'content_sha256':e['content_sha256'],**e['payload']['values']})
    if format=='csv':return csv_bytes(rows),'text/csv; charset=utf-8','nexus-resources.csv'
    if format=='html':return printable(rows,'NEXUS saved resource records'),'text/html; charset=utf-8','nexus-resources.html'
    if format=='json' and query.get('area')=='market':return json.dumps({'version':'market-export-v1','filters':query,'entries':result['entries'],'market':result['market'],'limits':result['limits']},indent=2,ensure_ascii=False).encode(),'application/json; charset=utf-8','nexus-market-records.json'
    if format=='json':return json.dumps({'version':'resource-export-v1','filters':query,'entries':result['entries'],'totals':result['totals'],'logistics':result['logistics'],'market':result['market'],'limits':result['limits']},indent=2,ensure_ascii=False).encode(),'application/json; charset=utf-8','nexus-resources.json'
    raise ValueError('Choose csv, json or html')


def calendar(store,query):
    lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//NEXUS//Resource plans//EN','CALSCALE:GREGORIAN']
    for row in state(store,query)['due']:
        # Dates only. Calendar copies are static; no notifications or external invitations.
        safe=lambda s:str(s).replace('\\','\\\\').replace('\r','').replace('\n','\\n').replace(';','\\;').replace(',','\\,')
        lines+=['BEGIN:VEVENT','UID:resource-'+str(row['record_id'])+'@nexus.local','DTSTAMP:'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'DTSTART;VALUE=DATE:'+row['due_date'].replace('-',''),'SUMMARY:'+safe(('TEST: ' if row['source']=='test' else '')+row['name']),'DESCRIPTION:User-planned date. Manual copy; no automatic updates.','END:VEVENT']
    folded=[]
    for line in lines+['END:VCALENDAR']:
        chunk=''
        for char in line:
            if len((chunk+char).encode('utf-8'))>75:
                folded.append(chunk);chunk=' '+char
            else:chunk+=char
        folded.append(chunk)
    return ('\r\n'.join(folded)+'\r\n').encode(),'text/calendar; charset=utf-8','nexus-resource-dates.ics'
