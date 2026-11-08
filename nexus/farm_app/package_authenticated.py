"""Build a source-only checked updater in CI; excludes databases and private files."""
import hashlib,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
TARGET=ROOT/'dist/nexus-inspection-reliability'
TARGET.mkdir(parents=True,exist_ok=True)
for path in (ROOT/'nexus/farm_app').iterdir():
    if path.is_file() and path.suffix in ('.py','.html','.css','.js','.json','.cjs'):
        dest=TARGET/'nexus/farm_app'/path.name
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,dest)
for folder in (ROOT/'docs/development',ROOT/'docs/security'):
    if folder.exists():
        shutil.copytree(folder,TARGET/folder.relative_to(ROOT),dirs_exist_ok=True)
for path in (ROOT/'docs/DEPLOYMENT_CONTROLS.md',ROOT/'docs/RELIABILITY_GUIDE.md'):
    if path.exists():
        shutil.copy2(path,TARGET/'docs'/path.name)
(TARGET/'nexus/__init__.py').write_text('',encoding='utf-8')
shutil.copy2(ROOT/'nexus/farm_app/install_authenticated.py',TARGET/'install_workspace.py')
shutil.copy2(ROOT/'docs/development/INSPECTION-RELIABILITY.md',TARGET/'INSTALL.md')
files={str(p.relative_to(TARGET)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for folder in (TARGET/'nexus/farm_app',TARGET/'docs') for p in sorted(folder.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}
(TARGET/'RELEASE.json').write_text(json.dumps({'release':'nexus-authenticated-core-v1','application_release':'nexus-inspection-reliability-v1','files':files},indent=2),encoding='utf-8')
print('Source-only updater packaged:',len(files),'verified files')
