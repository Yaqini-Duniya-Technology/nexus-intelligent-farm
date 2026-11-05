"""Install the checked authenticated-core release into an existing local project."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime,timezone
from pathlib import Path,PurePosixPath


def validate(release):
    manifest=json.loads((release/'RELEASE.json').read_text(encoding='utf-8'))
    if manifest.get('release')!='nexus-authenticated-core-v1' or not manifest.get('files'):
        raise ValueError('Unsupported or empty release manifest')
    files=manifest['files']
    for name,digest in files.items():
        relative=PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or '\\' in name or not (relative.parts[:2]==('nexus','farm_app') or relative.parts[0]=='docs'):
            raise ValueError('Unsafe release path')
        source=release.joinpath(*relative.parts)
        if source.is_symlink() or not source.resolve().is_relative_to(release.resolve()) or not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=digest:
            raise ValueError('Missing or changed release file: '+name)
        if source.suffix=='.py':
            compile(source.read_text(encoding='utf-8-sig'),str(source),'exec')
    return files


def install(release,project,database='nexus-farm.sqlite3',check_only=False):
    release=Path(release).resolve();project=Path(project).resolve()
    files=validate(release)
    if not (project/'nexus/farm_app/store.py').is_file():
        raise ValueError('Select the existing NEXUS project, not the downloaded release')
    for name in files:
        target=project/name
        if target.is_symlink() or not target.resolve().is_relative_to(project):
            raise ValueError('Unsafe install target')
    if check_only:
        return {'changed':False,'checked_files':len(files)}
    path=Path(database)
    if not path.is_absolute():path=project/path
    if not path.is_file():raise ValueError('Existing database not found')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    backup=project/('backup-authenticated-core-code-'+stamp)
    backup.mkdir()
    subprocess.run([sys.executable,'-c','from nexus.farm_app.backup import backup_database; import sys; backup_database(sys.argv[1],sys.argv[2])',str(path),str(project/'backups')],cwd=project,check=True)
    originals={}
    for name in files:
        target=project/name
        originals[name]=target.exists()
        if target.exists():
            saved=backup/name;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
    changed=[]
    try:
        for name in files:
            target=project/name;target.parent.mkdir(parents=True,exist_ok=True)
            temporary=target.with_name(target.name+'.nexus-install')
            changed.append(name)
            try:
                shutil.copyfile(release/name,temporary)
                os.replace(temporary,target)
            finally:
                temporary.unlink(missing_ok=True)
    except Exception:
        for name in reversed(changed):
            target=project/name
            if originals[name]:shutil.copy2(backup/name,target)
            else:target.unlink(missing_ok=True)
        raise
    return {'changed':True,'installed_files':len(files),'source_backup':str(backup)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',required=True)
    parser.add_argument('--database',default='nexus-farm.sqlite3')
    parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args()
    try:
        result=install(Path(__file__).resolve().parent,args.project,args.database,args.check_only)
        print(json.dumps(result,indent=2))
        print('No migration or account change was applied. Stop the legacy 8080 server before starting --authenticated.')
    except (ValueError,OSError,subprocess.CalledProcessError) as error:
        parser.exit(1,'Install failed: '+str(error)+'\n')


if __name__=='__main__':
    main()
