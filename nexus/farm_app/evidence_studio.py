"""Evidence studio routes, metadata and standard-library export adapters."""
import json
from pathlib import Path
from nexus.farm_app import field_measurements as measurements,studio_ledger as ledger,studio_cases as cases,studio_links as links,studio_reports as reports,studio_backups as backups
from nexus.farm_app.operations_common import readonly,table_names,positive
from nexus.farm_app.operations_exports import csv_bytes,printable


def initialize(store):measurements.initialize(store)


def metadata(database):
    with readonly(database) as db:
        tables=table_names(db)
        fields=[dict(r) for r in db.execute('SELECT * FROM fields ORDER BY id')]
        observations=[dict(r) for r in db.execute('SELECT id,field_id,note FROM observations ORDER BY id DESC')]
        seasons=[dict(r) for r in db.execute('SELECT * FROM crop_seasons ORDER BY id DESC')] if 'crop_seasons' in tables else []
        bundles=[dict(r) for r in db.execute('SELECT id,observation_id,captured_at FROM decision_review_bundles ORDER BY id DESC')] if 'decision_review_bundles' in tables else []
    return {'fields':fields,'observations':observations,'seasons':seasons,'bundles':bundles,
            'metrics':{key:{'unit':v[0],'entry_min':v[1],'entry_max':v[2]} for key,v in measurements.METRICS.items()},
            'sources':list(measurements.SOURCES),'link_kinds':list(links.KINDS)}


def number(query,key):
    from nexus.farm_app.operations_records import filter_id
    value=filter_id(query.get(key))
    if value is None:raise ValueError('Select '+key.replace('_',' '))
    return value


def get(store,endpoint,query):
    db=store.path
    if endpoint=='meta':return metadata(db)
    if endpoint=='measurements':return {'entries':measurements.readings(db,query)}
    if endpoint=='template':return measurements.template(),'text/csv; charset=utf-8','nexus-measurements-template.csv'
    if endpoint in ('cases','notes','views'):return {'entries':cases.entries(db,{'cases':'case','notes':'note','views':'view'}[endpoint],query)}
    if endpoint=='case-queue':return {'entries':cases.queue(db)}
    if endpoint=='links':return {'entries':links.entries(db,query)}
    if endpoint=='source':
        with readonly(db) as connection:return links.target(connection,query.get('kind'),number(query,'id'))
    if endpoint=='compare':
        report=reports.compare(db,number(query,'left_id'),number(query,'right_id'),query.get('section',''))
        format=query.get('format','json')
        if format=='csv':return csv_bytes(report['differences']),'text/csv; charset=utf-8','nexus-bundle-differences.csv'
        if format=='html':return printable(report['differences'],'NEXUS saved bundle differences'),'text/html; charset=utf-8','nexus-bundle-differences.html'
        return report
    if endpoint=='finance':return reports.finance(db,query)
    if endpoint=='quality':return reports.quality(db)
    if endpoint=='backups':return backups.catalogue(db)
    if endpoint=='backup-verify':return backups.verify(db,query.get('name'))
    if endpoint=='backup-download':return backups.portable(db,query.get('name')),'application/zip','nexus-verified-backup.zip'
    if endpoint=='export':
        dataset=query.get('dataset','measurements')
        if dataset=='measurements':rows=measurements.readings(db,query)
        elif dataset in ('cases','notes','views'):rows=cases.entries(db,{'cases':'case','notes':'note','views':'view'}[dataset],query)
        elif dataset=='links':rows=links.entries(db,query)
        elif dataset in ('cash_entries','cash_months'):rows=reports.finance(db,query)['entries' if dataset=='cash_entries' else 'months']
        else:raise ValueError('Unsupported studio export')
        if len(rows)>10000:raise ValueError('Export is limited to 10000 entries')
        format=query.get('format','csv')
        if format=='csv':return csv_bytes(rows),'text/csv; charset=utf-8','nexus-'+dataset+'.csv'
        if format=='html':return printable(rows,'NEXUS '+dataset),'text/html; charset=utf-8','nexus-'+dataset+'.html'
        if format=='json':return json.dumps({'dataset':dataset,'filters':query,'entries':rows},indent=2,ensure_ascii=False).encode(),'application/json; charset=utf-8','nexus-'+dataset+'.json'
        raise ValueError('Choose csv, json or html')
    raise ValueError('Unknown evidence studio route')


def post(store,endpoint,data):
    if endpoint=='measurements':return measurements.save(store,data)
    if endpoint=='import-preview':return measurements.preview(store,data)
    if endpoint=='import-commit':return measurements.commit(store,data)
    if endpoint in ('cases','notes','views'):return cases.save(store,{'cases':'case','notes':'note','views':'view'}[endpoint],data)
    if endpoint=='links':return links.save(store,data)
    if endpoint=='backup-create':return backups.create(store.path,data.get('confirm'))
    if endpoint=='backup-restore-copy':return backups.restore_copy(store.path,data.get('name'),data.get('confirm'))
    raise ValueError('Unknown evidence studio write route')
