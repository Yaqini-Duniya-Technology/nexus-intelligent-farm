"""Farm-authorised core workflows; all mutations share the permission transaction."""
import hmac
import uuid
from contextlib import closing, contextmanager
from nexus.farm_app import local_accounts as accounts, scoped_access as access
from nexus.farm_app.account_admin import event, operator
from nexus.farm_app.store import FarmStore
from nexus.farm_app.atomic import create_observation_atomic
from nexus.farm_app import field_inspections as inspections


class BoundConnection:
    def __init__(self, db):
        self.db = db

    def execute(self, sql, *args):
        # The outer permission transaction already owns the write lock.
        if sql.strip().upper() == 'BEGIN IMMEDIATE':
            if not self.db.in_transaction:
                raise RuntimeError('Permission transaction required')
            return self.db.execute('SELECT 1')
        return self.db.execute(sql, *args)


class BoundStore(FarmStore):
    def __init__(self, db, path):
        self.db = BoundConnection(db)
        self.path = path

    @contextmanager
    def connect(self):
        yield self.db


def selected_id(value):
    if type(value) is not int or value < 1:
        raise ValueError('Select a valid saved record')
    return value


def read(database, token, farm_id=None):
    with closing(accounts.connect(database)) as db, db:
        user = access.identity(db, token)
        farms = [dict(r) for r in db.execute('SELECT f.*,m.role FROM farms f JOIN nexus_farm_memberships m ON m.farm_id=f.id WHERE m.account_id=? ORDER BY f.id', (user['account_id'],))]
        result = {'username': user['username'], 'csrf': user['csrf'], 'farms': farms, 'fields': [], 'observations': [], 'tasks': [], 'actions': [], 'followups': [], 'can_write': False, 'can_create_farm': bool(db.execute('SELECT 1 FROM nexus_platform_admins WHERE account_id=?', (user['account_id'],)).fetchone()), 'limits': 'Latest 100 observations and tasks; up to 500 related actions/followups. No exports or attachments in this stage.'}
        if farm_id is None:
            return result
        role = access.require_farm(db, user['account_id'], selected_id(farm_id))
        result['can_write'] = role in ('owner','editor')
        result['fields'] = [dict(r) for r in db.execute('SELECT * FROM fields WHERE farm_id=? ORDER BY id', (farm_id,))]
        result['observations'] = [dict(r) for r in db.execute('SELECT o.* FROM observations o JOIN fields f ON f.id=o.field_id WHERE f.farm_id=? ORDER BY o.id DESC LIMIT 100', (farm_id,))]
        result['tasks'] = [dict(r) for r in db.execute('SELECT t.* FROM tasks t JOIN observations o ON o.id=t.observation_id JOIN fields f ON f.id=o.field_id WHERE f.farm_id=? ORDER BY t.id DESC LIMIT 100', (farm_id,))]
        for table, key in (('task_actions','actions'),('followups','followups')):
            result[key] = [dict(r) for r in db.execute('SELECT x.* FROM '+table+' x JOIN tasks t ON t.id=x.task_id JOIN observations o ON o.id=t.observation_id JOIN fields f ON f.id=o.field_id WHERE f.farm_id=? ORDER BY x.id DESC LIMIT 500', (farm_id,))]
        return result


def save_inspection(db, bound, actor, farm, data):
    inspections.initialize(bound)
    if 'submission_id' not in data:
        return inspections.save(bound, data)
    key = data['submission_id']
    try:
        if not isinstance(key, str) or str(uuid.UUID(key, version=4)) != key:
            raise ValueError()
    except ValueError:
        raise ValueError('Invalid inspection submission ID') from None
    if data.get('intent') not in ('new', 'correct'):
        raise ValueError('Choose new inspection or correction')
    request_hash = inspections.digest(data)
    db.execute('''CREATE TABLE IF NOT EXISTS nexus_inspection_receipts (
        account_id INTEGER NOT NULL REFERENCES nexus_accounts(id),
        farm_id INTEGER NOT NULL REFERENCES farms(id),
        submission_id TEXT NOT NULL,
        request_sha256 TEXT NOT NULL,
        inspection_id INTEGER NOT NULL REFERENCES field_inspections(id),
        PRIMARY KEY (account_id, farm_id, submission_id)
    )''')
    receipt = db.execute('''SELECT request_sha256,inspection_id FROM nexus_inspection_receipts
        WHERE account_id=? AND farm_id=? AND submission_id=?''', (actor, farm, key)).fetchone()
    if receipt:
        if receipt['request_sha256'] != request_hash:
            raise inspections.InspectionConflict('This save ID is already associated with a different submission')
        return {'id': receipt['inspection_id'], 'reused': True}
    saved = inspections.save(bound, data, deduplicate=False)
    db.execute('INSERT INTO nexus_inspection_receipts VALUES (?,?,?,?,?)',
               (actor, farm, key, request_hash, saved['id']))
    return saved


