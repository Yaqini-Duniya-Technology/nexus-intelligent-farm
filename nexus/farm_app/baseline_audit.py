"""Read-only source inventory and optional local database diagnostics. No farm text exported."""
import argparse
import ast
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from nexus.farm_app.deployment_controls import inspect

RELEASE = 'nexus-baseline-inspections-v1'
ROOT = Path(__file__).resolve().parents[2]


def inventory(root=ROOT):
    modules=[]
    for path in sorted((root/'nexus/farm_app').glob('*.py')):
        if path.name.startswith('test_'):
            continue
        source=path.read_text(encoding='utf-8-sig'); tree=ast.parse(source)
        literals=[node.value for node in ast.walk(tree) if isinstance(node,ast.Constant) and isinstance(node.value,str)]
        routes=sorted({s for s in literals if re.fullmatch(r'/[a-zA-Z0-9_./?-]+',s)})
        tables=sorted({m.group(1) for s in literals for m in re.finditer(r'\b(?:FROM|JOIN|INTO|UPDATE|CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?)\s+([a-zA-Z_][a-zA-Z_0-9]*)',s,re.I)})
        modules.append({'module':path.stem,'command':any(isinstance(n,ast.FunctionDef) and n.name=='main' for n in tree.body),'route_literals':routes,'table_references':tables,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    return {'release':RELEASE,'scope':'Static candidate inventory, not proof of route reachability or feature completion. Dynamic SQL/routes require manual review.',
            'modules':modules,'authenticated_routes':['/','/workspace','/api/workspace','/field-inspections','/api/field-inspections','/api/session','/api/login','/api/logout','/admin','/api/admin'],
            'authenticated_boundary':'Only explicit authenticated handler and account-pilot allowlists. Legacy operational routes are not delegated.'}


def database_report(path):
    path=Path(path).expanduser().resolve()
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        tables=[row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        def quote(name):return '"'+name.replace('"','""')+'"'
        schema={name:{'columns':[{'name':r[1],'type':r[2],'required':bool(r[3]),'primary_key':bool(r[5])} for r in db.execute('PRAGMA table_info('+quote(name)+')')],
                      'foreign_keys':[{'table':r[2],'from':r[3],'to':r[4]} for r in db.execute('PRAGMA foreign_key_list('+quote(name)+')')],
                      'rows':db.execute('SELECT count(*) FROM '+quote(name)).fetchone()[0]} for name in tables}
        return {'resolved_database':str(path),'integrity':db.execute('PRAGMA integrity_check').fetchone()[0],
                'foreign_key_issue_count':len(db.execute('PRAGMA foreign_key_check').fetchall()),
                'pending_migrations':[m[0] for m in inspect(db)],'tables':schema,
                'limit':'This is the selected file, not proof that a running server uses it. No record text, hashes, passwords or tokens are included.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',help='Optional existing file, opened read-only; keep report private because it includes its path and counts')
    args=parser.parse_args();result=inventory()
    if args.database:
        try:result['database']=database_report(args.database)
        except (ValueError,sqlite3.Error) as error:parser.exit(1,f'Audit failed: {error}\n')
    print(json.dumps(result,indent=2,ensure_ascii=False))


if __name__=='__main__':main()
