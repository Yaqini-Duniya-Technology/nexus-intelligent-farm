"""Manual questions, field notes and reusable local views. No automatic resolutions."""
from datetime import datetime,timezone
from urllib.parse import urlencode
from nexus.farm_app import studio_ledger as ledger
from nexus.farm_app.operations_common import word,day,readonly,LAGOS


def tags(value):
    if not isinstance(value,list) or len(value)>10:raise ValueError('Use at most ten tags')
    result=[word(v,'tag',40).lower() for v in value]
    if len(set(result))!=len(result):raise ValueError('Tags must be distinct')
    return result


def normalize(kind,data):
    result={'title':word(data.get('title'),'title',300),'reporter':word(data.get('reporter'),'reporter',200),
            'reason':word(data.get('reason'),'entry or revision reason',1000),'tags':tags(data.get('tags',[]))}
    if kind=='case':
        result['owner']=word(data.get('owner'),'owner',200)
        if data.get('status') not in ('open','monitoring','closed'):raise ValueError('Choose open, monitoring or closed')
        result['status']=data['status'];due=data.get('next_review_date')
        result['next_review_date']=day(due).isoformat() if due else None
        questions=data.get('questions')
        if not isinstance(questions,list) or not 1<=len(questions)<=20:raise ValueError('Record one to twenty case questions')
        result['questions']=[]
        for q in questions:
            if not isinstance(q,dict):raise ValueError('Invalid case question')
            question=word(q.get('question'),'question',1000);status=q.get('status')
            if status not in ('open','answered','deferred'):raise ValueError('Choose a question status')
            answer=q.get('answer','')
            if not isinstance(answer,str) or len(answer)>3000:raise ValueError('Answer must be text up to 3000 characters')
            if status=='answered' and not answer.strip():raise ValueError('Answered questions require a recorded answer')
            result['questions'].append({'question':question,'status':status,'answer':answer.strip()})
        if result['status']!='closed' and result['next_review_date'] is None:raise ValueError('An active case needs a next review date')
    elif kind=='note':
        result['content']=word(data.get('content'),'note',6000)
        if type(data.get('pinned')) is not bool:raise ValueError('Choose whether the note is pinned')
        result['pinned']=data['pinned']
    elif kind=='view':
        if data.get('path') not in ('/workbench','/evidence-studio'):raise ValueError('Saved views must point to a local workbench')
        filters=data.get('filters')
        if not isinstance(filters,dict) or len(filters)>15 or any(not isinstance(k,str) or len(k)>40 or not isinstance(v,str) or len(v)>500 for k,v in filters.items()):raise ValueError('Invalid saved view filters')
        result['path']=data['path'];result['filters']=filters
    else:raise ValueError('Unsupported field journal kind')
    return result


TABLE={'case':'field_case_entries','note':'field_notebook','view':'saved_studio_views'}


def save(store,kind,data):
    content=normalize(kind,data)
    fid,oid=data.get('field_id'),data.get('observation_id')
    if kind=='view':fid=oid=None
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if kind!='view':ledger.context(db,fid,oid)
        return ledger.append(db,TABLE[kind],fid,oid,content,data.get('root_id'),data.get('base_id'))


def entries(database,kind,filters=None):
    from nexus.farm_app.operations_records import filter_id
    filters=filters or {};fid=filter_id(filters.get('field_id'));tag=filters.get('tag','').strip().lower()
    with readonly(database) as db:
        rows=ledger.read(db,TABLE[kind]);result=[]
        for row in rows:
            content=row['payload']['data']
            if filters.get('history')!='true' and not row['latest']:continue
            if fid is not None and row['field_id']!=fid:continue
            if tag and tag not in content['tags']:continue
            if kind=='case' and filters.get('status') and content['status']!=filters['status']:continue
            if kind=='note' and filters.get('pinned')=='true' and not content['pinned']:continue
            if kind=='view':row['url']=content['path']+'?'+urlencode(content['filters'])
            result.append(row)
        if kind=='note':result.sort(key=lambda r:(not r['payload']['data']['pinned'],-r['id']))
        return result


def queue(database,now=None):
    today=(now or datetime.now(timezone.utc)).astimezone(LAGOS).date();rows=[]
    for row in entries(database,'case'):
        data=row['payload']['data'];due=data['next_review_date']
        timing='closed' if data['status']=='closed' else 'overdue' if day(due)<today else 'today' if day(due)==today else 'upcoming'
        rows.append({'id':row['id'],'root_id':row['root_id'] or row['id'],'field_id':row['field_id'],'title':data['title'],
                     'owner':data['owner'],'timing':timing,'next_review_date':due,
                     'open_questions':sum(q['status']=='open' for q in data['questions']),
                     'deferred_questions':sum(q['status']=='deferred' for q in data['questions'])})
    rank={'overdue':0,'today':1,'upcoming':2,'closed':3}
    return sorted(rows,key=lambda r:(rank[r['timing']],r['next_review_date'] or '',r['id']))
