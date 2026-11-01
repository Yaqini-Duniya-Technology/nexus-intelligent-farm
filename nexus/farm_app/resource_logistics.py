"""Traceability calculations and explicit, frozen links to existing case/cash records."""
from datetime import datetime,timezone,timedelta
from decimal import Decimal,ROUND_HALF_UP
from nexus.farm_app.operations_common import digest,table_names,LAGOS
EXTERNAL=('season','expense','observation','harvest')


def external(db,kind,rid):
    tables=table_names(db)
    if kind=='season' and 'crop_seasons' in tables:row=db.execute('SELECT * FROM crop_seasons WHERE id=?',(rid,)).fetchone()
    elif kind=='harvest' and {'harvests','crop_seasons'}<=tables:row=db.execute('SELECT h.*,s.field_id FROM harvests h JOIN crop_seasons s ON s.id=h.season_id WHERE h.id=?',(rid,)).fetchone()
    elif kind=='observation':row=db.execute('SELECT * FROM observations WHERE id=?',(rid,)).fetchone()
    elif kind=='expense' and {'season_transactions','crop_seasons'}<=tables:
        row=db.execute("SELECT t.*,s.field_id FROM season_transactions t JOIN crop_seasons s ON s.id=t.season_id WHERE t.id=? AND t.kind='expense'",(rid,)).fetchone()
    else:row=None
    if row is None:raise ValueError('Existing '+kind+' not found')
    return dict(row)


def normalize(kind,v):
    if kind in ('quote','purchase','delivery','dispatch') and Decimal(v['quantity'])<=0:raise ValueError('Use a positive quantity')
    if kind=='allocation' and Decimal(v['quantity'])==0:raise ValueError('Allocation must be nonzero')
    if kind=='dispatch':
        if v['status']=='completed' and not v['performed_at']:raise ValueError('Record actual dispatch time')
        if v['status']!='completed' and v['performed_at']:raise ValueError('Actual dispatch time requires completed status')
    return v


def freeze(db,current,kind,fid,source,v):
    captures={}
    key={'budget_scope':('season','season_id'),'expense_match':('expense','expense_id'),'case_link':('observation','observation_id')}.get(kind)
    if key:
        if source!='actual':raise ValueError('Links to existing seasons, expenses and observations require Actual source; keep practice separate')
        record=external(db,key[0],v[key[1]])
        if record.get('field_id')!=fid:raise ValueError('Selected '+key[0]+' must belong to the same field')
        captures[key[0]]={'record':record,'sha256':digest(record)}
    if kind=='case_link':
        target=current.get(v['resource_id'])
        if target is None or target['kind'] in ('contact','case_link') or target['field_id']!=fid or target['payload']['source']!=source:raise ValueError('Choose a same-field actual resource, excluding contacts and case links')
        captures['resource']={'record':target,'sha256':digest(target)}
    if kind=='stock_check':
        balance=Decimal(0)
        for e in current.values():
            x=e['payload']['values']
            if e['kind']=='movement' and x['supply_id']==v['supply_id']:
                balance+=Decimal(x['quantity'])*(-1 if x['direction']=='issue' else 1)
        captures['count_comparison']={'recorded_balance':format(balance,'f'),'counted':v['quantity'],'difference':format(Decimal(v['quantity'])-balance,'f'),'basis':'Recorded balance at entry time, not necessarily at the past count time. No adjustment posted.'}
    return captures


def check_captures(row):
    kind=row['kind'];p=row['payload'];captures=p.get('captures',{})
    if not isinstance(captures,dict):raise ValueError('Invalid captured resource context')
    for key in ('season','expense','observation','resource'):
        if key in captures:
            cap=captures[key]
            if not isinstance(cap,dict) or digest(cap.get('record'))!=cap.get('sha256'):raise ValueError('Captured '+key+' hash mismatch')
    expected={'budget_scope':('season','season_id'),'expense_match':('expense','expense_id'),'case_link':('observation','observation_id')}.get(kind)
    if expected:
        cap=captures.get(expected[0],{}).get('record',{})
        if p['source']!='actual' or cap.get('id')!=p['values'][expected[1]] or cap.get('field_id')!=row['field_id']:raise ValueError('Captured external association mismatch')
    if kind=='case_link':
        target=captures.get('resource',{}).get('record',{})
        if target.get('kind') in ('contact','case_link') or digest(target.get('payload'))!=target.get('content_sha256'):raise ValueError('Invalid frozen resource version')
        if target.get('record_id')!=p['values']['resource_id'] or target.get('field_id')!=row['field_id'] or target.get('payload',{}).get('source')!='actual':raise ValueError('Captured resource association mismatch')

    if kind=='expense_match':
        expense=captures['expense']['record']
        if expense.get('kind')!='expense' or type(expense.get('amount_kobo')) is not int or expense['amount_kobo']<=0:raise ValueError('Invalid frozen actual expense')
    if kind=='stock_check':
        comp=captures.get('count_comparison',{})
        try:
            if comp.get('counted')!=p['values']['quantity'] or Decimal(comp['counted'])-Decimal(comp['recorded_balance'])!=Decimal(comp['difference']):raise ValueError('Invalid frozen count comparison')
        except (KeyError,TypeError,ArithmeticError):raise ValueError('Invalid frozen count comparison') from None


