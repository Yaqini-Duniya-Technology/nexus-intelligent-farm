"""Bounded, spreadsheet-safe exports and portable offline report packages."""
import argparse
import csv
import hashlib
import io
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from nexus.farm_app.operations_common import text, canonical, readonly
from nexus.farm_app import operations_records as records

MAX_EXPORT=10000


def csv_bytes(rows):
    keys=list(dict.fromkeys(k for row in rows for k in row))
    output=io.StringIO(newline='');writer=csv.DictWriter(output,fieldnames=keys);writer.writeheader()
    for row in rows:
        clean={}
        for key,value in row.items():
            if isinstance(value,(dict,list)):value=canonical(value)
            if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@','\t','\r','\n')):value="'"+value
            clean[key]='' if value is None else value
        writer.writerow(clean)
    return ('\ufeff'+output.getvalue()).encode('utf-8')


def dataset(database,kind='records',params=None):
    with readonly(database) as db:
        return _dataset(db,kind,params)


def _dataset(database,kind='records',params=None):
    params=dict(params or {})
    if kind=='reviews':return records.review_queue(database,params)['items']
    if kind=='inspections':
        rows=records.inspection_ledger(database,params)['entries']
        if len(rows)>MAX_EXPORT:raise ValueError('Export exceeds 10000 rows; narrow the filters')
        return [{'inspection_id':r['id'],'observation_id':r['observation_id'],'corrected':r['corrected'],
                 'recorded_at':r['recorded_at'],**{k:v for k,v in r['payload'].items() if k!='observation_at_capture'}} for r in rows]
    if kind!='records':raise ValueError('Choose records, inspections or reviews')
    params.update(page=1,page_size=100)
    first=records.search(database,params)
    if first['total']>MAX_EXPORT:raise ValueError('Export exceeds 10000 rows; narrow the filters')
    result=first['records']
    for page in range(2,(first['total']+99)//100+1):
        params['page']=page;result.extend(records.search(database,params)['records'])
    return result


def printable(rows,title):
    keys=list(dict.fromkeys(k for row in rows for k in row))
    head=''.join('<th>'+text(k.replace('_',' '))+'</th>' for k in keys)
    body=''.join('<tr>'+''.join('<td>'+text(canonical(row[k]) if isinstance(row.get(k),(list,dict)) else row.get(k))+'</td>' for k in keys)+'</tr>' for row in rows)
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+text(title)+'</title><style>body{font:14px system-ui;margin:24px;color:#183c2c}table{border-collapse:collapse;width:100%}td,th{border:1px solid #b7cbbb;padding:8px;text-align:left;vertical-align:top;overflow-wrap:anywhere}td{white-space:pre-wrap}@media print{button{display:none}table{font-size:10px}}</style><h1>'+text(title)+'</h1><p>Saved export. Later farm edits do not update this copy. Reports are user-entered and do not establish diagnosis or effectiveness.</p><button onclick="print()">Print / save PDF</button><div style="overflow:auto"><table><thead><tr>'+head+'</tr></thead><tbody>'+body+'</tbody></table></div></html>').encode()


def export(database,kind='records',format='csv',params=None):
    rows=dataset(database,kind,params)
    if format=='csv':return csv_bytes(rows),'text/csv; charset=utf-8'
    if format=='html':return printable(rows,'NEXUS '+kind+' export'),'text/html; charset=utf-8'
    if format=='json':return (json.dumps({'export_version':'nexus-record-export-v1','captured_at':datetime.now(timezone.utc).isoformat(),'kind':kind,'filters':params or {},'records':rows},indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode(),'application/json; charset=utf-8'
    raise ValueError('Choose csv, json or html')


def portable(database,kind='records',params=None):
    # One selected data extraction is reused for all formats.
    rows=dataset(database,kind,params)
    captured=datetime.now(timezone.utc).isoformat()
    files={'records.csv':csv_bytes(rows),'report.html':printable(rows,'NEXUS '+kind+' offline report'),
           'records.json':json.dumps({'export_version':'nexus-record-export-v1','captured_at':captured,'kind':kind,'filters':params or {},'records':rows},indent=2,ensure_ascii=False,allow_nan=False).encode()}
    manifest={'package_version':'nexus-offline-report-v1','captured_at':captured,'kind':kind,'record_count':len(rows),
              'files':{name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()},
              'limitations':['This package is an export, not a restorable database backup.','Hashes check consistency, not identity or agricultural accuracy.']}
    files['manifest.json']=(json.dumps(manifest,indent=2)+'\n').encode()
    output=io.BytesIO()
    with ZipFile(output,'w',ZIP_DEFLATED) as zipped:
        for name,raw in files.items():zipped.writestr(name,raw)
    return output.getvalue()


def main():
    p=argparse.ArgumentParser(description='Export NEXUS records without starting a server')
    p.add_argument('--database',default='nexus-farm.sqlite3');p.add_argument('--kind',choices=['records','inspections','reviews'],default='records')
    p.add_argument('--format',choices=['csv','json','html','zip'],default='zip');p.add_argument('--output',required=True)
    for name in ('field-id','observation-id','q','from-date','to-date'):p.add_argument('--'+name)
    args=p.parse_args();filters={'field_id':args.field_id,'observation_id':args.observation_id,'q':args.q or '', 'from':args.from_date or '', 'to':args.to_date or ''}
    try:
        raw=portable(args.database,args.kind,filters) if args.format=='zip' else export(args.database,args.kind,args.format,filters)[0]
        target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as stream:stream.write(raw)
    except (ValueError,OSError,sqlite3.Error) as error:p.exit(1,f'Export failed: {error}\n')
    print('Saved export:',target.resolve())


if __name__=='__main__':main()
