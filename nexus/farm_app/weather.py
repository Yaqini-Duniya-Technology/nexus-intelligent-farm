import json
import math
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from threading import Lock
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

LATITUDE = 7.8
LONGITUDE = 6.65

FIELDS = (
    'temperature_2m_min',
    'temperature_2m_max',
    'precipitation_sum',
    'precipitation_probability_max',
    'wind_speed_10m_max',
)

_lock = Lock()
_cached = None
_cached_at = 0.0

PAGE = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS weather snapshots</title>
<style>
body{margin:0;background:#f1f5ee;color:#183c2c;font:16px system-ui}
header{padding:28px;background:#163f30;color:white}
main{max-width:1050px;margin:auto;padding:24px}
section{background:white;padding:22px;border-radius:14px;margin:20px 0}
a{color:inherit;margin-right:18px}
button,select{padding:12px;font:inherit;border-radius:8px;margin:6px 0}
button{background:#1d5c40;color:white;border:0;cursor:pointer}
button:disabled{opacity:.5}
.scroll{overflow:auto}
table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:12px;border-bottom:1px solid #ddd}
#message{padding:12px;background:#fff1c6}
p{line-height:1.5}
</style>
</head>
<body>
<header>
<small>LOCAL PILOT · SAVED AREA WEATHER</small>
<h1>NEXUS weather</h1>
<a href="/overview">Farm dashboard</a>
<a href="/">Workspace</a>
</header>
<main>
<h2>Zango-Daji area, Lokoja, Kogi State</h2>
<p>
Approximate area point: 7.8000°N, 6.6500°E.
This is the midpoint of the supplied range, not a measured field position.
</p>
<p>
External model forecasts. Actual field weather can differ.
Snapshots are area records; they are not automatically linked to observations.
</p>
<button id="refresh">Load / refresh forecast</button>
<button id="save" disabled>Save this forecast</button>
<p id="message" role="status" aria-live="polite">Loading…</p>

<section>
<h2>Saved forecasts</h2>
<label for="saved">Select a saved snapshot</label>
<select id="saved"><option value="">Select…</option></select>
<button id="reload">Refresh saved list</button>
<p>
Saving the same retrieved forecast again does not create a duplicate.
Saved snapshots retain their original values and times.
</p>
</section>

<section id="forecast" hidden>
<h2 id="heading"></h2>
<p id="retrieved"></p>
<p id="recorded"></p>
<p id="grid"></p>
<p>
Dates use Lagos time (UTC+1). Daily values cover whole calendar days,
including the elapsed part of the retrieval day.
Missing values appear as —.
</p>
<div class="scroll">
<table>
<caption>Seven-day forecast</caption>
<thead>
<tr>
<th>Date</th>
<th>Low °C</th>
<th>High °C</th>
<th>Precipitation mm</th>
<th>Max precipitation chance %</th>
<th>Max wind km/h</th>
</tr>
</thead>
<tbody id="rows"></tbody>
</table>
</div>
<p>
Retrieved time is when NEXUS received the forecast, not the model issue time.
Live refreshes within 15 minutes reuse the same retrieved forecast.
A saved forecast is historical and may no longer describe upcoming weather.
</p>
</section>
<p>
Forecasts do not change tasks, diagnose conditions or control equipment.
</p>
<p>
Weather data:
<a href="https://open-meteo.com/" target="_blank" rel="noopener">
Open-Meteo</a>, CC BY 4.0.
</p>
</main>

<script>
const $ = id => document.getElementById(id);
let current = null, records = [], busy = false;

const date = value => new Date(value).toLocaleString(
    'en-NG', {timeZone:'Africa/Lagos'}
);

function controls() {
    $('refresh').disabled = busy;
    $('reload').disabled = busy;
    $('saved').disabled = busy;
    $('save').disabled = busy || !current || !!current.id;
}

async function request(path, data) {
    const response = await fetch(path, data ? {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(data)
    } : {});

    const body = await response.json();

    if (!response.ok) {
        throw Error(body.error || 'Request failed');
    }

    return body;
}

function show(data) {
    current = data;

    $('heading').textContent = data.id
        ? 'Saved forecast #' + data.id + ' — historical snapshot'
        : 'Live area forecast';

    $('retrieved').textContent =
        'Retrieved: ' + date(data.retrieved_at) + ' (Lagos time)';

    $('recorded').textContent = data.saved_at
        ? 'Saved: ' + date(data.saved_at) + ' (Lagos time)'
        : 'Not saved yet.';

    $('grid').textContent =
        'Provider grid point: ' +
        data.grid_latitude + ', ' + data.grid_longitude;

    $('rows').replaceChildren();

    for (const values of data.days) {
        const row = document.createElement('tr');

        for (const value of values) {
            const cell = document.createElement('td');
            cell.textContent = value == null ? '—' : String(value);
            row.append(cell);
        }

        $('rows').append(row);
    }

    $('forecast').hidden = false;
    controls();
}

async function list() {
    records = await request('/api/weather-snapshots');
    const selected = current?.id;

    $('saved').replaceChildren(
        new Option('Select a saved snapshot…', '')
    );

    for (const item of records) {
        $('saved').add(new Option(
            '#' + item.id + ' · retrieved ' + date(item.retrieved_at),
            item.id
        ));
    }

    if (selected) {
        $('saved').value = String(selected);
    }
}

async function run(action) {
    busy = true;
    controls();

    try {
        await action();
    } catch (error) {
        $('message').textContent = error.message;
    } finally {
        busy = false;
        controls();
    }
}

$('refresh').onclick = () => run(async () => {
    current = null;
    $('forecast').hidden = true;
    $('message').textContent = 'Loading forecast…';

    show(await request('/api/weather'));
    $('saved').value = '';

    $('message').textContent =
        'Forecast loaded. Check the retrieved time.';
});

$('save').onclick = () => run(async () => {
    const saved = await request('/api/weather-snapshots', {
        retrieved_at:current.retrieved_at
    });

    show(saved);
    $('message').textContent = 'Forecast snapshot saved.';
    await list();
});

$('reload').onclick = () => run(async () => {
    await list();
    $('message').textContent = 'Saved list refreshed.';
});

$('saved').onchange = () => {
    const item = records.find(
        row => String(row.id) === $('saved').value
    );

    if (item) {
        show(item);
        $('message').textContent = 'Historical snapshot loaded.';
    }
};

run(async () => {
    await list();
    show(await request('/api/weather'));
    $('message').textContent = 'Weather ready.';
});
</script>
</body>
</html>'''


def initialize_weather(store):
    with store.connect() as db:
        db.execute(
            '''
            CREATE TABLE IF NOT EXISTS weather_snapshots (
                id INTEGER PRIMARY KEY,
                retrieved_at TEXT NOT NULL UNIQUE,
                saved_at TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            '''
        )


def snapshots(store):
    with store.connect() as db:
        rows = db.execute(
            'SELECT * FROM weather_snapshots ORDER BY id DESC'
        ).fetchall()

    return [
        dict(
            json.loads(row['payload']),
            id=row['id'],
            saved_at=row['saved_at'],
        )
        for row in rows
    ]


def save_snapshot(store, retrieved_at):
    if (
        not isinstance(retrieved_at, str)
        or len(retrieved_at) > 100
    ):
        raise ValueError('Invalid forecast reference')

    with _lock:
        with store.connect() as db:
            row = db.execute(
                '''
                SELECT *
                FROM weather_snapshots
                WHERE retrieved_at=?
                ''',
                (retrieved_at,),
            ).fetchone()

            if row is None:
                if (
                    _cached is None
                    or _cached['retrieved_at'] != retrieved_at
                ):
                    raise ValueError(
                        'Reload the live forecast before saving it.'
                    )

                db.execute(
                    '''
                    INSERT INTO weather_snapshots
                        (retrieved_at, saved_at, payload)
                    VALUES (?, ?, ?)
                    ''',
                    (
                        retrieved_at,
                        datetime.now(timezone.utc).isoformat(),
                        json.dumps(_cached, allow_nan=False),
                    ),
                )

                row = db.execute(
                    '''
                    SELECT *
                    FROM weather_snapshots
                    WHERE retrieved_at=?
                    ''',
                    (retrieved_at,),
                ).fetchone()

            return dict(
                json.loads(row['payload']),
                id=row['id'],
                saved_at=row['saved_at'],
            )


def forecast():
    global _cached, _cached_at

    with _lock:
        if (
            _cached is not None
            and time.monotonic() - _cached_at < 900
        ):
            return _cached

        params = {
            'latitude': LATITUDE,
            'longitude': LONGITUDE,
            'daily': ','.join(FIELDS),
            'timezone': 'Africa/Lagos',
            'forecast_days': 7,
            'temperature_unit': 'celsius',
            'wind_speed_unit': 'kmh',
            'precipitation_unit': 'mm',
        }

        request = Request(
            'https://api.open-meteo.com/v1/forecast?'
            + urlencode(params),
            headers={'User-Agent': 'NEXUS-local-pilot/1.0'},
        )

        with urlopen(request, timeout=15) as response:
            raw = response.read(262145)

        if len(raw) > 262144:
            raise ValueError('Weather response was too large')

        data = json.loads(raw)
        daily = data['daily']
        dates = daily['time']

        if not isinstance(dates, list) or len(dates) != 7:
            raise ValueError('Incomplete weather response')

        for value in dates:
            datetime.strptime(value, '%Y-%m-%d')

        for field in FIELDS:
            values = daily[field]

            if (
                not isinstance(values, list)
                or len(values) != len(dates)
            ):
                raise ValueError('Incomplete weather values')

            for value in values:
                if value is not None and (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    raise ValueError('Invalid weather value')

        _cached = {
            'retrieved_at': datetime.now(timezone.utc).isoformat(),
            'location': (
                'Approximate Zango-Daji area, Lokoja, Kogi State'
            ),
            'requested_latitude': LATITUDE,
            'requested_longitude': LONGITUDE,
            'grid_latitude': data['latitude'],
            'grid_longitude': data['longitude'],
            'provider': 'Open-Meteo',
            'timezone': 'Africa/Lagos',
            'columns': ['date'] + list(FIELDS),
            'units': ['date', '°C', '°C', 'mm', '%', 'km/h'],
            'days': [
                [date] + [daily[field][i] for field in FIELDS]
                for i, date in enumerate(dates)
            ],
        }

        _cached_at = time.monotonic()
        return _cached


def weather_handler(base_factory):
    def make_handler(store):
        initialize_weather(store)

        class Handler(base_factory(store)):
            def do_GET(self):
                path = urlparse(self.path).path

                if path == '/weather':
                    self.respond(
                        200,
                        PAGE.encode('utf-8'),
                        'text/html; charset=utf-8',
                    )

                elif path == '/api/weather-snapshots':
                    try:
                        self.respond(200, snapshots(store))
                    except sqlite3.Error:
                        self.respond(
                            500,
                            {'error': 'Could not load saved forecasts.'},
                        )

                elif path == '/api/weather':
                    try:
                        result = forecast()
                    except (
                        OSError,
                        ValueError,
                        KeyError,
                        TypeError,
                    ):
                        self.respond(
                            502,
                            {
                                'error': (
                                    'Forecast unavailable. Check your '
                                    'internet connection and retry.'
                                )
                            },
                        )
                    else:
                        self.respond(200, result)

                else:
                    super().do_GET()

            def do_POST(self):
                if (
                    urlparse(self.path).path
                    != '/api/weather-snapshots'
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

                try:
                    size = int(
                        self.headers.get('Content-Length', '0')
                    )

                    if not 0 < size <= 1024:
                        raise ValueError('Invalid request size')

                    data = json.loads(
                        self.rfile.read(size).decode('utf-8')
                    )

                    if not isinstance(data, dict):
                        raise ValueError('Expected a JSON object')

                    result = save_snapshot(
                        store,
                        data.get('retrieved_at'),
                    )

                except (ValueError, UnicodeDecodeError) as error:
                    self.respond(400, {'error': str(error)})

                except sqlite3.Error:
                    self.respond(
                        500,
                        {
                            'error': (
                                'Could not save the forecast. Refresh '
                                'the saved list before retrying.'
                            )
                        },
                    )

                else:
                    self.respond(200, result)

        return Handler

    return make_handler


def main():
    from nexus.farm_app import server

    original = server.make_handler
    server.make_handler = weather_handler(original)

    print('Weather snapshots: /weather', flush=True)

    try:
        server.main()
    finally:
        server.make_handler = original


if __name__ == '__main__':
    main()