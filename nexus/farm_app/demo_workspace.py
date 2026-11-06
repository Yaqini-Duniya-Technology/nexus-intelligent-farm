"""Create a new isolated DEMO workspace; never accepts an existing directory."""
import argparse
import getpass
import json
from pathlib import Path
from nexus.farm_app.store import FarmStore
from nexus.farm_app.audit import initialize_audit
from nexus.farm_app.deployment_controls import migrate
from nexus.farm_app import local_accounts, field_inspections


def create(directory,password):
    if not isinstance(password,str) or not 12<=len(password)<=1024:
        raise ValueError('Use a private demo password of 12–1024 characters')
    directory=Path(directory).expanduser().resolve()
    directory.mkdir(parents=True,exist_ok=False)
    path=directory/'nexus-farm.sqlite3'
    store=FarmStore(path);initialize_audit(store);field_inspections.initialize(store)
    for index in (1,2):
        farm=store.create('farms',{'name':f'DEMO farm {index}','location':'DEMO — not an actual farm'})
        store.create('fields',{'farm_id':farm,'name':f'DEMO field {index}','crop':'maize'})
    migrate(path,directory/'backups')
    for username,role,farm in [('demo-owner','owner',1),('demo-viewer','viewer',1),('demo-other','owner',2)]:
        uid=local_accounts.create(path,username,password);local_accounts.grant(path,uid,farm,role)
    return {'database':str(path),'accounts':['demo-owner','demo-viewer','demo-other'],'limitations':'Synthetic workspace only. No observations prefilled; never mix with actual farm evidence.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',required=True);args=parser.parse_args()
    password=getpass.getpass('Private DEMO password (12+ characters): ')
    if password!=getpass.getpass('Repeat DEMO password: '):parser.error('Passwords differ')
    try:result=create(args.directory,password)
    except (ValueError,OSError) as error:parser.exit(1,f'Demo creation failed: {error}\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