def validate(current):
    lots={};allocated={};scopes={};matched=set()
    for root,e in current.items():
        v=e['payload']['values'];kind=e['kind']
        if kind=='batch':lots[root]=Decimal(0)
        if kind=='budget_scope' and v['status']=='active':
            if v['budget_id'] in scopes:raise ValueError('A budget may have only one active season scope; revise or withdraw the earlier scope')
            scopes[v['budget_id']]=e
    for root,e in current.items():
        kind=e['kind'];v=e['payload']['values']
        if kind=='allocation':
            lot=current[v['batch_id']]['payload']['values'];move=current[v['movement_id']]['payload']['values']
            if lot['supply_id']!=move['supply_id']:raise ValueError('Lot and movement must refer to the same supply item')
            qty=Decimal(v['quantity']);mqty=Decimal(move['quantity'])
            if qty*mqty<=0:raise ValueError('Allocation sign must match the selected movement quantity')
            allocated[v['movement_id']]=allocated.get(v['movement_id'],Decimal(0))+qty
            if abs(allocated[v['movement_id']])>abs(mqty):raise ValueError('Allocations exceed the saved movement quantity')
            lots[v['batch_id']]+=qty*(-1 if move['direction']=='issue' else 1)
        if kind=='expense_match' and v['status']=='active':
            if v['expense_id'] in matched:raise ValueError('This whole expense is already actively matched; withdraw or revise the earlier match')
            matched.add(v['expense_id']);line=current[v['budget_line_id']]['payload']['values'];scope=scopes.get(line['budget_id'])
            expense=e['payload']['captures']['expense']['record']
            if line['status']=='cancelled':raise ValueError('An active expense match cannot use a cancelled budget line')
            if scope is None or scope['payload']['values']['season_id']!=expense['season_id']:raise ValueError('Establish the budget season scope matching this expense before reconciling')
    if any(v<0 for v in lots.values()):raise ValueError('Allocated lot balance cannot be negative; allocate receipts before issues or correct the lot association')
    return lots,allocated


def options(db):
    tables=table_names(db);result={'season':[],'expense':[],'observation':[],'harvest':[]}
    if 'crop_seasons' in tables:result['season']=[dict(r) for r in db.execute('SELECT * FROM crop_seasons ORDER BY id DESC')]
    result['observation']=[dict(r) for r in db.execute('SELECT id,field_id,note FROM observations ORDER BY id DESC')]
    if {'season_transactions','crop_seasons'}<=tables:result['expense']=[dict(r) for r in db.execute("SELECT t.*,s.field_id FROM season_transactions t JOIN crop_seasons s ON s.id=t.season_id WHERE t.kind='expense' ORDER BY t.id DESC")]
    if {'harvests','crop_seasons'}<=tables:result['harvest']=[dict(r) for r in db.execute('SELECT h.*,s.field_id FROM harvests h JOIN crop_seasons s ON s.id=h.season_id ORDER BY h.id DESC')]
    return result


