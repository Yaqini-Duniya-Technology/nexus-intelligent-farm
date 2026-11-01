import math
from datetime import date, datetime, timedelta, timezone


def initialize_harvests(store):
    with store.connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS harvests (
                id INTEGER PRIMARY KEY,
                season_id INTEGER NOT NULL UNIQUE
                    REFERENCES crop_seasons(id),
                harvested_at TEXT NOT NULL,
                quantity_kg REAL NOT NULL CHECK(quantity_kg >= 0),
                area_ha REAL NOT NULL CHECK(area_ha > 0),
                note TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            )
        """)


def harvest_state(store):
    with store.connect() as db:
        seasons = [
            dict(row)
            for row in db.execute("""
                SELECT crop_seasons.*,
                       fields.name AS field_name
                FROM crop_seasons
                JOIN fields ON fields.id = crop_seasons.field_id
                ORDER BY crop_seasons.id DESC
            """)
        ]

        harvests = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM harvests ORDER BY id DESC"
            )
        ]

    for harvest in harvests:
        harvest["yield_kg_ha"] = (
            harvest["quantity_kg"] / harvest["area_ha"]
        )

    return {
        "seasons": seasons,
        "harvests": harvests,
    }


def save_harvest(store, data):
    season_id = data.get("season_id")

    if (
        isinstance(season_id, bool)
        or not isinstance(season_id, int)
        or season_id < 1
    ):
        raise ValueError("Select an existing crop season")

    raw = data.get("quantity_kg")

    if (
        isinstance(raw, bool)
        or not isinstance(raw, (str, int, float))
    ):
        raise ValueError(
            "Enter the total harvest in kilograms"
        )

    try:
        quantity = float(raw)
    except (ValueError, OverflowError):
        raise ValueError(
            "Enter the total harvest in kilograms"
        ) from None

    if not math.isfinite(quantity) or quantity < 0:
        raise ValueError(
            "Harvest must be zero or more kilograms"
        )

    value = data.get("harvested_at")

    try:
        harvested = (
            date.fromisoformat(value)
            if isinstance(value, str)
            else None
        )
    except ValueError:
        harvested = None

    if harvested is None or harvested.isoformat() != value:
        raise ValueError(
            "Enter a harvest date as YYYY-MM-DD"
        )

    today = datetime.now(
        timezone(timedelta(hours=1))
    ).date()

    if harvested > today:
        raise ValueError(
            "Actual harvest date cannot be in the future "
            "(Lagos time)"
        )

    note = data.get("note", "")

    if not isinstance(note, str) or len(note) > 3000:
        raise ValueError(
            "Notes must be text, maximum 3000 characters"
        )

    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")

        season = db.execute(
            "SELECT * FROM crop_seasons WHERE id = ?",
            (season_id,),
        ).fetchone()

        if season is None:
            raise ValueError("Crop season not found")

        if value < season["planting_date"]:
            raise ValueError(
                "Harvest cannot precede the planting date"
            )

        area = season["area_ha"]

        if not math.isfinite(quantity / area):
            raise ValueError(
                "Quantity and area produce an invalid yield"
            )

        db.execute(
            """
            INSERT INTO harvests (
                season_id,
                harvested_at,
                quantity_kg,
                area_ha,
                note,
                recorded_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(season_id) DO UPDATE SET
                harvested_at = excluded.harvested_at,
                quantity_kg = excluded.quantity_kg,
                area_ha = excluded.area_ha,
                note = excluded.note,
                recorded_at = excluded.recorded_at
            """,
            (
                season_id,
                value,
                quantity,
                area,
                note.strip(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )


HARVEST_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1">
<title>NEXUS Harvest Records</title>

<style>
* { box-sizing: border-box; }

body {
    margin: 0;
    background: #f1f5ee;
    color: #183c2c;
    font: 16px system-ui;
}

header {
    background: #163f30;
    color: white;
    padding: 28px;
}

main {
    max-width: 850px;
    margin: auto;
    padding: 24px;
}

section {
    background: white;
    padding: 24px;
    border-radius: 16px;
    margin-bottom: 20px;
}

label {
    display: block;
    margin: 16px 0 6px;
}

input, select, textarea, button {
    width: 100%;
    padding: 12px;
    font: inherit;
    border: 1px solid #bdcbbb;
    border-radius: 8px;
}

button {
    background: #1d5c40;
    color: white;
    margin-top: 18px;
    cursor: pointer;
}

button:disabled { opacity: .5; }

a {
    color: inherit;
    margin-right: 16px;
}

article {
    border-top: 1px solid #ddd;
    padding: 16px 0;
    overflow-wrap: anywhere;
}

#message {
    padding: 12px;
    background: #fff1c6;
}
</style>
</head>

<body>
<header>
    <small>LOCAL PILOT · PRODUCTION RECORDS</small>
    <h1>NEXUS harvest records</h1>
    <a href="/">Workspace</a>
    <a href="/seasons">Crop seasons</a>
</header>

<main>
    <p>
        Record one final total for the entire crop season.
        Wait until harvesting is finished. Saving again
        updates that season's existing harvest.
    </p>

    <p>
        Yield = reported total kilograms / recorded season
        hectares. It is not a prediction or an independently
        verified measurement.
    </p>

    <p id="message" role="status" aria-live="polite">
        Loading…
    </p>

    <section>
        <h2 id="title">Record final harvest</h2>

        <form id="harvest-form">
            <label for="season">Crop season</label>
            <select id="season"
                    name="season_id"
                    required></select>

            <p id="context"></p>

            <label for="date">
                Actual harvest completion date
            </label>
            <input id="date"
                   name="harvested_at"
                   type="date"
                   required>

            <label for="quantity">
                Final total harvested (kilograms)
            </label>
            <input id="quantity"
                   name="quantity_kg"
                   type="number"
                   min="0"
                   step="any"
                   required>

            <p>
                Enter 0 only if the season ended with
                no harvested produce.
            </p>

            <label for="note">
                Notes: product form and how the quantity
                was measured
            </label>
            <textarea
                id="note"
                name="note"
                maxlength="3000"
                placeholder="For example, shelled grain weighed using a scale"
            ></textarea>

            <button id="save">Save final harvest</button>
        </form>
    </section>

    <section>
        <h2>Saved harvests</h2>
        <div id="list"></div>
    </section>
</main>

<script>
const $ = id => document.getElementById(id);
let state;

function node(tag, text) {
    const element = document.createElement(tag);
    element.textContent = text;
    return element;
}

async function request(data) {
    const response = await fetch(
        '/api/harvests',
        data ? {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        } : {}
    );

    const body = await response.json();

    if (!response.ok) {
        throw new Error(body.error || 'Request failed');
    }

    return body;
}

function selection() {
    const season = state.seasons.find(
        item => String(item.id) === $('season').value
    );

    const record = state.harvests.find(
        item => item.season_id === season?.id
    );

    $('date').value = record?.harvested_at || '';
    $('quantity').value = record?.quantity_kg ?? '';
    $('note').value = record?.note || '';

    $('title').textContent = record
        ? 'Edit final harvest'
        : 'Record final harvest';

    $('save').textContent = record
        ? 'Update final harvest'
        : 'Save final harvest';

    $('context').textContent = season
        ? `${season.crop} · ${season.area_ha} hectares ·
           Planted/planned ${season.planting_date} ·
           Expected harvest ${season.expected_harvest_date}`
        : '';
}

function render() {
    const select = $('season');

    select.replaceChildren(
        new Option(
            state.seasons.length
                ? 'Select a crop season…'
                : 'Create a crop season first',
            ''
        )
    );

    for (const season of state.seasons) {
        select.add(
            new Option(
                `${season.name} / ${season.field_name} · ${season.crop}`,
                season.id
            )
        );
    }

    $('save').disabled = !state.seasons.length;
    $('list').replaceChildren();

    if (!state.harvests.length) {
        $('list').append(
            node('p', 'No final harvests recorded.')
        );
    }

    for (const harvest of state.harvests) {
        const season = state.seasons.find(
            item => item.id === harvest.season_id
        );

        const article = node('article', '');

        article.append(
            node(
                'h3',
                season?.name || 'Season #' + harvest.season_id
            ),
            node(
                'p',
                `Harvest completed: ${harvest.harvested_at}`
            ),
            node(
                'p',
                `Reported total: ${harvest.quantity_kg} kg`
            ),
            node(
                'p',
                `Area recorded with harvest: ${harvest.area_ha} hectares`
            ),
            node(
                'p',
                'Calculated yield: ' +
                harvest.yield_kg_ha.toLocaleString(
                    undefined,
                    { maximumFractionDigits: 2 }
                ) +
                ' kg/ha'
            ),
            node('p', harvest.note)
        );

        if (season && season.area_ha !== harvest.area_ha) {
            article.append(
                node(
                    'p',
                    'Season area has since changed. This yield ' +
                    'uses the area recorded at the last harvest save.'
                )
            );
        }

        const button = node('button', 'Edit final harvest');
        button.type = 'button';

        button.onclick = () => {
            $('season').value = harvest.season_id;
            selection();

            $('title').scrollIntoView({
                behavior: 'smooth'
            });
        };

        article.append(button);
        $('list').append(article);
    }
}

$('season').onchange = selection;

$('harvest-form').onsubmit = async event => {
    event.preventDefault();

    const data = Object.fromEntries(
        new FormData(event.currentTarget)
    );

    data.season_id = Number(data.season_id);
    data.quantity_kg = Number(data.quantity_kg);

    $('save').disabled = true;

    try {
        state = await request(data);
        render();
        selection();
        $('message').textContent = 'Final harvest saved.';
    } catch (error) {
        $('message').textContent = error.message;
        $('save').disabled = !state?.seasons.length;
    }
};

request()
    .then(result => {
        state = result;
        render();
        $('message').textContent = 'Harvest records ready.';
    })
    .catch(error => {
        $('message').textContent = error.message;
        $('save').disabled = true;
    });
</script>
</body>
</html>
"""