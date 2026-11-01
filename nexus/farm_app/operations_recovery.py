"""Verified backup manifests and restore-to-new-file recovery. Never overwrites a DB."""
import argparse
import hashlib
import json
import platform
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from nexus.farm_app.operations_common import readonly, table_names, identifier, canonical, RELEASE


def file_hash(path):
    hashed=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):hashed.update(block)
    return hashed.hexdigest()


def inspect(database,deep=False):
    with readonly(database) as db:
        integrity=[r[0] for r in db.execute('PRAGMA integrity_check')]
        relationships=[list(r) for r in db.execute('PRAGMA foreign_key_check')]
        tables=table_names(db)
        if not {'farms','fields','observations','tasks'} <= tables:
            raise ValueError('This is not a supported NEXUS farm database')
        counts={table:db.execute('SELECT count(*) FROM '+identifier(table)).fetchone()[0] for table in sorted(tables)}
        hashes=[];photos=[]
        if deep:
            known={'decision_review_bundles','decision_cycle_snapshots','human_decisions','field_inspections',
                   'observation_season_history','voice_clarification_answers','work_orders','work_order_events','resource_entries'}
            for table in sorted(known & tables):
                columns={r[1] for r in db.execute('PRAGMA table_info('+identifier(table)+')')}
                if not {'id','payload','content_sha256'} <= columns:continue
                for row in db.execute('SELECT id,payload,content_sha256 FROM '+identifier(table)):
                    matches=False
                    try:
                        data=json.loads(row['payload'])
                        variants=[canonical(data),json.dumps(data,sort_keys=True,ensure_ascii=False,allow_nan=False)]
                        matches=row['content_sha256'] in {hashlib.sha256(v.encode()).hexdigest() for v in variants}
                    except (ValueError,TypeError):pass
                    hashes.append({'table':table,'id':row['id'],'matches':matches})
            if 'observation_photos' in tables:
                for row in db.execute('SELECT id,image_data,sha256 FROM observation_photos'):
                    data=row['image_data']
                    photos.append({'id':row['id'],'matches':isinstance(data,bytes) and hashlib.sha256(data).hexdigest()==row['sha256']})
        return {'integrity_ok':integrity==['ok'],'integrity_messages':integrity,
                'foreign_key_errors':relationships,'table_counts':counts,
                'frozen_hash_checks':hashes,'photo_hash_checks':photos,
                'limitations':['Checks test stored consistency, not agricultural accuracy or author identity.']}


def doctor(database):
    from nexus.farm_app.operations_common import digest
    from nexus.farm_app.work_orders import history
    result=inspect(database,True)
    chains=[]
    with readonly(database) as db:
        tables=table_names(db)
        if {'work_orders','work_order_events'} <= tables:
            for row in db.execute('SELECT id FROM work_orders'):
                try:history(db,row[0]);valid=True
                except (ValueError,KeyError,TypeError):valid=False
                chains.append({'id':row[0],'valid':valid})
    studio_checks=[]
    from nexus.farm_app import studio_ledger
    with readonly(database) as db:
        for table in studio_ledger.TABLES:
            if table not in table_names(db):continue
            try:
                rows=studio_ledger.read(db,table);studio_checks.append({'table':table,'entries':len(rows),'valid':True})
            except ValueError:
                studio_checks.append({'table':table,'entries':None,'valid':False})
    result['studio_ledger_checks']=studio_checks
    resource_checks=[]
    from nexus.farm_app import farm_resources
    with readonly(database) as db:
        if 'resource_entries' in table_names(db):
            try:
                entries,current=farm_resources.load(db)
                farm_resources.validate_links(current)
                resource_checks.append({'entries':len(entries),'valid':True})
            except (ValueError,KeyError,TypeError,ArithmeticError):
                resource_checks.append({'entries':None,'valid':False})
    result['resource_ledger_checks']=resource_checks
    result.update(release=RELEASE,python=sys.version.split()[0],platform=platform.system(),
                  checked_at=datetime.now(timezone.utc).isoformat(),work_order_chain_checks=chains,
                  optional_modules={'work_orders': 'work_orders' in result['table_counts'],
                                    'field_inspections':'field_inspections' in result['table_counts'],
                                    'season_context':'observation_season_history' in result['table_counts']})
    result['ok']=result['integrity_ok'] and not result['foreign_key_errors'] and all(x['matches'] for x in result['frozen_hash_checks']+result['photo_hash_checks']) and all(x['valid'] for x in chains) and all(x['valid'] for x in studio_checks) and all(x['valid'] for x in resource_checks)
    return result