def report(db,current):
    lots,allocated=validate(current);today=datetime.now(timezone.utc).astimezone(LAGOS).date();result={'lots':[],'unallocated_movements':[],'reconciliation':[],'association_checks':[],'stock_counts':[],'quotes':[]}
    for root,e in current.items():
        v=e['payload']['values'];kind=e['kind'];base={'record_id':root,'field_id':e['field_id'],'source':e['payload']['source']}
        if kind=='batch':
            expiry=v['expiry_date'];days=None if expiry is None else (datetime.fromisoformat(expiry).date()-today).days
            result['lots'].append(base|dict(name=v['name'],supply_id=v['supply_id'],unit=current[v['supply_id']]['payload']['values']['unit'],allocated_balance=format(lots[root],'f'),status=v['status'],expiry_date=expiry,expiry_state='unknown' if days is None else 'expired' if days<0 else 'within_30_days' if days<=30 else 'later',days_to_expiry=days))
        if kind=='movement':result['unallocated_movements'].append(base|dict(supply_id=v['supply_id'],direction=v['direction'],quantity=v['quantity'],allocated=format(allocated.get(root,Decimal(0)),'f'),unallocated=format(Decimal(v['quantity'])-allocated.get(root,Decimal(0)),'f')))
        if kind=='stock_check':result['stock_counts'].append(base|e['payload']['captures']['count_comparison'])
        if kind=='quote':result['quotes'].append(base|dict(quoted_total_ngn=format((Decimal(v['quantity'])*Decimal(v['unit_ngn'])).quantize(Decimal('.01'),rounding=ROUND_HALF_UP),'f'),valid_until=v['valid_until'],validity='unknown' if v['valid_until'] is None else 'past_reported_validity' if v['valid_until']<today.isoformat() else 'within_reported_validity'))
        if kind=='budget':
            lines={r:x for r,x in current.items() if x['kind']=='budget_line' and x['payload']['values']['budget_id']==root};matches=[x for x in current.values() if x['kind']=='expense_match' and x['payload']['values']['status']=='active' and x['payload']['values']['budget_line_id'] in lines]
            amount=sum((Decimal(x['payload']['captures']['expense']['record']['amount_kobo'])/100 for x in matches),Decimal(0));planned=sum((Decimal(x['payload']['values']['amount_ngn']) for x in lines.values() if x['payload']['values']['status']!='cancelled'),Decimal(0))
            result['reconciliation'].append(base|dict(name=v['name'],planned_lines_ngn=format(planned,'f'),matched_expenses_ngn=format(amount,'f'),plan_minus_matched_ngn=format(planned-amount,'f'),matched_expense_count=len(matches),basis='Whole matched expense snapshots only; not all field expenditure.'))
        for key,cap in e['payload'].get('captures',{}).items():
            if key=='count_comparison':continue
            try:
                record=current.get(v['resource_id']) if key=='resource' else external(db,key,cap['record']['id'])
                matches=record is not None and digest(record)==cap['sha256']
                status='matches_frozen_copy' if matches else 'changed_since_link'
            except ValueError:status='current_record_missing'
            result['association_checks'].append(base|dict(kind=kind,target_kind=key,status=status,link_status=v.get('status'),frozen_sha256=cap['sha256']))
    return result


def capture(db,tables,observation_id):
    if 'resource_entries' not in tables:return None
    from nexus.farm_app.farm_resources import load,validate_links
    _,current=load(db);validate_links(current)
    links=[]
    for e in current.values():
        if e['kind']!='case_link' or e['payload']['values']['observation_id']!=observation_id or e['payload']['source']!='actual':continue
        target=current.get(e['payload']['values']['resource_id'])
        same=target is not None and digest(target)==e['payload']['captures']['resource']['sha256']
        observation=external(db,'observation',observation_id)
        dependencies=[]
        frozen=e['payload']['captures']['resource']['record']
        for key,cap in frozen.get('payload',{}).get('captures',{}).items():
            if key not in EXTERNAL:continue
            try:status='matches_frozen_copy' if digest(external(db,key,cap['record']['id']))==cap['sha256'] else 'changed_since_link'
            except ValueError:status='current_record_missing'
            dependencies.append({'kind':key,'status':status,'frozen_sha256':cap['sha256']})
        links.append(e|{'dependency_checks_at_capture':dependencies,'target_check_at_capture':'matches_frozen_copy' if same else 'changed_since_link','observation_check_at_capture':'matches_frozen_copy' if digest(observation)==e['payload']['captures']['observation']['sha256'] else 'changed_since_link'})
    return {'scope':'Explicit resource case links only. Contacts are not selectable targets. Current field resources are not silently substituted.','links':links,'limitations':['Each link preserves the resource version selected when saved. Later resource corrections require a new link revision.','Links indicate user-selected relevance, not causation or verified findings.','Withdrawn links remain recorded with their status. No lot or finance action is executed by capturing.']}