def change(database, token, csrf, data):
    if not isinstance(data, dict):
        raise ValueError('Expected an object')
    with closing(accounts.connect(database)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        user = access.identity(db, token)
        if not isinstance(csrf, str) or not hmac.compare_digest(csrf.encode(), user['csrf'].encode()):
            raise access.AccessError('Refresh before saving')
        actor = user['account_id']
        op = data.get('operation')
        if op not in ('farm','field','observation','approve','action','followup','inspection'):
            raise ValueError('This workflow is not enabled in the authenticated workspace')
        bound = BoundStore(db, database)
        if op == 'farm':
            operator(db, actor)
            farm = bound.create('farms', data)
            db.execute("INSERT INTO nexus_farm_memberships VALUES (?,?,'owner')", (actor, farm))
            result = {'farm_id': farm}
        else:
            farm = selected_id(data.get('farm_id'))
            access.require_farm(db, actor, farm, write=True)
            if op == 'field':
                result = {'field_id': bound.create('fields', data)}
            elif op == 'inspection':
                observation = selected_id(data.get('observation_id'))
                if not db.execute('SELECT 1 FROM observations o JOIN fields f ON f.id=o.field_id WHERE o.id=? AND f.farm_id=?', (observation, farm)).fetchone():
                    raise access.AccessError()
                result = save_inspection(db, bound, actor, farm, data)
                if result['reused']:
                    return result
            elif op == 'observation':
                field = selected_id(data.get('field_id'))
                if not db.execute('SELECT 1 FROM fields WHERE id=? AND farm_id=?', (field, farm)).fetchone():
                    raise access.AccessError()
                result = create_observation_atomic(bound, data)
            else:
                task = selected_id(data.get('task_id'))
                if not db.execute('SELECT 1 FROM tasks t JOIN observations o ON o.id=t.observation_id JOIN fields f ON f.id=o.field_id WHERE t.id=? AND f.farm_id=?', (task, farm)).fetchone():
                    raise access.AccessError()
                if op == 'approve':
                    if data.get('review_confirmed') is not True:
                        raise ValueError('Confirm that you reviewed the observation and task')
                    bound.transition(task, 'approve')
                elif op == 'action':
                    bound.record_action(task, data)
                else:
                    bound.record_followup(task, data)
                result = {'task_id': task}
        event(db, 'workspace_'+op, actor=actor, affected=actor, farm=farm, summary='Authenticated core workflow saved: '+op)
        return result


def read_inspections(database, token, farm_id, observation_id=None):
    """One read transaction; never call the legacy all-farm state reader."""
    with closing(accounts.connect(database)) as db, db:
        db.execute('BEGIN')
        user = access.identity(db, token)
        farm = selected_id(farm_id)
        role = access.require_farm(db, user['account_id'], farm)
        args = [farm]
        sql = 'SELECT o.*,f.name AS field_name FROM observations o JOIN fields f ON f.id=o.field_id WHERE f.farm_id=?'
        if observation_id is not None:
            observation_id = selected_id(observation_id)
            if not db.execute('SELECT 1 FROM observations o JOIN fields f ON f.id=o.field_id WHERE o.id=? AND f.farm_id=?', (observation_id,farm)).fetchone():
                raise access.AccessError()
            sql += ' AND o.id=?'
            args.append(observation_id)
        observations = [dict(row) for row in db.execute(sql+' ORDER BY o.id DESC',args)]
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        history = []
        for observation in observations:
            # Hash only the original row, excluding the joined display label.
            raw = {k:v for k,v in observation.items() if k!='field_name'}
            history.extend(inspections.capture_history(db,tables,raw) or [])
            observation['selection_hash'] = inspections.digest(raw)
        return {'username':user['username'],'csrf':user['csrf'],'farm_id':farm,
                'can_write':role in ('owner','editor'),'observations':observations,
                'history':sorted(history,key=lambda row:row['id'],reverse=True)}
