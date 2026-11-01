import math
from datetime import date, datetime, timezone


def initialize_seasons(store):
    with store.connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS crop_seasons (
                id INTEGER PRIMARY KEY,
                field_id INTEGER NOT NULL REFERENCES fields(id),
                name TEXT NOT NULL,
                crop TEXT NOT NULL,
                variety TEXT NOT NULL,
                area_ha REAL NOT NULL CHECK(area_ha > 0),
                planting_date TEXT NOT NULL,
                expected_harvest_date TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)


def season_state(store):
    with store.connect() as db:
        fields = [
            dict(row)
            for row in db.execute("""
                SELECT fields.*, farms.name AS farm_name
                FROM fields
                JOIN farms ON farms.id = fields.farm_id
                ORDER BY fields.id DESC
            """)
        ]

        seasons = [
            dict(row)
            for row in db.execute("""
                SELECT crop_seasons.*,
                       fields.name AS field_name,
                       farms.name AS farm_name
                FROM crop_seasons
                JOIN fields ON fields.id = crop_seasons.field_id
                JOIN farms ON farms.id = fields.farm_id
                ORDER BY crop_seasons.id DESC
            """)
        ]

    return {
        "fields": fields,
        "seasons": seasons,
    }


def save_season(store, data):
    season_id = data.get("id")

    if "id" in data and (
        isinstance(season_id, bool)
        or not isinstance(season_id, int)
        or season_id < 1
    ):
        raise ValueError("Invalid season ID")

    field_id = data.get("field_id")

    if (
        isinstance(field_id, bool)
        or not isinstance(field_id, int)
        or field_id < 1
    ):
        raise ValueError("Select an existing field")

    strings = {}

    for key in ("name", "variety"):
        value = data.get(key)

        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 200
        ):
            raise ValueError(
                "Enter a season name and variety "
                "(maximum 200 characters each)"
            )

        strings[key] = value.strip()

    raw_area = data.get("area_ha")

    if (
        isinstance(raw_area, bool)
        or not isinstance(raw_area, (str, int, float))
    ):
        raise ValueError(
            "Enter a positive field area in hectares"
        )

    try:
        area = float(raw_area)
    except (ValueError, OverflowError):
        raise ValueError(
            "Enter a positive field area in hectares"
        ) from None

    if not math.isfinite(area) or area <= 0:
        raise ValueError(
            "Enter a positive field area in hectares"
        )

    dates = {}

    for key in ("planting_date", "expected_harvest_date"):
        value = data.get(key)

        try:
            parsed = (
                date.fromisoformat(value)
                if isinstance(value, str)
                else None
            )
        except ValueError:
            parsed = None

        if parsed is None or parsed.isoformat() != value:
            raise ValueError("Enter dates as YYYY-MM-DD")

        dates[key] = value

    if (
        dates["expected_harvest_date"]
        <= dates["planting_date"]
    ):
        raise ValueError(
            "Expected harvest must be after the planting date"
        )

    with store.connect() as db:
        field = db.execute(
            "SELECT crop FROM fields WHERE id = ?",
            (field_id,),
        ).fetchone()

        if field is None:
            raise ValueError("Select an existing field")

        if season_id is not None:
            existing = db.execute(
                "SELECT id FROM crop_seasons WHERE id = ?",
                (season_id,),
            ).fetchone()

            if existing is None:
                raise ValueError(
                    "Crop season not found; refresh the page"
                )

            db.execute(
                """
                UPDATE crop_seasons
                SET field_id = ?,
                    name = ?,
                    crop = ?,
                    variety = ?,
                    area_ha = ?,
                    planting_date = ?,
                    expected_harvest_date = ?
                WHERE id = ?
                """,
                (
                    field_id,
                    strings["name"],
                    field["crop"],
                    strings["variety"],
                    area,
                    dates["planting_date"],
                    dates["expected_harvest_date"],
                    season_id,
                ),
            )

            return season_id

        cursor = db.execute(
            """
            INSERT INTO crop_seasons (
                field_id,
                name,
                crop,
                variety,
                area_ha,
                planting_date,
                expected_harvest_date,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                field_id,
                strings["name"],
                field["crop"],
                strings["variety"],
                area,
                dates["planting_date"],
                dates["expected_harvest_date"],
                datetime.now(timezone.utc).isoformat(),
            ),
        )

        return cursor.lastrowid


SEASONS_HTML = """<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport"
          content="width=device-width,initial-scale=1">

    <title>NEXUS Crop Seasons</title>

    <style>
        * {
            box-sizing: border-box;
        }

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

        input,
        select,
        button {
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

        button:disabled {
            opacity: .5;
        }

        a {
            color: inherit;
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

        .muted {
            color: #5d7060;
        }
    </style>
</head>

<body>
<header>
    <small>LOCAL PILOT · CROP PLANNING</small>
    <h1>NEXUS crop seasons</h1>
    <a href="/">Back to farm workspace</a>
    <a href="/observation-seasons">Observation season context</a>
    <a href="/season-overview">Field season overview</a>
</header>

<main>
    <p class="muted">
        Record your planting plan and expected harvest.
        Dates are farmer-entered plans; NEXUS does not
        predict harvest or yield. These records do not
        change task recommendations.
    </p>

    <p id="message" role="status" aria-live="polite">
        Loading seasons…
    </p>

    <section>
        <h2 id="form-title">Add a crop season</h2>

        <form id="season-form">
            <label for="field">Field</label>
            <select id="field"
                    name="field_id"
                    required></select>

            <label for="name">Season name</label>
            <input id="name"
                   name="name"
                   maxlength="200"
                   placeholder="For example: 2026 maize season"
                   required>

            <label for="variety">Crop variety</label>
            <input id="variety"
                   name="variety"
                   maxlength="200"
                   placeholder="Enter Unknown if you do not know"
                   required>

            <label for="area">
                Area used for this season (hectares)
            </label>
            <input id="area"
                   name="area_ha"
                   type="number"
                   min="0"
                   step="any"
                   required>

            <label for="planting">
                Planting date (planned or actual)
            </label>
            <input id="planting"
                   name="planting_date"
                   type="date"
                   required>

            <label for="harvest">
                Expected harvest date
            </label>
            <input id="harvest"
                   name="expected_harvest_date"
                   type="date"
                   required>

            <button id="save">Save crop season</button>

            <button id="cancel"
                    type="button"
                    hidden>
                Cancel editing
            </button>
        </form>
    </section>

    <section>
        <h2>Saved crop seasons</h2>
        <div id="season-list"></div>
    </section>
</main>

<script>
const $ = id => document.getElementById(id);

let state;
let editingId = null;

function node(tag, text) {
    const element = document.createElement(tag);
    element.textContent = text;
    return element;
}

async function request(data) {
    const response = await fetch(
        '/api/seasons',
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

function render() {
    const select = $('field');
    const previous = select.value;

    select.replaceChildren(
        new Option(
            state.fields.length
                ? 'Select a field…'
                : 'Create a field in the workspace first',
            ''
        )
    );

    for (const field of state.fields) {
        select.add(
            new Option(
                `${field.farm_name} / ${field.name} · ${field.crop}`,
                field.id
            )
        );
    }

    if (
        state.fields.some(
            field => String(field.id) === previous
        )
    ) {
        select.value = previous;
    }

    $('save').disabled = !state.fields.length;

    const list = $('season-list');
    list.replaceChildren();

    if (!state.seasons.length) {
        list.append(
            node('p', 'No crop seasons recorded yet.')
        );
    }

    for (const season of state.seasons) {
        const article = node('article', '');

        article.append(
            node('h3', season.name),
            node(
                'p',
                `${season.farm_name} / ${season.field_name}`
            ),
            node(
                'p',
                `Crop: ${season.crop} · Variety: ${season.variety}`
            ),
            node(
                'p',
                `Season area: ${season.area_ha} hectares`
            ),
            node(
                'p',
                `Planting date: ${season.planting_date}`
            ),
            node(
                'p',
                `Expected harvest: ${season.expected_harvest_date}`
            )
        );

        const edit = node('button', 'Edit crop season');
        edit.type = 'button';

        edit.onclick = () => {
            editingId = season.id;

            const form = $('season-form');

            for (const key of [
                'field_id',
                'name',
                'variety',
                'area_ha',
                'planting_date',
                'expected_harvest_date'
            ]) {
                form.elements.namedItem(key).value = season[key];
            }

            $('form-title').textContent =
                'Edit crop season #' + season.id;

            $('save').textContent = 'Save changes';
            $('cancel').hidden = false;

            $('message').textContent =
                'Editing ' + season.name +
                '. Change the details and save.';

            $('form-title').scrollIntoView({
                behavior: 'smooth'
            });

            $('name').focus();
        };

        article.append(edit);
        list.append(article);
    }
}

function resetForm() {
    editingId = null;
    $('season-form').reset();

    $('form-title').textContent = 'Add a crop season';
    $('save').textContent = 'Save crop season';
    $('cancel').hidden = true;
}

$('cancel').onclick = () => {
    resetForm();
    $('message').textContent = 'Editing cancelled.';
};

$('season-form').onsubmit = async event => {
    event.preventDefault();

    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form));

    data.field_id = Number(data.field_id);
    data.area_ha = Number(data.area_ha);

    const isEditing = editingId !== null;

    if (isEditing) {
        data.id = editingId;
    }

    $('save').disabled = true;
    $('cancel').disabled = true;

    try {
        state = await request(data);
        resetForm();
        render();

        $('message').textContent = isEditing
            ? 'Crop season updated.'
            : 'Crop season saved.';
    } catch (error) {
        $('message').textContent = error.message;
        $('save').disabled = !state?.fields.length;
    } finally {
        $('cancel').disabled = false;
    }
};

request()
    .then(result => {
        state = result;
        render();
        $('message').textContent = 'Crop planning ready.';
    })
    .catch(error => {
        $('message').textContent = error.message;
        $('save').disabled = true;
    });
</script>
</body>
</html>
"""