"""Local backup catalogue; user-triggered new-copy recovery, never active DB replacement."""
import io
import json
from datetime import datetime,timezone
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from nexus.farm_app import operations_recovery as recovery


def directory(database):return Path(database).expanduser().resolve().parent/'backups'


def selected(database,name):
    if not isinstance(name,str) or Path(name).name!=name or not name.endswith('.sqlite3') or '/' in name or '\\' in name:
        raise ValueError('Choose a backup filename from the catalogue')
    root=directory(database).resolve();target=root/name
    if target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(root):raise ValueError('Backup file not found')
    return target


def catalogue(database):
    root=directory(database);files=[]
    if root.is_dir():
        for path in sorted(root.glob('*.sqlite3'),key=lambda p:p.stat().st_mtime,reverse=True)[:100]:
            if path.is_symlink():continue
            files.append({'name':path.name,'size_bytes':path.stat().st_size,
                          'modified_at':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat(),
                          'manifest_available':path.with_suffix(path.suffix+'.manifest.json').is_file()})
    return {'backups':files,'limit':100,'notice':'Catalogue lists local copies; verify one before relying on it.'}


def verify(database,name):return recovery.verify(selected(database,name))


def create(database,confirm):
    if confirm is not True:raise ValueError('Explicitly request creation of a local backup')
    return recovery.backup(database,directory(database))


def portable(database,name):
    path=selected(database,name);checked=recovery.verify(path)
    if not checked['ok']:raise ValueError('Backup checks failed; download was not created')
    if path.stat().st_size>100*1024*1024:raise ValueError('Backup is over 100 MB; use the local backup file directly')
    output=io.BytesIO()
    with ZipFile(output,'w',ZIP_DEFLATED) as zipped:
        zipped.write(path,path.name)
        manifest=path.with_suffix(path.suffix+'.manifest.json')
        if manifest.is_file():zipped.write(manifest,manifest.name)
        zipped.writestr('CHECKS.json',json.dumps(checked,indent=2))
    return output.getvalue()


def restore_copy(database,name,confirm):
    if confirm is not True:raise ValueError('Explicitly confirm recovery to a NEW file')
    source=selected(database,name)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    target=Path(database).resolve().parent/'recovered'/('nexus-recovered-'+stamp+'.sqlite3')
    return recovery.restore(source,target,commit=True)
