"""Season operations inside the authenticated workspace's farm transaction."""
import json
from datetime import datetime, timezone

from nexus.farm_app import observation_seasons as context, seasons
from nexus.farm_app.field_inspections import InspectionConflict
from nexus.farm_app.scoped_access import AccessError
from nexus.farm_app.season_context import validate_entry


def read(db, farm):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    fields = [dict(r) for r in db.execute('SELECT * FROM fields WHERE farm_id=? ORDER BY id', (farm,))]
    observations = []
    raw = {}
    for row in db.execute('''SELECT o.*,f.name AS field_name FROM observations o
            JOIN fields f ON f.id=o.field_id WHERE f.farm_id=? ORDER BY o.id DESC''', (farm,)):
        observation = dict(row)
        raw[row['id']] = {k:v for k,v in observation.items() if k != 'field_name'}
        observation['selection_hash'] = context.digest(raw[row['id']])
        observations.append(observation)
    saved = [dict(r) for r in db.execute('''SELECT s.* FROM crop_seasons s
        JOIN fields f ON f.id=s.field_id WHERE f.farm_id=? ORDER BY s.id DESC''', (farm,))] if 'crop_seasons' in tables else []
    owned = {s['id']:s for s in saved}
    for season in saved:
        season['selection_hash'] = context.digest(season)
    history = []
    if 'observation_season_history' in tables:
        for row in db.execute('''SELECT h.* FROM observation_season_history h
                JOIN observations o ON o.id=h.observation_id JOIN fields f ON f.id=o.field_id
                WHERE f.farm_id=? ORDER BY h.id DESC''', (farm,)):
            item = {'id':row['id'], 'observation_id':row['observation_id'], 'recorded_at':row['recorded_at']}
            try:
                entry = dict(row)
                entry['payload'] = json.loads(entry['payload'])
                observation = raw[row['observation_id']]
                validate_entry(entry, observation)
                sid = row['season_id']
                if sid is not None and (sid not in owned or owned[sid]['field_id'] != observation['field_id']):
                    raise ValueError('Unavailable season')
                p = entry['payload']
                item.update(status='linked' if sid is not None else 'unknown',
                            season=p['season_at_capture'], growth_stage=p['growth_stage'],
                            reporter=p['reporter'], basis=p['basis'], reason=p['reason'])
            except (ValueError, TypeError, KeyError):
                # Legacy links can become invalid if a season is moved. Do not disclose the old payload.
                item['status'] = 'unavailable'
            history.append(item)
    harvests = [dict(r) for r in db.execute('''SELECT h.season_id,h.harvested_at,h.quantity_kg,h.area_ha
        FROM harvests h JOIN crop_seasons s ON s.id=h.season_id
        JOIN fields f ON f.id=s.field_id WHERE f.farm_id=?''', (farm,))] if {'harvests','crop_seasons'} <= tables else []
    revisions = []
    if {'nexus_season_revisions','crop_seasons'} <= tables:
        for row in db.execute('''SELECT r.season_id,r.recorded_at,r.before_json,r.after_json
                FROM nexus_season_revisions r JOIN crop_seasons s ON s.id=r.season_id
                JOIN fields f ON f.id=s.field_id
                WHERE r.farm_id=? AND f.farm_id=? AND r.field_id=s.field_id ORDER BY r.id DESC''', (farm,farm)):
            revisions.append({'season_id':row['season_id'],'recorded_at':row['recorded_at'],
                              'before':json.loads(row['before_json']),'after':json.loads(row['after_json'])})
    return dict(fields=fields, observations=observations, seasons=saved, history=history,
                harvests=harvests, revisions=revisions, stages=list(context.STAGES))


def save(db, bound, farm, data):
    seasons.initialize_seasons(bound)
    if data['operation'] == 'season_context':
        observation_id = context.positive(data.get('observation_id'), 'observation')
        observation = db.execute('''SELECT o.field_id FROM observations o
            JOIN fields f ON f.id=o.field_id WHERE o.id=? AND f.farm_id=?''', (observation_id,farm)).fetchone()
        if observation is None:
            raise AccessError()
        sid = data.get('season_id')
        if sid is not None:
            context.positive(sid, 'season')
            season = db.execute('''SELECT s.field_id FROM crop_seasons s
                JOIN fields f ON f.id=s.field_id WHERE s.id=? AND f.farm_id=?''', (sid,farm)).fetchone()
            if season is None:
                raise AccessError()
            if season['field_id'] != observation['field_id']:
                raise ValueError('Season must belong to the observation field')
        context.initialize_observation_seasons(bound)
        return context.save(bound, data)

    field = context.positive(data.get('field_id'), 'field')
    if not db.execute('SELECT 1 FROM fields WHERE id=? AND farm_id=?', (field,farm)).fetchone():
        raise AccessError()
    before = None
    if 'id' in data:
        sid = context.positive(data['id'], 'season')
        row = db.execute('''SELECT s.* FROM crop_seasons s JOIN fields f ON f.id=s.field_id
                            WHERE s.id=? AND f.farm_id=?''', (sid,farm)).fetchone()
        if row is None:
            raise AccessError()
        before = dict(row)
        if before['field_id'] != field:
            raise ValueError('Existing seasons cannot be moved to another field')
        if data.get('selection_hash') != context.digest(before):
            raise InspectionConflict('Season changed; refresh before saving')
    sid = seasons.save_season(bound, data)
    after = dict(db.execute('SELECT * FROM crop_seasons WHERE id=?', (sid,)).fetchone())
    if before == after:
        return {'id':sid,'reused':True}
    db.execute('''CREATE TABLE IF NOT EXISTS nexus_season_revisions (
        id INTEGER PRIMARY KEY, season_id INTEGER NOT NULL REFERENCES crop_seasons(id),
        farm_id INTEGER NOT NULL REFERENCES farms(id), field_id INTEGER NOT NULL REFERENCES fields(id),
        recorded_at TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL)''')
    db.execute('''INSERT INTO nexus_season_revisions(season_id,farm_id,field_id,recorded_at,before_json,after_json)
        VALUES(?,?,?,?,?,?)''', (sid,farm,field,datetime.now(timezone.utc).isoformat(),
                               context.canonical(before),context.canonical(after)))
    return {'id':sid,'reused':False}
