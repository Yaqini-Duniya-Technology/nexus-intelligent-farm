import json
import math
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse


CHOICES = {
    'soil_type': (
        'unknown', 'sandy', 'loamy', 'clayey', 'mixed',
    ),
    'crop_stage': (
        'unknown', 'not_planted', 'establishment',
        'vegetative', 'flowering', 'grain_or_fruit_filling',
        'mature', 'harvested',
    ),
    'water_access': (
        'unknown', 'rainfed_only', 'manual_watering',
        'irrigation_available',
    ),
    'location_precision': (
        'unknown', 'approximate_area', 'field_point',
    ),
}


PAGE = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS field context</title>
<style>
body{margin:0;background:#f1f5ee;color:#183c2c;font:16px system-ui}
header{padding:28px;background:#163f30;color:white}
main{max-width:900px;margin:auto;padding:24px}
section{background:white;padding:22px;border-radius:14px;margin:20px 0}
label{display:block;margin:14px 0 6px}
input,select,textarea,button{box-sizing:border-box;width:100%;padding:12px;
font:inherit;border:1px solid #bdcbbb;border-radius:8px}
textarea{min-height:90px}
button{background:#1d5c40;color:white;margin-top:16px;cursor:pointer}
button:disabled{opacity:.5}
a{color:inherit;margin-right:18px}
p{line-height:1.5}
#message{padding:12px;background:#fff1c6}
article{border-top:1px solid #ddd;padding:16px 0;overflow-wrap:anywhere}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:600px){.grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<header>
<small>LOCAL PILOT · FIELD CONTEXT</small>
<h1>NEXUS field context</h1>
<a href="/overview">Dashboard</a>
<a href="/">Workspace</a>
<a href="/weather">Weather</a>
</header>
<main>
<p>
Record what is known about the field on a particular date.
Leave unknown details unknown.
These are user-entered reports, not verified measurements.
</p>
<p>
This does not change existing recommendations, review snapshots
or the weather location. Crop stage describes the crop on the
context date; it may change later.
</p>
<p id="message" role="status" aria-live="polite">Loading…</p>

<section>
<form id="form">
<h2>Record field context</h2>

<label for="field">Field</label>
<select id="field" name="field_id" required></select>

<label for="context-date">
Context date (blank means today in Lagos)
</label>
<input id="context-date" name="context_date" type="date">

<label for="location">Reported field location</label>
<input id="location" name="location" maxlength="300" required>

<label for="precision">Coordinate precision</label>
<select id="precision" name="location_precision">
<option value="unknown">Coordinates not recorded</option>
<option value="approximate_area">Approximate area point</option>
<option value="field_point">User-reported field point</option>
</select>

<div class="grid">
<div>
<label for="latitude">Latitude (optional)</label>
<input id="latitude" name="latitude" type="number"
min="-90" max="90" step="any">
</div>
<div>
<label for="longitude">Longitude (optional)</label>
<input id="longitude" name="longitude" type="number"
min="-180" max="180" step="any">
</div>
</div>

<label for="soil">Reported soil type</label>
<select id="soil" name="soil_type">
<option value="unknown">Unknown</option>
<option value="sandy">Sandy</option>
<option value="loamy">Loamy</option>
<option value="clayey">Clayey</option>
<option value="mixed">Mixed</option>
</select>

<label for="stage">Reported crop stage</label>
<select id="stage" name="crop_stage">
<option value="unknown">Unknown</option>
<option value="not_planted">Not planted</option>
<option value="establishment">Establishment</option>
<option value="vegetative">Vegetative</option>
<option value="flowering">Flowering</option>
<option value="grain_or_fruit_filling">Grain / fruit filling</option>
<option value="mature">Mature</option>
<option value="harvested">Harvested</option>
</select>

<label for="water">Water access</label>
<select id="water" name="water_access">
<option value="unknown">Unknown</option>
<option value="rainfed_only">Rainfed only</option>
<option value="manual_watering">Manual watering</option>
<option value="irrigation_available">Irrigation available</option>
</select>

<label for="resources">
Available resources and constraints (optional)
</label>
<textarea id="resources" name="resources" maxlength="3000"
placeholder="Record actual labour, tools, water availability or budget constraints."></textarea>

<label for="basis">How were these details established?</label>
<textarea id="basis" name="basis" required maxlength="3000"
placeholder="Describe your observations, records or measurements and their limitations."></textarea>

<button id="save">Save new context version</button>
</form>
</section>

<section>
<h2>Context history for selected field</h2>
<p>
Newest context date first. All earlier versions remain available.
A newer entry records an update or correction;
it does not erase earlier entries.
</p>
<div id="history"></div>
</section>
</main>

<script>
const $ = id => document.getElementById(id);
let state;

async function request(data) {
    const response = await fetch('/api/field-context', data ? {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(data)
    } : {});

    const result = await response.json();

    if (!response.ok) {
        throw Error(result.error || 'Request failed');
    }

    return result;
}

function paragraph(parent, text) {
    const p = document.createElement('p');
    p.textContent = text;
    parent.append(p);
}

function history() {
    $('history').replaceChildren();

    const records = state.contexts.filter(
        r => String(r.field_id) === $('field').value
    );

    if (!records.length) {
        paragraph($('history'), 'No field context recorded yet.');
    }

    for (const r of records) {
        const article = document.createElement('article');
        const heading = document.createElement('h3');

        heading.textContent =
            'Version #' + r.id + ' · context date ' + r.context_date;

        article.append(heading);
        paragraph(article, 'Location: ' + r.location);

        paragraph(
            article,
            r.latitude == null
                ? 'Coordinates: not recorded'
                : 'Coordinates: ' + r.latitude + ', ' +
                  r.longitude + ' · ' + r.location_precision
        );

        paragraph(
            article,
            'Soil: ' + r.soil_type +
            ' · Crop stage: ' + r.crop_stage
        );

        paragraph(article, 'Water access: ' + r.water_access);

        paragraph(
            article,
            'Resources / constraints: ' +
            (r.resources || 'Not recorded')
        );

        paragraph(article, 'Basis / limitations: ' + r.basis);

        paragraph(
            article,
            'Recorded: ' +
            new Date(r.recorded_at).toLocaleString(
                'en-NG', {timeZone:'Africa/Lagos'}
            ) +
            ' (Lagos time)'
        );

        $('history').append(article);
    }
}

function render() {
    const previous = $('field').value;

    $('field').replaceChildren(
        new Option('Select a field…', '')
    );

    for (const f of state.fields) {
        $('field').add(new Option(
            f.farm_name + ' / ' + f.name + ' · ' + f.crop,
            f.id
        ));
    }

    $('field').value = previous;
    $('save').disabled = !state.fields.length;
    history();
}

$('field').onchange = history;

$('form').onsubmit = async event => {
    event.preventDefault();
    $('save').disabled = true;

    const data = Object.fromEntries(
        new FormData($('form'))
    );

    data.field_id = Number(data.field_id);

    try {
        state = await request(data);
        render();
        $('message').textContent =
            'New field context version saved.';
    } catch (error) {
        $('message').textContent = error.message;
    } finally {
        $('save').disabled = !state?.fields.length;
    }
};

request().then(result => {
    state = result;
    render();
    $('message').textContent = 'Field context ready.';
}).catch(error => {
    $('message').textContent = error.message;
});
</script>
</body>
</html>'''


def initialize_context(store):
    with store.connect() as db:
        db.execute(
            '''
            CREATE TABLE IF NOT EXISTS field_context_versions (
                id INTEGER PRIMARY KEY,
                field_id INTEGER NOT NULL REFERENCES fields(id),
                context_date TEXT NOT NULL,
                location TEXT NOT NULL,
                location_precision TEXT NOT NULL,
                latitude REAL,
                longitude REAL,
                soil_type TEXT NOT NULL,
                crop_stage TEXT NOT NULL,
                water_access TEXT NOT NULL,
                resources TEXT NOT NULL,
                basis TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            )
            '''
        )


def context_state(store):
    with store.connect() as db:
        fields = [
            dict(r)
            for r in db.execute(
                '''
                SELECT f.*, a.name AS farm_name
                FROM fields f
                JOIN farms a ON a.id=f.farm_id
                ORDER BY f.id DESC
                '''
            )
        ]

        contexts = [
            dict(r)
            for r in db.execute(
                '''
                SELECT *
                FROM field_context_versions
                ORDER BY context_date DESC, id DESC
                '''
            )
        ]

        return {
            'fields': fields,
            'contexts': contexts,
        }


def save_context(store, data):
    field_id = data.get('field_id')

    if (
        isinstance(field_id, bool)
        or not isinstance(field_id, int)
        or field_id < 1
    ):
        raise ValueError('Select an existing field')

    values = {}

    for key, limit, required in [
        ('location', 300, True),
        ('resources', 3000, False),
        ('basis', 3000, True),
    ]:
        value = data.get(key, '')

        if (
            not isinstance(value, str)
            or len(value) > limit
            or (required and not value.strip())
        ):
            raise ValueError(
                f'Complete {key} (maximum {limit} characters)'
            )

        values[key] = value.strip()

    for key, choices in CHOICES.items():
        value = data.get(key, 'unknown')

        if value not in choices:
            raise ValueError(f'Choose a valid {key}')

        values[key] = value

    today = datetime.now(
        timezone(timedelta(hours=1))
    ).date()

    day = data.get('context_date') or today.isoformat()

    try:
        parsed = date.fromisoformat(day)

        if parsed.isoformat() != day or parsed > today:
            raise ValueError

    except (ValueError, TypeError):
        raise ValueError(
            'Use a valid context date no later than today in Lagos'
        ) from None

    coordinates = []

    for key, limit in [
        ('latitude', 90),
        ('longitude', 180),
    ]:
        value = data.get(key)

        if value is None or value == '':
            coordinates.append(None)
            continue

        try:
            if isinstance(value, bool):
                raise ValueError

            number = float(value)

            if (
                not math.isfinite(number)
                or not -limit <= number <= limit
            ):
                raise ValueError

        except (ValueError, TypeError):
            raise ValueError(f'Invalid {key}') from None

        coordinates.append(number)

    lat, lon = coordinates

    if (lat is None) != (lon is None):
        raise ValueError(
            'Provide both coordinates or leave both blank'
        )

    if (
        (lat is None)
        != (values['location_precision'] == 'unknown')
    ):
        raise ValueError(
            'Match coordinate precision to the entered coordinates'
        )

    with store.connect() as db:
        existing = db.execute(
            'SELECT id FROM fields WHERE id=?',
            (field_id,),
        ).fetchone()

        if not existing:
            raise ValueError('Select an existing field')

        db.execute(
            '''
            INSERT INTO field_context_versions (
                field_id,
                context_date,
                location,
                location_precision,
                latitude,
                longitude,
                soil_type,
                crop_stage,
                water_access,
                resources,
                basis,
                recorded_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                field_id,
                day,
                values['location'],
                values['location_precision'],
                lat,
                lon,
                values['soil_type'],
                values['crop_stage'],
                values['water_access'],
                values['resources'],
                values['basis'],
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def context_handler(base_factory):
    def make_handler(store):
        initialize_context(store)

        class Handler(base_factory(store)):
            def do_GET(self):
                path = urlparse(self.path).path

                if path == '/field-context':
                    self.respond(
                        200,
                        PAGE.encode('utf-8'),
                        'text/html; charset=utf-8',
                    )

                elif path == '/api/field-context':
                    try:
                        self.respond(200, context_state(store))
                    except sqlite3.Error:
                        self.respond(
                            500,
                            {'error': 'Could not load field context.'},
                        )

                else:
                    super().do_GET()

            def do_POST(self):
                if (
                    urlparse(self.path).path
                    != '/api/field-context'
                ):
                    return super().do_POST()

                origin = self.headers.get('Origin')

                if (
                    origin
                    and origin !=
                    'http://' + self.headers.get('Host', '')
                ):
                    self.respond(
                        403,
                        {'error': 'Cross-origin request rejected'},
                    )
                    return

                saved = False

                try:
                    size = int(
                        self.headers.get('Content-Length', '0')
                    )

                    if not 0 < size <= 32768:
                        raise ValueError('Invalid request size')

                    data = json.loads(
                        self.rfile.read(size).decode('utf-8')
                    )

                    if not isinstance(data, dict):
                        raise ValueError('Expected a JSON object')

                    save_context(store, data)
                    saved = True
                    result = context_state(store)

                except (ValueError, UnicodeDecodeError) as error:
                    self.respond(400, {'error': str(error)})

                except sqlite3.Error:
                    error = (
                        'Context saved; refresh before retrying.'
                        if saved
                        else (
                            'Database operation failed. '
                            'Context was not saved.'
                        )
                    )

                    self.respond(500, {'error': error})

                else:
                    self.respond(200, result)

        return Handler

    return make_handler


def main():
    from nexus.farm_app import server, weather

    original = server.make_handler
    server.make_handler = context_handler(original)

    print('Field context: /field-context', flush=True)

    try:
        weather.main()
    finally:
        server.make_handler = original


if __name__ == '__main__':
    main()