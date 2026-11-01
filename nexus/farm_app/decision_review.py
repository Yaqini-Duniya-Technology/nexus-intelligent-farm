from urllib.parse import urlparse


PAGE = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS decision review</title>
<style>
body{margin:0;background:#f1f5ee;color:#183c2c;font:16px system-ui}
header{padding:28px;background:#163f30;color:white}
main{max-width:1000px;margin:auto;padding:24px}
section{background:white;padding:22px;border-radius:14px;margin:20px 0}
a{color:inherit;margin-right:16px}
p{line-height:1.5;white-space:pre-wrap;overflow-wrap:anywhere}
label{display:block;margin:14px 0 6px}
select,button{width:100%;padding:12px;font:inherit;border-radius:8px;
border:1px solid #bdcbbb}
button{background:#1d5c40;color:white;cursor:pointer;margin-top:16px}
button:disabled{opacity:.5}
#message{padding:12px;background:#fff1c6}
article{padding:14px 0;border-top:1px solid #ddd}
.scroll{overflow:auto}
table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:10px;border-bottom:1px solid #ddd}
</style>
</head>
<body>
<header>
<small>LOCAL PILOT · DECISION REVIEW</small>
<h1>NEXUS decision review</h1>
<a href="/overview">Dashboard</a>
<a href="/">Workspace</a>
<a href="/field-context">Field context</a>
<a href="/weather">Weather</a>
</header>

<main>
<p>
Bring recorded information together for a human review.
This page does not produce a diagnosis, choose an intervention or change tasks.
</p>
<p>
Current records are loaded from several endpoints.
They may include information recorded after task creation
and are not an original decision-time snapshot.
</p>

<p id="message" role="status" aria-live="polite">Loading…</p>

<label for="observation">Select an observation</label>
<select id="observation"></select>

<label for="weather">Optional weather snapshot for this review</label>
<select id="weather"></select>

<p>
Choose weather only if its area and forecast dates are relevant.
Selection does not establish a field match and is not saved
as a link to this observation.
</p>

<button id="refresh">Refresh review records</button>
<div id="review"></div>
</main>

<script>
const $ = id => document.getElementById(id);
let records;

const local = value => value
    ? new Date(value).toLocaleString(
        'en-NG', {timeZone:'Africa/Lagos'}
      ) + ' (Lagos time)'
    : 'Not recorded';

function add(parent, tag, text) {
    const element = document.createElement(tag);
    element.textContent = text;
    parent.append(element);
    return element;
}

function section(title) {
    const s = document.createElement('section');
    add(s, 'h2', title);
    $('review').append(s);
    return s;
}

function link(parent, text, path) {
    const a = add(parent, 'a', text);
    a.href = path;
}

function render() {
    $('review').replaceChildren();

    const observation = records.state.observations.find(
        o => String(o.id) === $('observation').value
    );

    if (!observation) return;

    const field = records.state.fields.find(
        f => f.id === observation.field_id
    );

    const farm = records.state.farms.find(
        f => f.id === field?.farm_id
    );

    const task = records.state.tasks.find(
        t => t.observation_id === observation.id
    );

    let s = section('Recorded observation');

    add(
        s, 'h3',
        (farm?.name || 'Unknown farm') + ' / ' +
        (field?.name || 'Unknown field')
    );

    add(
        s, 'p',
        'Observation #' + observation.id + ' · ' +
        (field?.crop || 'Unknown crop')
    );

    add(s, 'p', observation.note);

    add(
        s, 'p',
        'Observed: ' +
        local(observation.observed_at || observation.created)
    );

    add(s, 'p', 'Submitted: ' + local(observation.created));

    add(
        s, 'p',
        'Category: ' + observation.category +
        ' · Source: ' + observation.source +
        ' · Reported condition: ' + observation.condition
    );

    if (observation.soil_moisture_pct != null) {
        add(
            s, 'p',
            'Reported volumetric moisture: ' +
            observation.soil_moisture_pct +
            '% · Method: ' + observation.moisture_method
        );
    }

    link(
        s,
        'Open photo evidence and source labels',
        '/photos?observation_id=' + observation.id
    );

    s = section(
        'Latest recorded field context — current review only'
    );

    const contexts = records.context.contexts.filter(
        c => c.field_id === observation.field_id
    );

    const context = contexts[0];

    if (!context) {
        add(s, 'p', 'No field context recorded.');
    } else {
        add(
            s, 'p',
            'Version #' + context.id +
            ' · Context date: ' + context.context_date +
            '\\nRecorded: ' + local(context.recorded_at)
        );

        add(
            s, 'p',
            'Location: ' + context.location +
            ' · Coordinate precision: ' + context.location_precision
        );

        if (context.latitude != null) {
            add(
                s, 'p',
                'Coordinates: ' + context.latitude +
                ', ' + context.longitude
            );
        }

        add(
            s, 'p',
            'Soil: ' + context.soil_type +
            ' · Crop stage: ' + context.crop_stage +
            ' · Water access: ' + context.water_access
        );

        add(
            s, 'p',
            'Resources / constraints: ' +
            (context.resources || 'Not recorded')
        );

        add(s, 'p', 'Basis / limitations: ' + context.basis);

        add(
            s, 'p',
            'This context may postdate the observation. ' +
            'It does not describe the field at the original ' +
            'observation time unless its date and evidence ' +
            'support that interpretation.'
        );
    }

    s = section('Recorded task and original review');

    if (!task) {
        add(s, 'p', 'No task found for this observation.');
    } else {
        add(
            s, 'p',
            'Task #' + task.id + ' · ' + task.status +
            ' · ' + task.priority + ' priority'
        );

        add(s, 'p', task.recommendation);

        add(
            s, 'p',
            task.original_explanation || task.explanation
        );

        let missing = [];

        try {
            missing = JSON.parse(
                task.missing_information || '[]'
            );
        } catch {}

        if (Array.isArray(missing) && missing.length) {
            add(
                s, 'p',
                'Information needed: ' + missing.join('; ')
            );
        }

        if (task.review_snapshot?.status === 'stored') {
            link(
                s,
                'Open stored review snapshot',
                '/api/review-snapshot?task_id=' + task.id
            );
        }

        link(
            s,
            'Open task / outcome history',
            '/#task-' + task.id
        );
    }

    s = section('Adviser reviews recorded so far');

    const reviews = records.advisers.reviews.filter(
        r => r.observation_id === observation.id
    );

    if (!reviews.length) {
        add(s, 'p', 'No adviser consultation recorded.');
    }

    for (const r of reviews) {
        const a = add(s, 'article', '');

        add(a, 'h3', r.adviser_name + ' · ' + r.adviser_role);

        add(
            a, 'p',
            'Consultation: ' + local(r.reviewed_at) +
            ' · Recorded: ' + local(r.recorded_at)
        );

        add(a, 'p', 'Reported assessment: ' + r.assessment);
        add(a, 'p', 'Findings: ' + r.findings);
        add(a, 'p', 'Basis / limitations: ' + r.basis);
        add(a, 'p', 'Agreed next step: ' + r.next_step);
    }

    add(
        s, 'p',
        'Names and findings are user-entered. ' +
        'NEXUS does not authenticate advisers or independently ' +
        'verify their conclusions.'
    );

    link(
        s,
        'Open adviser reviews',
        '/advisers?observation_id=' + observation.id
    );

    s = section(
        'Manually selected weather — relevance requires review'
    );

    const weather = records.weather.find(
        w => String(w.id) === $('weather').value
    );

    if (!weather) {
        add(s, 'p', 'No weather snapshot selected.');
    } else {
        add(
            s, 'p',
            'Snapshot #' + weather.id + ' · ' + weather.location
        );

        add(
            s, 'p',
            'Retrieved: ' + local(weather.retrieved_at) +
            ' · Saved: ' + local(weather.saved_at)
        );

        add(
            s, 'p',
            'Approximate requested point: ' +
            weather.requested_latitude + ', ' +
            weather.requested_longitude
        );

        add(
            s, 'p',
            'Historical forecast, not measured rainfall. ' +
            'Check location and dates before using it.'
        );

        const wrap = add(s, 'div', '');
        wrap.className = 'scroll';

        const table = add(wrap, 'table', '');
        const head = add(table, 'tr', '');

        for (const title of [
            'Date',
            'Low °C',
            'High °C',
            'Precipitation mm',
            'Max chance %',
            'Max wind km/h'
        ]) {
            add(head, 'th', title);
        }

        for (const values of weather.days) {
            const row = add(table, 'tr', '');

            for (const v of values) {
                add(row, 'td', v == null ? '—' : String(v));
            }
        }
    }

    s = section('Questions for the human reviewer');

    for (const text of [
        'What evidence supports the reported condition?',
        'Which details remain unknown or contradictory?',
        'Does the context date describe the crop being reviewed?',
        'Is the selected weather relevant to this field and time?',
        'What options has a qualified adviser discussed, and what constraints apply?',
        'What work was actually performed, and what follow-up evidence is needed?'
    ]) {
        add(s, 'p', text);
    }
}

async function get(path) {
    const response = await fetch(path);
    const data = await response.json();

    if (!response.ok) {
        throw Error(data.error || 'Could not load ' + path);
    }

    return data;
}

async function load() {
    $('refresh').disabled = true;

    try {
        const old = $('observation').value;
        const oldWeather = $('weather').value;

        const [state, context, advisers, weather] =
            await Promise.all([
                get('/api/state'),
                get('/api/field-context'),
                get('/api/adviser-reviews'),
                get('/api/weather-snapshots')
            ]);

        records = {state, context, advisers, weather};

        $('observation').replaceChildren(
            new Option('Select an observation…', '')
        );

        for (const o of state.observations) {
            $('observation').add(
                new Option('#' + o.id + ' · ' + o.note, o.id)
            );
        }

        $('weather').replaceChildren(
            new Option('No weather selected', '')
        );

        for (const w of weather) {
            $('weather').add(new Option(
                '#' + w.id + ' · retrieved ' +
                local(w.retrieved_at),
                w.id
            ));
        }

        $('observation').value = old;
        $('weather').value = oldWeather;
        render();

        $('message').textContent =
            'Review records loaded: ' +
            local(new Date().toISOString());

    } catch (error) {
        $('message').textContent = error.message;
    } finally {
        $('refresh').disabled = false;
    }
}

$('observation').onchange = render;
$('weather').onchange = render;
$('refresh').onclick = load;

load();
</script>
</body>
</html>'''


def review_handler(base_factory):
    def make_handler(store):
        class Handler(base_factory(store)):
            def do_GET(self):
                if urlparse(self.path).path == '/decision-review':
                    self.respond(
                        200,
                        PAGE.encode('utf-8'),
                        'text/html; charset=utf-8',
                    )
                else:
                    super().do_GET()

        return Handler

    return make_handler


def main():
    from nexus.farm_app import server, field_context_guard

    original = server.make_handler
    server.make_handler = review_handler(original)

    print('Decision review: /decision-review', flush=True)

    try:
        field_context_guard.main()
    finally:
        server.make_handler = original


if __name__ == '__main__':
    main()