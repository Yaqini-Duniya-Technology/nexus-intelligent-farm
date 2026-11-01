"""Current field-level season context, separate from frozen evidence."""
from html import escape
from nexus.farm_app.observation_seasons import state, digest


def overview_state(store):
    records = state(store)
    latest = {}
    for entry in records['history']:
        latest.setdefault(entry['observation_id'], entry)
    seasons = {s['id']: s for s in records['seasons']}
    rows = []
    counts = {'linked': 0, 'unknown': 0, 'unrecorded': 0, 'needs_recheck': 0}
    from nexus.farm_app.season_context import validate_entry
    for observation in records['observations']:
        entry = latest.get(observation['id'])
        status = 'unrecorded'
        stage = None
        sid = None
        warnings = []
        if entry:
            validate_entry(entry, observation)
            data = entry['payload']
            sid, stage = data['season_id'], data['growth_stage']
            status = 'unknown' if sid is None else 'linked'
            raw = {k:v for k,v in observation.items() if k not in ('farm_name','field_name','crop','selection_hash')}
            if data['observation_at_capture'] != raw:
                warnings.append('Observation has changed since this context entry.')
            if sid is not None:
                current = seasons.get(sid)
                if not current or current['selection_hash'] != digest(data['season_at_capture']):
                    warnings.append('Season has changed or is unavailable; review the saved link.')
                if current and current['field_id'] != observation['field_id']:
                    warnings.append('Current season belongs to another field.')
            if warnings:
                status = 'needs_recheck'
        counts[status] += 1
        rows.append({'observation_id': observation['id'], 'field_id': observation['field_id'],
                     'field_name': observation['field_name'], 'farm_name': observation['farm_name'],
                     'note': observation['note'], 'status': status, 'season_id': sid,
                     'growth_stage': stage, 'latest_entry_id': entry['id'] if entry else None,
                     'warnings': warnings})
    return {'counts': counts, 'observations': rows}


def render_overview(data):
    def text(value):
        return escape(str(value if value is not None else 'Not recorded'))
    content = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>NEXUS season overview</title><style>body{background:#f1f5ee;color:#183c2c;font:16px system-ui;margin:0}header{background:#163f30;color:white;padding:24px}main{max-width:1000px;margin:auto;padding:24px}article{background:white;padding:20px;margin:18px 0;border-radius:12px}a{color:inherit;margin-right:16px}p{overflow-wrap:anywhere}</style>
    <header><h1>Field season overview</h1><nav><a href="/overview">Farm dashboard</a><a href="/seasons">Crop seasons</a><a href="/observation-seasons">Record season context</a><a href="/season-overview">Refresh overview</a></nav></header><main>
    <p>Current saved records, grouped by field. Linked means a user recorded a season link; it does not verify season identity or growth stage. Earlier evidence bundles retain their own captured context.</p>'''
    content += '<p>' + ' / '.join(text(k.replace('_',' ')) + ': ' + text(v) for k,v in data['counts'].items()) + '</p>'
    fields = {}
    for row in data['observations']:
        fields.setdefault(row['field_id'], []).append(row)
    for rows in fields.values():
        content += '<h2>' + text(rows[0]['farm_name']) + ' / ' + text(rows[0]['field_name']) + '</h2>'
        for row in rows:
            content += '<article><h3>Observation #' + text(row['observation_id']) + ' — ' + text(row['status'].replace('_',' ')) + '</h3>'
            content += '<p>' + text(row['note']) + '</p><p>Season ID: ' + text(row['season_id']) + ' / Stage: ' + text(row['growth_stage']) + ' / Context entry: ' + text(row['latest_entry_id']) + '</p>'
            content += ''.join('<p>' + text(w) + '</p>' for w in row['warnings'])
            content += '<a href="/observation-seasons">Review or correct season context</a></article>'
    if not data['observations']:
        content += '<p>No observations recorded.</p>'
    return content + '</main></html>'
