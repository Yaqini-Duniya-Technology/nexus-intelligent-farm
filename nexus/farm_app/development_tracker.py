"""Read-only validator/report for the project roadmap. Never opens a farm database."""
import argparse,json
from pathlib import Path
from collections import Counter
STATUSES={'Planned','In Progress','Blocked','Tested','Completed'}
COUNTS=dict(A=15,B=20,C=20,D=15,E=15,F=15,G=15,H=15,I=10,J=10)

def read(path):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('tracker_version')!='nexus-roadmap-v1':raise ValueError('Unsupported tracker version')
    rows=data.get('upgrades');expected={f'NEXUS-UPG-{n:03}' for n in range(1,151)}
    if not isinstance(rows,list) or any(not isinstance(r,dict) for r in rows) or len(rows)!=150 or {r.get('id') for r in rows}!=expected:raise ValueError('Tracker requires exactly 150 distinct numbered IDs')
    if dict(Counter(r.get('workstream') for r in rows))!=COUNTS:raise ValueError('Workstream counts do not match the 150-item scope')
    byid={r['id']:r for r in rows}
    for r in rows:
        if r.get('status') not in STATUSES or r.get('priority') not in ('Critical','High','Medium','Future'):raise ValueError('Invalid status or priority')
        for key in ('feature','purpose','benefit','phase'):
            if not isinstance(r.get(key),str) or not r[key].strip():raise ValueError('Missing '+key)
        for key in ('acceptance_criteria','tests','documentation'):
            if not isinstance(r.get(key),list) or not r[key] or any(not isinstance(v,str) or not v.strip() for v in r[key]):raise ValueError('Missing '+key)
        if not isinstance(r.get('dependencies'),list) or any(d not in byid or d==r['id'] for d in r['dependencies']):raise ValueError('Invalid dependency')
        if r['status'] in ('Tested','Completed') and (not r.get('verification') or not r.get('git_reference')):raise ValueError('Verified statuses require evidence and a Git reference')
        if r['status']=='Blocked' and not r.get('requirements'):raise ValueError('Blocked items require a stated external requirement')
    seen=set();active=set()
    def visit(uid):
        if uid in active:raise ValueError('Dependency cycle')
        if uid in seen:return
        active.add(uid)
        for dep in byid[uid]['dependencies']:visit(dep)
        active.remove(uid);seen.add(uid)
    for uid in byid:visit(uid)
    return data


def summary(data):
    rows=data['upgrades']
    return dict(tracker_version=data['tracker_version'],total=len(rows),status_counts=dict(Counter(r['status'] for r in rows)),workstream_counts=dict(Counter(r['workstream'] for r in rows)),limitations=['Status is project tracking, not proof of production readiness. Follow the recorded acceptance evidence.','Planned and Blocked entries are not implemented features.'])


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--file',default='docs/development/roadmap.json');parser.add_argument('--status',choices=sorted(STATUSES));parser.add_argument('--workstream',choices=sorted(COUNTS));parser.add_argument('--details',action='store_true');args=parser.parse_args()
    try:
        data=read(args.file);result=summary(data)
        if args.details:result['upgrades']=[r for r in data['upgrades'] if (not args.status or r['status']==args.status) and (not args.workstream or r['workstream']==args.workstream)]
        print(json.dumps(result,indent=2,ensure_ascii=False))
    except (ValueError,OSError,TypeError,KeyError) as error:parser.exit(1,'Tracker check failed: '+str(error)+'\n')

if __name__=='__main__':main()
