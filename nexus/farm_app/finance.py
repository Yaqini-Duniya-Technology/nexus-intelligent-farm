from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation


def initialize_finance(store):
    with store.connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS season_transactions (
                id INTEGER PRIMARY KEY,
                season_id INTEGER NOT NULL
                    REFERENCES crop_seasons(id),
                kind TEXT NOT NULL
                    CHECK(kind IN ('expense', 'sale')),
                occurred_at TEXT NOT NULL,
                description TEXT NOT NULL,
                amount_kobo INTEGER NOT NULL
                    CHECK(amount_kobo > 0),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)


def finance_state(store):
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

        transactions = [
            dict(row)
            for row in db.execute("""
                SELECT *
                FROM season_transactions
                ORDER BY occurred_at DESC, id DESC
            """)
        ]

    totals = {
        season["id"]: {
            "expenses_kobo": 0,
            "sales_kobo": 0,
            "entries": 0,
        }
        for season in seasons
    }

    for row in transactions:
        summary = totals[row["season_id"]]

        key = (
            "expenses_kobo"
            if row["kind"] == "expense"
            else "sales_kobo"
        )

        summary[key] += row["amount_kobo"]
        summary["entries"] += 1

        row["amount_ngn"] = str(
            Decimal(row["amount_kobo"]) / 100
        )

    for season in seasons:
        summary = totals[season["id"]]

        summary["balance_kobo"] = (
            summary["sales_kobo"]
            - summary["expenses_kobo"]
        )

        season["cash_summary"] = summary

    return {
        "seasons": seasons,
        "transactions": transactions,
    }


