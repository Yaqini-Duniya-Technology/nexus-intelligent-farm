"""Read-only cross-record search, timelines, review dates and sample comparisons."""
import json
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlencode
from nexus.farm_app.operations_common import readonly, table_names, day, positive, LAGOS, canonical, instant

# Only these fixed relations are addressable; no user-supplied SQL identifiers.
SPECS = {
 'measurement':('field_measurements',"WHERE json_extract(x.payload,'$.data.source')!='test_measurement'", 'x.field_id','x.observation_id',"json_extract(x.payload,'$.data.metric') || ' ' || COALESCE(json_extract(x.payload,'$.data.value'),'Unknown') || ' ' || json_extract(x.payload,'$.data.notes')","json_extract(x.payload,'$.data.observed_at')",'x.recorded_at','/evidence-studio?view=measurements'),
 'field_case':('field_case_entries','', 'x.field_id','x.observation_id',"json_extract(x.payload,'$.data.title')",'x.recorded_at','x.recorded_at','/evidence-studio?view=cases'),
 'field_note':('field_notebook','', 'x.field_id','x.observation_id',"json_extract(x.payload,'$.data.title') || ' ' || json_extract(x.payload,'$.data.content')",'x.recorded_at','x.recorded_at','/evidence-studio?view=notes'),
 'evidence_link':('field_evidence_links','', 'x.field_id','x.observation_id',"json_extract(x.payload,'$.data.reason')",'x.recorded_at','x.recorded_at','/evidence-studio?view=links'),
 'observation':('observations','', 'x.field_id','x.id','x.note','x.observed_at','x.created','/observation-seasons'),
 'task':('tasks','JOIN observations o ON o.id=x.observation_id','o.field_id','o.id','x.recommendation','NULL','NULL','/#tasks'),
 'task_action':('task_actions','JOIN tasks t ON t.id=x.task_id JOIN observations o ON o.id=t.observation_id','o.field_id','o.id','x.description','x.performed_at','x.recorded_at','/#history'),
 'followup':('followups','JOIN tasks t ON t.id=x.task_id JOIN observations o ON o.id=t.observation_id','o.field_id','o.id','x.evidence','x.observed_at','x.recorded_at','/#history'),
 'adviser':('adviser_reviews','JOIN observations o ON o.id=x.observation_id','o.field_id','o.id','x.findings','x.reviewed_at','x.recorded_at','/advisers'),
 'photo':('observation_photos','JOIN observations o ON o.id=x.observation_id','o.field_id','o.id','x.caption','x.uploaded_at','x.uploaded_at','/photos'),
 'inspection':('field_inspections','JOIN observations o ON o.id=x.observation_id','o.field_id','o.id',"json_extract(x.payload,'$.findings')","json_extract(x.payload,'$.performed_at')",'x.recorded_at','/field-inspections'),
 'season_context':('observation_season_history','JOIN observations o ON o.id=x.observation_id','o.field_id','o.id',"json_extract(x.payload,'$.basis')",'x.recorded_at','x.recorded_at','/observation-seasons'),
 'decision':('human_decisions','JOIN decision_review_bundles b ON b.id=x.bundle_id JOIN observations o ON o.id=b.observation_id','o.field_id','o.id',"json_extract(x.payload,'$.next_step')",'x.recorded_at','x.recorded_at','/decision-report?decision_id='),
 'decision_action_or_outcome':('decision_events','JOIN human_decisions d ON d.id=x.decision_id JOIN decision_review_bundles b ON b.id=d.bundle_id JOIN observations o ON o.id=b.observation_id','o.field_id','o.id','x.description','x.occurred_at','x.recorded_at','/decision-events'),
 'decision_review':('human_decision_reviews','JOIN human_decisions d ON d.id=x.decision_id JOIN decision_review_bundles b ON b.id=d.bundle_id JOIN observations o ON o.id=b.observation_id','o.field_id','o.id','x.conclusion','x.reviewed_at','x.recorded_at','/decision-reviews'),
 'work_order':('work_orders','', 'x.field_id','x.observation_id',"json_extract(x.payload,'$.state.title')",'x.created_at','x.created_at','/workbench?view=work'),
 'work_event':('work_order_events','JOIN work_orders w ON w.id=x.work_order_id','w.field_id','w.observation_id',"json_extract(x.payload,'$.note')","json_extract(x.payload,'$.performed_at')",'x.recorded_at','/workbench?view=work'),
}


def filter_id(value):
    if value in (None,''):
        return None
    if type(value) is int:
        return positive(value)
    if not isinstance(value,str) or not value.isascii() or not value.isdigit():
        raise ValueError('Use a positive record ID')
    return positive(int(value))