def backup(database,output_directory):
    from nexus.farm_app.backup import backup_database
    # Core backup API includes committed WAL changes; never just copy an open SQLite file.
    inspect(database)
    target,_=backup_database(database,output_directory)
    manifest=target.with_suffix(target.suffix+'.manifest.json')
    try:
        checked=inspect(target)
        content={'manifest_version':'nexus-backup-v1','filename':target.name,
                 'created_at':datetime.now(timezone.utc).isoformat(),'sha256':file_hash(target),
                 'size_bytes':target.stat().st_size,'table_counts':checked['table_counts'],
                 'integrity_ok':checked['integrity_ok'],'foreign_key_errors':checked['foreign_key_errors'],
                 'release':RELEASE,'scope':'Whole SQLite database; external files are not included'}
        with manifest.open('x',encoding='utf-8') as stream:stream.write(json.dumps(content,indent=2)+'\n')
        return {'backup':str(target),'manifest':str(manifest),'table_counts':content['table_counts']}
    except BaseException:
        target.unlink(missing_ok=True)
        manifest.unlink(missing_ok=True)
        raise


def verify(database,manifest=None):
    path=Path(database).resolve();result=inspect(path)
    if manifest is None:
        candidate=path.with_suffix(path.suffix+'.manifest.json')
        manifest=candidate if candidate.is_file() else None
    result['manifest_status']='not_provided'
    if manifest is not None:
        content=json.loads(Path(manifest).read_text(encoding='utf-8'))
        if content.get('manifest_version')!='nexus-backup-v1':raise ValueError('Unsupported backup manifest')
        matches=(content.get('sha256')==file_hash(path) and content.get('size_bytes')==path.stat().st_size
                 and content.get('table_counts')==result['table_counts'])
        result['manifest_status']='matches' if matches else 'mismatch'
    result['ok']=result['integrity_ok'] and not result['foreign_key_errors'] and result['manifest_status']!='mismatch'
    return result


def restore(source,destination,commit=False,manifest=None):
    source=Path(source).expanduser().resolve();destination=Path(destination).expanduser().resolve()
    if destination.exists() or source==destination:
        raise ValueError('Recovery creates a NEW file only. Choose a destination that does not exist.')
    if any(Path(str(destination)+suffix).exists() for suffix in ('-wal','-shm','-journal')):
        raise ValueError('SQLite sidecar files exist at the destination. Choose another filename.')
    if any(Path(str(source)+suffix).exists() for suffix in ('-wal','-journal')):
        raise ValueError('Restore from an offline backup file, not a live database with SQLite sidecars')
    source_hash=file_hash(source)
    checked=verify(source,manifest)
    if not checked['ok']:raise ValueError('Backup verification failed; recovery was not performed')
    result={'mode':'restore_copy' if commit else 'dry_run','destination':str(destination),
            'source_checks':checked,'source_unchanged':True}
    if not commit:return result
    destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.open('xb'):pass
    try:
        with readonly(source) as src:
            target=sqlite3.connect(destination)
            try:src.backup(target)
            finally:target.close()
        if file_hash(source)!=source_hash:
            raise ValueError('Source changed during recovery; use an offline backup')
        copied=inspect(destination)
        if not copied['integrity_ok'] or copied['foreign_key_errors'] or copied['table_counts']!=checked['table_counts']:
            raise ValueError('Recovered copy verification failed')
        result['verified']=True
        return result
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def main():
    parser=argparse.ArgumentParser(description='NEXUS backup, recovery and diagnostics')
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('doctor','verify','backup'):
        p=sub.add_parser(name);p.add_argument('--database',default='nexus-farm.sqlite3')
        if name=='backup':p.add_argument('--output-directory',default='backups')
        if name=='verify':p.add_argument('--manifest')
    p=sub.add_parser('restore');p.add_argument('--source',required=True);p.add_argument('--destination',required=True)
    p.add_argument('--manifest');p.add_argument('--commit',action='store_true',help='Create the verified NEW database file; otherwise preview only')
    args=parser.parse_args()
    try:
        if args.command=='doctor':result=doctor(args.database)
        elif args.command=='backup':result=backup(args.database,args.output_directory)
        elif args.command=='verify':result=verify(args.database,args.manifest)
        else:result=restore(args.source,args.destination,args.commit,args.manifest)
    except (ValueError,OSError,sqlite3.Error) as error:parser.exit(1,f'Operation failed: {error}\n')
    print(json.dumps(result,indent=2))
    if result.get('ok') is False:parser.exit(1,'Checks found inconsistencies.\n')


if __name__=='__main__':main()
