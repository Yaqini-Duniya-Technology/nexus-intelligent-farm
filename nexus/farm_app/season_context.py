"""Saved season-context validation, descriptive checks and HTML rendering."""
import json
from html import escape
from nexus.farm_app.observation_seasons import digest, STAGES


def validate_entry(entry, observation):
    payload = entry.get('payload')
    if (not isinstance(payload, dict) or digest(payload) != entry.get('content_sha256')
            or payload.get('version') != 'observation-season-context-v1'):
        raise ValueError('Season context content hash or version is invalid')
    frozen = payload.get('observation_at_capture')
    season = payload.get('season_at_capture')
    if (entry.get('observation_id') != observation.get('id')
            or payload.get('observation_id') != observation.get('id')
            or not isinstance(frozen, dict) or frozen.get('id') != observation.get('id')
            or frozen.get('field_id') != observation.get('field_id')
            or payload.get('season_id') != entry.get('season_id')):
        raise ValueError('Season context observation reference is inconsistent')
    sid = payload.get('season_id')
    if sid is None:
        if season is not None:
            raise ValueError('Unknown season has unexpected season details')
    elif (type(sid) is not int or sid < 1 or not isinstance(season, dict)
          or season.get('id') != sid or season.get('field_id') != observation.get('field_id')):
        raise ValueError('Season context belongs to a different field or season')
    if payload.get('growth_stage') not in STAGES:
        raise ValueError('Invalid saved growth stage')
    for key, limit in [('reporter', 200), ('basis', 3000), ('reason', 3000)]:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError('Invalid saved season context ' + key)


def capture_history(db, tables, observation):
    if 'observation_season_history' not in tables:
        return None
    rows = [dict(r) for r in db.execute(
        'SELECT * FROM observation_season_history WHERE observation_id=? ORDER BY id DESC',
        (observation['id'],))]
    for row in rows:
        row['payload'] = json.loads(row['payload'])
        validate_entry(row, observation)
    return rows


def assess(payload):
    history = payload.get('observation_season_history')
    result = {'status': 'not_captured', 'entries': None, 'latest_entry_id': None,
              'season_id': None, 'growth_stage': None, 'findings': []}
    if history is None:
        result['findings'].append('Season context history was not available in this capture.')
        return result
    if not isinstance(history, list):
        result['findings'].append('Season context history has an invalid structure.')
        result['status'] = 'invalid'
        return result
    result['entries'] = len(history)
    if not history:
        result['status'] = 'no_entry'
        result['findings'].append('No season context was recorded for this observation at capture.')
        return result
    try:
        for entry in history:
            if not isinstance(entry, dict) or type(entry.get('id')) is not int:
                raise ValueError('Invalid season context entry ID')
            validate_entry(entry, payload.get('observation') or {})
        latest = max(history, key=lambda item: item['id'])
    except (ValueError, TypeError, KeyError) as error:
        result['status'] = 'invalid'
        result['findings'].append(str(error))
        return result
    data = latest['payload']
    result.update(status='recorded', latest_entry_id=latest['id'],
                  season_id=data['season_id'], growth_stage=data['growth_stage'])
    if data['season_id'] is None:
        result['findings'].append('Season linkage is explicitly recorded as unknown.')
    if data['growth_stage'] == 'unknown':
        result['findings'].append('Growth stage at observation is explicitly recorded as unknown.')
    if data['observation_at_capture'] != payload.get('observation'):
        result['findings'].append('Observation values differ from those saved with the season context; assess recorded corrections.')
    return result


def render_history(payload, title='Season context at bundle capture'):
    def text(value):
        return escape(str(value if value is not None else 'Unknown'))
    result = '<section><h2>' + text(title) + '</h2><p>Saved user-reported context. Later season edits do not rewrite these entries. This is not a verified growth-stage assessment.</p>'
    assessment = assess(payload)
    if assessment['status'] != 'recorded':
        return result + ''.join('<p>' + text(f) + '</p>' for f in assessment['findings']) + '</section>'
    result += '<p>Newest entry first; earlier entries are retained.</p>'
    for entry in sorted(payload['observation_season_history'], key=lambda e: e['id'], reverse=True):
        data = entry['payload']
        season = data['season_at_capture'] or {}
        pairs = [('Recorded (UTC)', entry.get('recorded_at')), ('Reporter / role', data['reporter']),
                 ('Season ID', data['season_id']), ('Season name at entry', season.get('name')),
                 ('Planting date (planned or actual)', season.get('planting_date')),
                 ('Expected harvest', season.get('expected_harvest_date')),
                 ('Reported growth stage at observation', data['growth_stage'].replace('_', ' ')),
                 ('Basis', data['basis']), ('Reason / correction', data['reason']),
                 ('Entry content SHA-256', entry['content_sha256'])]
        result += '<article><h3>Season context entry #' + text(entry['id']) + '</h3><dl>'
        result += ''.join('<dt>' + text(k) + '</dt><dd style="white-space:pre-wrap">' + text(v) + '</dd>' for k,v in pairs)
        result += '</dl></article>'
    return result + '</section>'