def save_transaction(store, data):
    season_id = data.get("season_id")
    record_id = data.get("id")

    if (
        isinstance(season_id, bool)
        or not isinstance(season_id, int)
        or season_id < 1
    ):
        raise ValueError("Select a valid season")

    if "id" in data and (
        isinstance(record_id, bool)
        or not isinstance(record_id, int)
        or record_id < 1
    ):
        raise ValueError("Invalid transaction ID")

    kind = data.get("kind")

    if kind not in ("expense", "sale"):
        raise ValueError("Choose expense or sale")

    description = data.get("description")

    if (
        not isinstance(description, str)
        or not description.strip()
        or len(description) > 1000
    ):
        raise ValueError(
            "Describe the payment or sale "
            "(maximum 1000 characters)"
        )

    raw = data.get("amount_ngn")

    if not isinstance(raw, str) or len(raw) > 30:
        raise ValueError(
            "Enter the naira amount as text, without commas"
        )

    try:
        amount = Decimal(raw)
    except InvalidOperation:
        raise ValueError(
            "Enter a valid naira amount"
        ) from None

    if (
        not amount.is_finite()
        or not 0 < amount <= Decimal("1000000000000")
    ):
        raise ValueError(
            "Amount must be positive and no more than "
            "1 trillion naira"
        )

    kobo = amount * 100

    if kobo != kobo.to_integral_value():
        raise ValueError(
            "Use no more than two decimal places"
        )

    value = data.get("occurred_at")

    try:
        occurred = (
            date.fromisoformat(value)
            if isinstance(value, str)
            else None
        )
    except ValueError:
        occurred = None

    if occurred is None or occurred.isoformat() != value:
        raise ValueError(
            "Enter a payment date as YYYY-MM-DD"
        )

    today = datetime.now(
        timezone(timedelta(hours=1))
    ).date()

    if occurred > today:
        raise ValueError(
            "Payment date cannot be in the future "
            "(Lagos time)"
        )

    now = datetime.now(timezone.utc).isoformat()

    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")

        season = db.execute(
            "SELECT id FROM crop_seasons WHERE id = ?",
            (season_id,),
        ).fetchone()

        if season is None:
            raise ValueError("Crop season not found")

        values = (
            season_id,
            kind,
            value,
            description.strip(),
            int(kobo),
        )

        if record_id is not None:
            existing = db.execute(
                """
                SELECT id
                FROM season_transactions
                WHERE id = ?
                """,
                (record_id,),
            ).fetchone()

            if existing is None:
                raise ValueError(
                    "Transaction not found; refresh the page"
                )

            db.execute(
                """
                UPDATE season_transactions
                SET season_id = ?,
                    kind = ?,
                    occurred_at = ?,
                    description = ?,
                    amount_kobo = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (*values, now, record_id),
            )

            return record_id

        cursor = db.execute(
            """
            INSERT INTO season_transactions (
                season_id,
                kind,
                occurred_at,
                description,
                amount_kobo,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (*values, now, now),
        )

        return cursor.lastrowid


FINANCE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1">
<title>NEXUS Season Expenses and Sales</title>

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
    max-width: 900px;
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
    margin-top: 16px;
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
    <small>LOCAL PILOT · SEASON CASH RECORDS</small>
    <h1>NEXUS expenses & sales</h1>
    <a href="/">Workspace</a>
    <a href="/seasons">Crop seasons</a>
    <a href="/harvests">Harvests</a>
</header>

<main>
    <p>
        Record money actually paid for expenses and money
        actually received from produce sales. For partial
        payments, record only the paid or received amount.
    </p>

    <p>
        Recorded cash balance = received sales minus paid
        expenses. It is not a complete profit calculation.
        Unrecorded costs, unpaid amounts and unsold produce
        are not included. All amounts are in Nigerian
        naira (NGN).
    </p>

    <p id="message" role="status" aria-live="polite">
        Loading…
    </p>

    <section>
        <h2 id="title">Add expense or sale</h2>

        <form id="entry">
            <label for="season">Crop season</label>
            <select id="season"
                    name="season_id"
                    required></select>

            <label for="kind">Record type</label>
            <select id="kind" name="kind">
                <option value="expense">Expense paid</option>
                <option value="sale">
                    Sale payment received
                </option>
            </select>

            <label for="date">Payment date</label>
            <input id="date"
                   name="occurred_at"
                   type="date"
                   required>

            <label for="description">
                What was paid for or sold?
            </label>
            <textarea id="description"
                      name="description"
                      maxlength="1000"
                      required></textarea>

            <label for="amount">
                Amount paid or received (NGN)
            </label>
            <input id="amount"
                   name="amount_ngn"
                   type="number"
                   min="0.01"
                   step="0.01"
                   required>

            <button id="save">Save record</button>

            <button id="cancel"
                    type="button"
                    hidden>
                Cancel editing
            </button>
        </form>
    </section>

    <section>
        <h2>Season cash summaries</h2>
        <div id="summaries"></div>
    </section>

    <section>
        <h2>Saved expenses and sales</h2>
        <div id="records"></div>
    </section>
</main>

<script>
const $ = id => document.getElementById(id);

let state;
let editingId = null;
let saving = false;

const money = kobo => new Intl.NumberFormat(
    'en-NG',
    {
        style: 'currency',
        currency: 'NGN'
    }
).format(kobo / 100);

function node(tag, text) {
    const element = document.createElement(tag);
    element.textContent = text;
    return element;
}

async function request(data) {
    const response = await fetch(
        '/api/finance',
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

function reset() {
    editingId = null;
    $('entry').reset();
    $('title').textContent = 'Add expense or sale';
    $('save').textContent = 'Save record';
    $('cancel').hidden = true;
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

    $('summaries').replaceChildren();
    $('records').replaceChildren();

    if (!state.seasons.length) {
        $('summaries').append(
            node('p', 'No crop seasons recorded.')
        );
    }

    for (const season of state.seasons) {
        const article = node('article', '');
        const totals = season.cash_summary;

        article.append(
            node('h3', season.name),
            node(
                'p',
                `${totals.entries} recorded payments`
            ),
            node(
                'p',
                `Expenses paid: ${money(totals.expenses_kobo)}`
            ),
            node(
                'p',
                `Sales received: ${money(totals.sales_kobo)}`
            ),
            node(
                'p',
                `Recorded cash balance: ${money(totals.balance_kobo)}`
            )
        );

        if (!totals.entries) {
            article.append(
                node(
                    'p',
                    'No payments recorded. Zero totals do not ' +
                    'establish that the season had no costs or sales.'
                )
            );
        }

        $('summaries').append(article);
    }

    if (!state.transactions.length) {
        $('records').append(
            node('p', 'No expenses or sales recorded.')
        );
    }

    for (const record of state.transactions) {
        const season = state.seasons.find(
            item => item.id === record.season_id
        );

        const article = node('article', '');

        article.append(
            node(
                'h3',
                season?.name || 'Season #' + record.season_id
            ),
            node(
                'p',
                record.kind === 'expense'
                    ? 'Expense paid'
                    : 'Sale payment received'
            ),
            node('p', record.occurred_at),
            node('p', record.description),
            node('p', money(record.amount_kobo))
        );

        const button = node('button', 'Edit record');
        button.type = 'button';

        button.onclick = () => {
            if (saving) return;

            editingId = record.id;
            const form = $('entry');

            for (const key of [
                'season_id',
                'kind',
                'occurred_at',
                'description',
                'amount_ngn'
            ]) {
                form.elements.namedItem(key).value = record[key];
            }

            $('title').textContent =
                'Edit record #' + record.id;

            $('save').textContent = 'Save changes';
            $('cancel').hidden = false;

            $('title').scrollIntoView({
                behavior: 'smooth'
            });
        };

        article.append(button);
        $('records').append(article);
    }
}

$('cancel').onclick = () => {
    if (!saving) {
        reset();
        $('message').textContent = 'Editing cancelled.';
    }
};

$('entry').onsubmit = async event => {
    event.preventDefault();

    if (saving) return;

    const data = Object.fromEntries(
        new FormData(event.currentTarget)
    );

    data.season_id = Number(data.season_id);

    if (editingId !== null) {
        data.id = editingId;
    }

    saving = true;
    $('save').disabled = true;
    $('cancel').disabled = true;

    try {
        state = await request(data);
        reset();
        render();
        $('message').textContent = 'Payment record saved.';
    } catch (error) {
        $('message').textContent = error.message;
        $('save').disabled = !state?.seasons.length;
    } finally {
        saving = false;
        $('cancel').disabled = false;
    }
};

request()
    .then(result => {
        state = result;
        render();
        $('message').textContent = 'Expenses and sales ready.';
    })
    .catch(error => {
        $('message').textContent = error.message;
        $('save').disabled = true;
    });
</script>
</body>
</html>
"""