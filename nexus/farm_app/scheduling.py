from datetime import datetime, timezone


def initialize_scheduling(store):
    with store.connect() as db:
        db.execute('''
            CREATE TABLE IF NOT EXISTS followup_schedules (
                id INTEGER PRIMARY KEY,
                task_id INTEGER NOT NULL REFERENCES tasks(id),
                due_at TEXT NOT NULL,
                note TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'scheduled',
                closed_at TEXT,
                followup_id INTEGER REFERENCES followups(id)
            )
        ''')
        db.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_followup_schedule
            ON followup_schedules(task_id) WHERE status = 'scheduled'
        ''')


def timestamp(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Provide a date and time')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('Invalid date and time') from None
    if result.tzinfo is None:
        raise ValueError('Date and time must include a timezone')
    return result.astimezone(timezone.utc)


def positive_id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError('Invalid record ID')
    return value


def schedule_state(store, state):
    now = datetime.now(timezone.utc)
    with store.connect() as db:
        rows = [dict(row) for row in db.execute(
            'SELECT * FROM followup_schedules ORDER BY due_at, id'
        )]
    for row in rows:
        row['timing'] = (
            'overdue' if timestamp(row['due_at']) <= now else 'upcoming'
        ) if row['status'] == 'scheduled' else row['status']
    state['followup_schedules'] = rows
    state['schedule_clock'] = now.isoformat()
    return state


def save_schedule(store, data):
    task_id = positive_id(data.get('task_id'))
    due = timestamp(data.get('due_at'))
    note = data.get('note')
    if not isinstance(note, str) or not note.strip() or len(note) > 3000:
        raise ValueError('Describe the planned follow-up (maximum 3000 characters)')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        now = datetime.now(timezone.utc)
        if due <= now:
            raise ValueError('Choose a future follow-up time')
        task = db.execute('SELECT status FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not task or task['status'] != 'completed':
            raise ValueError('Complete the task before scheduling a follow-up')
        if db.execute("SELECT id FROM followup_schedules WHERE task_id=? AND status='scheduled'", (task_id,)).fetchone():
            raise ValueError('This task already has an active follow-up; cancel it before replacing it')
        db.execute('''INSERT INTO followup_schedules(task_id,due_at,note,created_at)
                      VALUES (?,?,?,?)''',
                   (task_id, due.isoformat(), note.strip(), now.isoformat()))


def close_schedule(store, data):
    schedule_id = positive_id(data.get('id'))
    action = data.get('action')
    if action not in ('complete', 'cancel'):
        raise ValueError('Choose complete or cancel')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        schedule = db.execute('SELECT * FROM followup_schedules WHERE id=?', (schedule_id,)).fetchone()
        if not schedule or schedule['status'] != 'scheduled':
            raise ValueError('Active follow-up schedule not found')
        followup_id = None
        if action == 'complete':
            followup_id = positive_id(data.get('followup_id'))
            followup = db.execute('SELECT * FROM followups WHERE id=?', (followup_id,)).fetchone()
            if not followup or followup['task_id'] != schedule['task_id']:
                raise ValueError('Select evidence from this task')
            if (timestamp(followup['observed_at']) < timestamp(schedule['created_at'])
                    or timestamp(followup['recorded_at']) < timestamp(schedule['created_at'])):
                raise ValueError('Select follow-up evidence observed and saved after this schedule was created')
            task = db.execute('SELECT * FROM tasks WHERE id=?', (schedule['task_id'],)).fetchone()
            observation = db.execute('SELECT * FROM observations WHERE id=?', (task['observation_id'],)).fetchone()
            recorded_action = db.execute('SELECT * FROM task_actions WHERE task_id=?', (task['id'],)).fetchone()
            assessment = store._assess_followup(
                dict(followup), dict(task), dict(observation) if observation else None,
                dict(recorded_action) if recorded_action else None,
            )
            if not assessment['eligible']:
                raise ValueError('Selected follow-up evidence is excluded from the evidence summary')
        db.execute('''UPDATE followup_schedules SET status=?,closed_at=?,followup_id=?
                      WHERE id=?''',
                   ('completed' if action == 'complete' else 'cancelled',
                    datetime.now(timezone.utc).isoformat(), followup_id, schedule_id))