def search(database, params=None):
    params=params or {}
    q=params.get('q','')
    if not isinstance(q,str) or len(q)>200:
        raise ValueError('Search text must be at most 200 characters')
    kind=params.get('kind','')
    if kind and kind not in SPECS:
        raise ValueError('Unknown record type')
    fid,oid=filter_id(params.get('field_id')),filter_id(params.get('observation_id'))
    start,end=params.get('from',''),params.get('to','')
    if start:day(start)
    if end:day(end)
    if start and end and start>end:
        raise ValueError('From date must not follow To date')
    page=filter_id(params.get('page')) or 1
    size=filter_id(params.get('page_size')) or 25
    if size>100 or page>100000:
        raise ValueError('Page size must be at most 100')
    direction=params.get('sort','newest')
    if direction not in ('newest','oldest'):
        raise ValueError('Choose newest or oldest')
    selects=[]
    with readonly(database) as db:
        tables=table_names(db)
        missing=[]
        for name,(table,joins,field,obs,title,occurred,recorded,link) in SPECS.items():
            if kind and name!=kind:continue
            if table not in tables:
                missing.append(name);continue
            # Old pilot schemas may lack optional columns. Do not substitute current evidence.
            try:
                query=f"SELECT x.id,'{name}' AS kind,{field} AS field_id,{obs} AS observation_id,COALESCE({title},'') AS title,{occurred} AS occurred_at,{recorded} AS recorded_at,'{link}' AS link FROM {table} x {joins}"
                db.execute(query+' LIMIT 0')
                selects.append(query)
            except sqlite3.OperationalError:
                missing.append(name)
        if not selects:
            return {'records':[],'total':0,'page':page,'page_size':size,'missing_record_types':missing}
        union=' UNION ALL '.join(selects)
        where=[];args=[]
        if q:
            # Escape LIKE metacharacters so input is literal text.
            pattern='%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            where.append("title LIKE ? ESCAPE '\\'");args.append(pattern)
        if fid is not None:where.append('field_id=?');args.append(fid)
        if oid is not None:where.append('observation_id=?');args.append(oid)
        if start:where.append("date(occurred_at,'+1 hour')>=?");args.append(start)
        if end:where.append("date(occurred_at,'+1 hour')<=?");args.append(end)
        clause=' WHERE '+' AND '.join(where) if where else ''
        total=db.execute('SELECT count(*) FROM ('+union+')'+clause,args).fetchone()[0]
        sort='DESC' if direction=='newest' else 'ASC'
        rows=[dict(r) for r in db.execute('SELECT * FROM ('+union+')'+clause+f' ORDER BY datetime(occurred_at) {sort}, kind, id {sort} LIMIT ? OFFSET ?',args+[size,(page-1)*size])]
        for row in rows:
            if row['kind']=='decision':row['link']+=str(row['id'])
        return {'records':rows,'total':total,'page':page,'page_size':size,
                'missing_record_types':missing,'filters':params,'date_basis':'Lagos calendar dates; legacy times without offset are interpreted as UTC'}


def detail(database,kind,rid):
    if kind not in SPECS:
        raise ValueError('Unknown record type')
    rid=filter_id(rid)
    if rid is None:raise ValueError('Select a record')
    table=SPECS[kind][0]
    with readonly(database) as db:
        if table not in table_names(db):raise ValueError('Record table unavailable')
        row=db.execute(f'SELECT * FROM {table} WHERE id=?',(rid,)).fetchone()
        if row is None:raise ValueError('Record not found')
        result={k:v for k,v in dict(row).items() if not isinstance(v,bytes)}
        for key in ('payload',):
            if key in result:
                try:result[key]=json.loads(result[key])
                except ValueError:pass
        return result


def inspection_ledger(database,params=None):
    from nexus.farm_app.field_inspections import capture_history
    params=params or {}
    fid,oid=filter_id(params.get('field_id')),filter_id(params.get('observation_id'))
    if params.get('from'):day(params['from'])
    if params.get('to'):day(params['to'])
    if params.get('from') and params.get('to') and params['from']>params['to']:
        raise ValueError('From date must not follow To date')
    if params.get('active','true') not in ('true','false'):
        raise ValueError('Active filter must be true or false')
    with readonly(database) as db:
        tables=table_names(db)
        if 'field_inspections' not in tables:return {'entries':[],'status':'unavailable'}
        sql='SELECT * FROM observations';args=[];where=[]
        if fid is not None:where.append('field_id=?');args.append(fid)
        if oid is not None:where.append('id=?');args.append(oid)
        if where:sql+=' WHERE '+' AND '.join(where)
        rows=[]
        for observation in db.execute(sql,args):
            rows.extend(capture_history(db,tables,dict(observation)))
        corrected={r['supersedes_id'] for r in rows if r['supersedes_id'] is not None}
        result=[]
        for row in rows:
            if params.get('active','true')=='true' and row['id'] in corrected:continue
            data=row['payload']
            entry={**row,'corrected':row['id'] in corrected}
            if params.get('from') and day(params['from'])> instant(data['performed_at']).astimezone(LAGOS).date():continue
            if params.get('to') and day(params['to'])< instant(data['performed_at']).astimezone(LAGOS).date():continue
            result.append(entry)
        result.sort(key=lambda r:(r['payload']['performed_at'],r['id']),reverse=True)
        return {'entries':result,'status':'available','limitations':['Each inspection is a reported sample. Counts are not summed across inspections. Corrected entries remain in history.']}


