"""Human-planned work with append-only, hashed event history."""
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from nexus.farm_app.operations_common import canonical, digest, positive, word, day, instant, LAGOS

STATUSES = ('planned', 'in_progress', 'blocked', 'done', 'cancelled')
TRANSITIONS = {'start': (('planned',), 'in_progress'),
               'block': (('planned', 'in_progress'), 'blocked'),
               'resume': (('blocked',), 'in_progress'),
               'complete': (('in_progress',), 'done'),
               'cancel': (('planned', 'blocked', 'in_progress'), 'cancelled')}


def initialize(store):
    with store.connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS work_orders(
            id INTEGER PRIMARY KEY,field_id INTEGER NOT NULL REFERENCES fields(id),
            observation_id INTEGER REFERENCES observations(id),created_at TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,payload TEXT NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS work_order_events(
            id INTEGER PRIMARY KEY,work_order_id INTEGER NOT NULL REFERENCES work_orders(id),
            previous_id INTEGER REFERENCES work_order_events(id),recorded_at TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,payload TEXT NOT NULL)''')
        db.execute('CREATE INDEX IF NOT EXISTS work_events_order ON work_order_events(work_order_id,id)')


def plan(data):
    result = {key: word(data.get(key), key.replace('_',' '), limit) for key,limit in
              [('title',300),('owner',200),('constraints',3000),('resources',3000)]}
    if data.get('priority') not in ('routine','prompt','low'):
        raise ValueError('Choose routine, prompt or low priority')
    result['priority'] = data['priority']
    result['due_date'] = day(data.get('due_date')).isoformat()
    amount = data.get('estimated_ngn')
    if amount is None or amount == '':
        result['estimated_kobo'] = None
    else:
        try:
            if isinstance(amount, bool):
                raise ValueError()
            decimal = Decimal(str(amount))
            if not decimal.is_finite() or decimal < 0 or decimal > Decimal('1000000000') or decimal*100 != (decimal*100).to_integral_value():
                raise ValueError()
            result['estimated_kobo'] = int(decimal*100)
        except (InvalidOperation, ValueError):
            raise ValueError('Estimated cost must be a nonnegative amount with at most two decimal places') from None
    checklist = data.get('checklist', [])
    if not isinstance(checklist, list) or len(checklist) > 30:
        raise ValueError('Use at most 30 checklist items')
    checklist = [word(item, 'checklist item', 300) for item in checklist]
    if len(set(checklist)) != len(checklist):
        raise ValueError('Checklist items must be distinct')
    result['checklist'] = [{'label': item, 'done': False} for item in checklist]
    result['status'] = 'planned'
    result['actual_work'] = None
    return result


def validate_state(state):
    if not isinstance(state,dict) or state.get('status') not in STATUSES or state.get('priority') not in ('routine','prompt','low'):
        raise ValueError('Invalid saved work state')
    for key,limit in [('title',300),('owner',200),('resources',3000),('constraints',3000)]:
        word(state.get(key),key,limit)
    day(state.get('due_date'))
    amount=state.get('estimated_kobo')
    if amount is not None and (type(amount) is not int or not 0<=amount<=100000000000):
        raise ValueError('Invalid saved estimated cost')
    items=state.get('checklist')
    if not isinstance(items,list) or len(items)>30:
        raise ValueError('Invalid saved checklist')
    labels=[]
    for item in items:
        if not isinstance(item,dict) or type(item.get('done')) is not bool:
            raise ValueError('Invalid saved checklist item')
        labels.append(word(item.get('label'),'checklist item',300))
    if len(labels)!=len(set(labels)):
        raise ValueError('Duplicate saved checklist item')
    if state['status']=='done':
        word(state.get('actual_work'),'actual work')
        if any(not item['done'] for item in items):
            raise ValueError('Completed work has unfinished checklist items')


def history(db, oid):
    row = db.execute('SELECT * FROM work_orders WHERE id=?', (oid,)).fetchone()
    if row is None:
        raise ValueError('Work order not found')
    order = dict(row)
    order['payload'] = json.loads(order['payload'])
    if digest(order['payload']) != order['content_sha256']:
        raise ValueError('Work order hash mismatch')
    p = order['payload']
    if (p.get('version') != 'work-order-v1' or p.get('field_id') != order['field_id']
            or p.get('observation_id') != order['observation_id']):
        raise ValueError('Inconsistent work order reference')
    positive(p.get('field_id'),'field ID')
    if p.get('observation_id') is not None:positive(p['observation_id'],'observation ID')
    current = p['state']
    validate_state(current)
    previous, previous_hash = None, order['content_sha256']
    events = []
    for raw in db.execute('SELECT * FROM work_order_events WHERE work_order_id=? ORDER BY id', (oid,)):
        event = dict(raw)
        event['payload'] = json.loads(event['payload'])
        data = event['payload']
        if (digest(data) != event['content_sha256'] or event['previous_id'] != previous
                or data.get('previous_sha256') != previous_hash or data.get('work_order_id') != oid):
            raise ValueError('Work order history hash or chain mismatch')
        current = data['state']
        validate_state(current)
        previous, previous_hash = event['id'], event['content_sha256']
        events.append(event)
    return {**order, 'state': current, 'events': events, 'base_id': previous, 'state_hash': previous_hash}


def state(store):
    with store.connect() as db:
        db.execute('BEGIN')
        fields = [dict(r) for r in db.execute('SELECT * FROM fields ORDER BY id')]
        observations = [dict(r) for r in db.execute('SELECT id,field_id,note FROM observations ORDER BY id DESC')]
        orders = [history(db, r[0]) for r in db.execute('SELECT id FROM work_orders ORDER BY id DESC')]
        today = datetime.now(timezone.utc).astimezone(LAGOS).date()
        for order in orders:
            d = day(order['state']['due_date'])
            order['timing'] = 'closed' if order['state']['status'] in ('done','cancelled') else 'overdue' if d < today else 'today' if d == today else 'upcoming'
        return {'fields': fields, 'observations': observations, 'orders': orders}


def create(store, data):
    fid = positive(data.get('field_id'), 'field ID')
    oid = data.get('observation_id')
    if oid is not None:
        positive(oid, 'observation ID')
    reporter = word(data.get('reporter'), 'reporter', 200)
    initial = plan(data)
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT id FROM fields WHERE id=?',(fid,)).fetchone() is None:
            raise ValueError('Field not found')
        if oid is not None:
            obs = db.execute('SELECT field_id FROM observations WHERE id=?',(oid,)).fetchone()
            if obs is None or obs[0] != fid:
                raise ValueError('Observation must belong to the selected field')
        payload = {'version':'work-order-v1','field_id':fid,'observation_id':oid,'reporter':reporter,'state':initial}
        hashed = digest(payload)
        same = db.execute('SELECT id FROM work_orders WHERE content_sha256=? ORDER BY id DESC', (hashed,)).fetchone()
        if same:
            return {'id':same[0], 'reused':True}
        cursor=db.execute('INSERT INTO work_orders(field_id,observation_id,created_at,content_sha256,payload) VALUES(?,?,?,?,?)',
                          (fid,oid,datetime.now(timezone.utc).isoformat(),hashed,canonical(payload)))
        return {'id':cursor.lastrowid, 'reused':False}


def change(store,data):
    oid = positive(data.get('work_order_id'), 'work order ID')
    actor = word(data.get('reporter'), 'reporter', 200)
    note = word(data.get('note'), 'work note / change reason')
    action = data.get('action')
    if action not in (*TRANSITIONS, 'revise', 'checklist'):
        raise ValueError('Choose a valid work action')
    performed = instant(data.get('performed_at') or datetime.now(timezone.utc).isoformat())
    if performed > datetime.now(timezone.utc):
        raise ValueError('Performed time cannot be in the future')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        order = history(db, oid)
        if performed < instant(order['created_at']):
            raise ValueError('Work event cannot predate order creation')
        base = data.get('base_id')
        if base is not None:
            positive(base, 'base event ID')
        # Stable request fingerprints allow safe retries of the same stale request.
        fingerprint = digest({key:value for key,value in data.items() if key != 'performed_at'} | {'performed_at':data.get('performed_at')})
        same = next((e for e in order['events'] if e['payload'].get('request_sha256') == fingerprint),None)
        if same:
            return {'id':same['id'],'reused':True}
        if base != order['base_id'] or data.get('state_hash') != order['state_hash']:
            raise ValueError('Work order changed; refresh before saving')
        if order['events'] and performed < instant(order['events'][-1]['payload']['performed_at']):
            raise ValueError('Work event cannot predate the previous saved work event')
        current = json.loads(canonical(order['state']))
        if action in TRANSITIONS:
            allowed, target = TRANSITIONS[action]
            if current['status'] not in allowed:
                raise ValueError('This transition is not allowed from '+current['status'])
            current['status'] = target
            if action == 'complete':
                if any(not item['done'] for item in current['checklist']):
                    raise ValueError('Finish the checklist before recording completion')
                current['actual_work'] = note
        elif action == 'revise':
            if current['status'] in ('done','cancelled'):
                raise ValueError('Closed orders retain their saved plan; create a new order')
            revised = plan(data)
            revised['status'] = current['status']
            existing = {item['label']:item['done'] for item in current['checklist']}
            for item in revised['checklist']:
                item['done'] = existing.get(item['label'],False)
            current = revised
        else:
            if current['status'] in ('done','cancelled'):
                raise ValueError('Closed order checklist cannot be changed')
            done = data.get('checked')
            if not isinstance(done,list) or len(done)!=len(current['checklist']) or any(type(v) is not bool for v in done):
                raise ValueError('Submit one checkbox value per checklist item')
            for item,value in zip(current['checklist'],done):
                item['done']=value
        payload = {'version':'work-event-v1','work_order_id':oid,'previous_sha256':order['state_hash'],
                   'action':action,'reporter':actor,'note':note,'performed_at':performed.isoformat(),
                   'request_sha256':fingerprint,'state':current}
        cursor=db.execute('INSERT INTO work_order_events(work_order_id,previous_id,recorded_at,content_sha256,payload) VALUES(?,?,?,?,?)',
                          (oid,base,datetime.now(timezone.utc).isoformat(),digest(payload),canonical(payload)))
        return {'id':cursor.lastrowid,'reused':False}


def capture_for_observation(db,tables,observation_id):
    if not {'work_orders','work_order_events'} <= tables:
        return None
    return [history(db,r[0]) for r in db.execute('SELECT id FROM work_orders WHERE observation_id=? ORDER BY id DESC',(observation_id,))]
