"""Descriptive cash reports, structural capture comparisons and evidence checks."""
import hashlib
import json
from datetime import datetime,timezone
from nexus.farm_app.operations_common import readonly,table_names,positive,day,instant,LAGOS
from nexus.farm_app import studio_ledger as ledger,studio_cases,studio_links,field_measurements


def finance(database,filters=None):
    from nexus.farm_app.operations_records import filter_id
    filters=filters or {};sid=filter_id(filters.get('season_id'));fid=filter_id(filters.get('field_id'))
    start=day(filters['from']) if filters.get('from') else None;end=day(filters['to']) if filters.get('to') else None
    if start and end and start>end:raise ValueError('From date must not follow To date')
    with readonly(database) as db:
        tables=table_names(db)
        if not {'season_transactions','crop_seasons'}<=tables:return {'entries':[],'months':[],'status':'unavailable'}
        seasons={r['id']:dict(r) for r in db.execute('SELECT * FROM crop_seasons')}
        rows=[];months={};totals={'expenses_kobo':0,'sales_kobo':0,'net_cash_kobo':0}
        for raw in db.execute('SELECT * FROM season_transactions ORDER BY occurred_at,id'):
            row=dict(raw);season=seasons.get(row['season_id'])
            if season is None:raise ValueError('Transaction season is missing')
            if sid is not None and row['season_id']!=sid:continue
            if fid is not None and season['field_id']!=fid:continue
            if filters.get('kind') and row['kind']!=filters['kind']:continue
            if filters.get('q') and filters['q'].lower() not in row['description'].lower():continue
            date=day(row['occurred_at']) if len(row['occurred_at'])==10 else instant(row['occurred_at']).astimezone(LAGOS).date()
            if (start and date<start) or (end and date>end):continue
            if type(row['amount_kobo']) is not int or row['amount_kobo']<=0 or row['kind'] not in ('sale','expense'):raise ValueError('Invalid saved cash entry')
            key='sales_kobo' if row['kind']=='sale' else 'expenses_kobo'
            month=date.strftime('%Y-%m');item=months.setdefault(month,{'month':month,'expenses_kobo':0,'sales_kobo':0,'entries':0})
            item[key]+=row['amount_kobo'];item['entries']+=1;totals[key]+=row['amount_kobo']
            rows.append({**row,'field_id':season['field_id'],'season_name':season['name']})
        for item in months.values():item['net_cash_kobo']=item['sales_kobo']-item['expenses_kobo']
        totals['net_cash_kobo']=totals['sales_kobo']-totals['expenses_kobo']
        return {'entries':rows,'months':list(months.values()),'totals':totals,'status':'available',
                'limitations':['Net cash is recorded sales minus recorded expenses; it is not profit.','Missing months have no selected entries; they are not treated as zero economic activity.','This report does not add or edit financial transactions.']}


def compare(database,left_id,right_id,section=''):
    positive(left_id,'left bundle ID');positive(right_id,'right bundle ID')
    if left_id==right_id:raise ValueError('Choose two different saved bundles')
    with readonly(database) as db:
        selected=[]
        for rid in (left_id,right_id):
            raw=db.execute('SELECT * FROM decision_review_bundles WHERE id=?',(rid,)).fetchone()
            if raw is None:raise ValueError('Saved bundle not found')
            row=dict(raw);row['payload']=json.loads(row['payload'])
            encoded=json.dumps(row['payload'],sort_keys=True,ensure_ascii=False,allow_nan=False).encode()
            if hashlib.sha256(encoded).hexdigest()!=row['content_sha256']:raise ValueError('Bundle content hash mismatch')
            selected.append(row)
    left,right=selected
    if left['observation_id']!=right['observation_id']:raise ValueError('Compare bundles for the same observation')
    if section and section not in set(left['payload'])|set(right['payload']):raise ValueError('Section not found in these captures')
    a={section:left['payload'][section]} if section in left['payload'] else {} if section else left['payload']
    b={section:right['payload'][section]} if section in right['payload'] else {} if section else right['payload']
    differences=[]
    def walk(old,new,path):
        if len(differences)>5000:raise ValueError('More than 5000 changes; select a narrower section')
        if type(old) is type(new) and isinstance(old,dict):
            for key in sorted(set(old)|set(new)):
                sub=path+'/'+str(key).replace('~','~0').replace('/','~1')
                if key not in old:differences.append({'path':sub,'change':'added','before':None,'after':new[key]})
                elif key not in new:differences.append({'path':sub,'change':'removed','before':old[key],'after':None})
                else:walk(old[key],new[key],sub)
        elif old!=new or type(old) is not type(new):differences.append({'path':path or '/','change':'changed','before':old,'after':new})
    walk(a,b,'')
    if len(differences)>5000:raise ValueError('More than 5000 changes; select a narrower section')
    return {'left':{'id':left_id,'captured_at':left['captured_at'],'payload':a},
            'right':{'id':right_id,'captured_at':right['captured_at'],'payload':b},'differences':differences,
            'sections':sorted(set(left['payload'])|set(right['payload'])),
            'limitations':['Structural changes in saved captures do not establish changes in the field or treatment effectiveness.','Arrays are compared as stored lists. Captures are never rewritten by this comparison.']}


def quality(database):
    readings=field_measurements.readings(database,{'include_tests':'true'})
    real=[r for r in readings if r['payload']['data']['source']!='test_measurement']
    tests=[r for r in readings if r['payload']['data']['source']=='test_measurement']
    latest={}
    for row in sorted(real,key=lambda r:r['payload']['data']['observed_at']):latest[(row['field_id'],row['payload']['data']['metric'])]=row
    coverage=[{'field_id':fid,'metric':metric,'measurement_id':r['id'],'observed_at':r['payload']['data']['observed_at'],
               'value':r['payload']['data']['value'],'unit':r['payload']['data']['unit']} for (fid,metric),r in latest.items()]
    unknown=[r for r in real if r['payload']['data']['value'] is None]
    links=studio_links.entries(database)
    checks=[]
    with readonly(database) as db:
        for table in ledger.TABLES:
            rows=ledger.read(db,table);checks.append({'table':table,'verified_entries':len(rows)})
    return {'case_review_queue':studio_cases.queue(database),'latest_measurement_coverage':coverage,
            'unknown_measurements':unknown,'test_measurement_count':len(tests),'farm_measurement_count':len(real),
            'links_needing_review':[r for r in links if r['reference_status'] not in ('matches','withdrawn')],
            'new_ledger_checks':checks,'limitations':['Coverage lists saved readings; it is not a sampling plan or readiness score.','Unknown measurements are not treated as zero. Test data is not counted as farm readings.','Source labels and answers remain user-reported.']}


def capture_context(db,tables,observation):
    result={'measurement_history':None,'excluded_test_measurements':None,'case_history':None,'notebook_history':None,'evidence_links':None}
    oid=observation['id']
    if 'field_measurements' in tables:
        rows=[r for r in ledger.read(db,'field_measurements') if r['observation_id']==oid]
        result['measurement_history']=[r for r in rows if r['payload']['data']['source']!='test_measurement']
        result['excluded_test_measurements']=sum(r['payload']['data']['source']=='test_measurement' for r in rows)
    for table,key in [('field_case_entries','case_history'),('field_notebook','notebook_history')]:
        if table in tables:result[key]=[r for r in ledger.read(db,table) if r['observation_id']==oid]
    if 'field_evidence_links' in tables:result['evidence_links']=studio_links.capture(db,tables,observation)
    return result