def compare_inspections(database,ids):
    if not isinstance(ids,list) or not 1<=len(ids)<=2:
        raise ValueError('Choose one or two inspections')
    wanted=[filter_id(i) for i in ids]
    if None in wanted or len(set(wanted))!=len(wanted):raise ValueError('Choose distinct inspection IDs')
    all_rows=inspection_ledger(database,{'active':'false'})['entries']
    selected=[next((r for r in all_rows if r['id']==i),None) for i in wanted]
    if any(r is None for r in selected):raise ValueError('Inspection not found')
    return {'inspections':selected,'limitations':['Side-by-side display does not establish comparable sampling, growth stage or season. No change rate or effectiveness is inferred.']}


def review_queue(database,params=None,now=None):
    params=params or {};now=now or datetime.now(timezone.utc);today=now.astimezone(LAGOS).date()
    if params.get('status','') not in ('','overdue','today','upcoming','closed','unavailable'):
        raise ValueError('Choose a valid review timing filter')
    with readonly(database) as db:
        tables=table_names(db)
        if 'human_decisions' not in tables:return {'items':[],'checked_at':now.isoformat()}
        items=[]
        for row in db.execute('SELECT * FROM human_decisions ORDER BY id'):
            decision=dict(row);data=json.loads(decision['payload'])
            latest=db.execute('SELECT * FROM human_decision_reviews WHERE decision_id=? ORDER BY id DESC LIMIT 1',(row['id'],)).fetchone() if 'human_decision_reviews' in tables else None
            latest=dict(latest) if latest else None
            closed=bool(latest and latest['disposition']=='close')
            active=None if closed else latest['next_review_date'] if latest else data.get('review_date')
            try:d=day(active);timing='closed' if closed else 'overdue' if d<today else 'today' if d==today else 'upcoming'
            except ValueError:timing='closed' if closed else 'unavailable'
            item={'decision_id':row['id'],'title':data.get('next_step',''), 'active_review_date':active,
                  'timing':timing,'latest_review_id':latest['id'] if latest else None,
                  'disposition':latest['disposition'] if latest else None,'recorded_at':row['recorded_at']}
            if params.get('status') and item['timing']!=params['status']:continue
            if not params.get('status') and closed and params.get('include_closed')!='true':continue
            items.append(item)
        rank={'overdue':0,'today':1,'upcoming':2,'unavailable':3,'closed':4}
        items.sort(key=lambda r:(rank[r['timing']],r['active_review_date'] or '',r['decision_id']))
        return {'items':items,'checked_at':now.isoformat(),'date_basis':'Africa/Lagos; no background notification'}


def calendar(database):
    queue=review_queue(database)
    def esc(value):return str(value).replace('\\','\\\\').replace('\r','').replace('\n','\\n').replace(';','\\;').replace(',','\\,')
    lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//NEXUS//Review Calendar//EN','CALSCALE:GREGORIAN']
    for item in queue['items']:
        if item['timing']=='unavailable':continue
        d=day(item['active_review_date'])
        from datetime import timedelta
        lines+=['BEGIN:VEVENT',f"UID:decision-{item['decision_id']}@nexus.local",
                'DTSTAMP:'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),
                'DTSTART;VALUE=DATE:'+d.strftime('%Y%m%d'),'DTEND;VALUE=DATE:'+(d+timedelta(days=1)).strftime('%Y%m%d'),
                'SUMMARY:'+esc('NEXUS review decision #'+str(item['decision_id'])),
                'DESCRIPTION:'+esc(item['title']+'\nLagos calendar date. Exported copy; later NEXUS edits do not update this calendar file.'),'END:VEVENT']
    lines+=['END:VCALENDAR']
    # Fold by UTF-8 octets, without splitting a multibyte character.
    folded=[]
    for line in lines:
        chunk=''
        for char in line:
            if len((chunk+char).encode())>74:
                folded.append(chunk);chunk=' '+char
            else:chunk+=char
        folded.append(chunk)
    return ('\r\n'.join(folded)+'\r\n').encode()
