from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation


def positive_id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("Select a valid record")
    return value


def grams(value, allow_zero=False):
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ValueError("Enter kilograms using up to three decimal places")

    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Enter valid kilograms") from None

    if (
        not amount.is_finite()
        or amount < 0
        or (amount == 0 and not allow_zero)
    ):
        raise ValueError("Enter a positive quantity")

    if amount > Decimal("1000000000"):
        raise ValueError("Quantity is too large")

    scaled = amount * 1000

    if scaled != scaled.to_integral_value():
        raise ValueError("Use up to three decimal places for kilograms")

    return int(scaled)


def initialize_stock(store):
    with store.connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS harvest_product_forms (
                harvest_id INTEGER PRIMARY KEY REFERENCES harvests(id),
                product_form TEXT NOT NULL,
                harvest_recorded_at TEXT NOT NULL,
                confirmed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS stock_movements (
                id INTEGER PRIMARY KEY,
                harvest_id INTEGER NOT NULL REFERENCES harvests(id),
                kind TEXT NOT NULL
                    CHECK(kind IN ('loss', 'household_use', 'other')),
                quantity_g INTEGER NOT NULL CHECK(quantity_g > 0),
                occurred_at TEXT NOT NULL,
                note TEXT NOT NULL,
                product_form TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                recorded_at TEXT NOT NULL,
                cancelled_at TEXT
            );

            CREATE TABLE IF NOT EXISTS stock_sales (
                transaction_id INTEGER PRIMARY KEY
                    REFERENCES season_transactions(id),
                harvest_id INTEGER NOT NULL REFERENCES harvests(id),
                quantity_g INTEGER NOT NULL CHECK(quantity_g > 0),
                delivered_at TEXT NOT NULL,
                confirmed_at TEXT NOT NULL
            );
        """)


def stock_state(store):
    with store.connect() as db:
        db.execute("BEGIN")
        return read_stock(db)


def read_stock(db):
    seasons = [
        dict(r)
        for r in db.execute("""
            SELECT crop_seasons.*, fields.name AS field_name
            FROM crop_seasons
            JOIN fields ON fields.id = crop_seasons.field_id
            ORDER BY crop_seasons.id DESC
        """)
    ]

    harvests = [
        dict(r)
        for r in db.execute("SELECT * FROM harvests")
    ]

    forms = {
        r["harvest_id"]: dict(r)
        for r in db.execute("SELECT * FROM harvest_product_forms")
    }

    payments = [
        dict(r)
        for r in db.execute("""
            SELECT * FROM season_transactions
            WHERE kind = 'sale'
            ORDER BY id DESC
        """)
    ]

    all_payments = {
        r["id"]: dict(r)
        for r in db.execute("SELECT * FROM season_transactions")
    }

    links = [
        dict(r)
        for r in db.execute("SELECT * FROM stock_sales")
    ]

    movements = [
        dict(r)
        for r in db.execute("""
            SELECT * FROM stock_movements
            ORDER BY id DESC
        """)
    ]

    harvest_map = {r["id"]: r for r in harvests}

    for harvest in harvests:
        form = forms.get(harvest["id"])
        harvest["product_form"] = form["product_form"] if form else None
        harvest["form_current"] = bool(
            form
            and form["harvest_recorded_at"] == harvest["recorded_at"]
        )

    for link in links:
        harvest = harvest_map.get(link["harvest_id"])
        payment = all_payments.get(link["transaction_id"])

        link["eligible"] = bool(
            harvest
            and harvest["form_current"]
            and payment
            and payment["kind"] == "sale"
            and payment["season_id"] == harvest["season_id"]
        )
        link["quantity_kg"] = link["quantity_g"] / 1000

    for movement in movements:
        harvest = harvest_map.get(movement["harvest_id"])

        movement["eligible"] = bool(
            movement["status"] == "active"
            and harvest
            and harvest["form_current"]
            and movement["product_form"] == harvest["product_form"]
        )
        movement["quantity_kg"] = movement["quantity_g"] / 1000

    for harvest in harvests:
        matching = [
            r for r in links
            if r["harvest_id"] == harvest["id"] and r["eligible"]
        ]
        sold = sum(r["quantity_g"] for r in matching)

        withdrawn = sum(
            m["quantity_g"]
            for m in movements
            if m["eligible"] and m["harvest_id"] == harvest["id"]
        )

        try:
            total = grams(harvest["quantity_kg"], allow_zero=True)
        except ValueError:
            total = None

        harvest["linked_sales_kg"] = sold / 1000
        harvest["withdrawals_kg"] = withdrawn / 1000
        harvest["balance_known"] = bool(
            harvest["form_current"]
            and total is not None
            and sold + withdrawn <= total
        )

        harvest["remaining_kg"] = (
            (total - sold - withdrawn) / 1000
            if harvest["balance_known"]
            else None
        )

        harvest["unlinked_payments"] = sum(
            1
            for p in payments
            if p["season_id"] == harvest["season_id"]
            and not any(
                r["eligible"] and r["transaction_id"] == p["id"]
                for r in links
            )
        )

    return {
        "seasons": seasons,
        "harvests": harvests,
        "payments": payments,
        "links": links,
        "movements": movements,
    }


def save_stock(store, data):
    action = data.get("action")
    now = datetime.now(timezone.utc).isoformat()

    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")

        if action == "confirm_harvest":
            harvest_id = positive_id(data.get("harvest_id"))
            form = data.get("product_form")

            if (
                not isinstance(form, str)
                or not form.strip()
                or len(form) > 200
            ):
                raise ValueError(
                    "Enter the product form, maximum 200 characters"
                )

            harvest = db.execute(
                "SELECT * FROM harvests WHERE id = ?",
                (harvest_id,),
            ).fetchone()

            if harvest is None:
                raise ValueError("Harvest not found")

            total = grams(harvest["quantity_kg"], allow_zero=True)

            existing = db.execute(
                """
                SELECT * FROM harvest_product_forms
                WHERE harvest_id = ?
                """,
                (harvest_id,),
            ).fetchone()

            normalized = form.strip().lower()

            active_movements = db.execute(
                """
                SELECT 1 FROM stock_movements
                WHERE harvest_id = ? AND status = 'active'
                """,
                (harvest_id,),
            ).fetchone()

            if (
                existing
                and existing["product_form"] != normalized
                and active_movements
            ):
                raise ValueError(
                    "Cancel active withdrawals before changing the product form"
                )

            if (
                existing
                and existing["product_form"] != normalized
                and db.execute(
                    "SELECT 1 FROM stock_sales WHERE harvest_id = ?",
                    (harvest_id,),
                ).fetchone()
            ):
                raise ValueError(
                    "Unlink the saved sale quantities before changing "
                    "the product form"
                )

            state = read_stock(db)

            linked = sum(
                r["quantity_g"]
                for r in state["links"]
                if r["harvest_id"] == harvest_id
                and (
                    (
                        p := next(
                            (
                                p for p in state["payments"]
                                if p["id"] == r["transaction_id"]
                            ),
                            None,
                        )
                    )
                    and p["season_id"] == harvest["season_id"]
                )
            )

            withdrawn = sum(
                m["quantity_g"]
                for m in state["movements"]
                if m["harvest_id"] == harvest_id
                and m["status"] == "active"
                and m["product_form"] == normalized
            )

            if linked + withdrawn > total:
                raise ValueError(
                    "Sales and withdrawals exceed this harvest. "
                    "Correct those records first"
                )

            db.execute(
                """
                INSERT INTO harvest_product_forms VALUES (?, ?, ?, ?)
                ON CONFLICT(harvest_id) DO UPDATE SET
                    product_form = excluded.product_form,
                    harvest_recorded_at = excluded.harvest_recorded_at,
                    confirmed_at = excluded.confirmed_at
                """,
                (harvest_id, normalized, harvest["recorded_at"], now),
            )

        elif action == "link_sale":
            transaction_id = positive_id(data.get("transaction_id"))

            if data.get("same_product_form") is not True:
                raise ValueError(
                    "Confirm that the sold produce has the same "
                    "product form as the harvest"
                )

            quantity = grams(data.get("quantity_kg"))
            value = data.get("delivered_at")

            try:
                delivered = (
                    date.fromisoformat(value)
                    if isinstance(value, str)
                    else None
                )
            except ValueError:
                delivered = None

            if delivered is None or delivered.isoformat() != value:
                raise ValueError("Enter a delivery date as YYYY-MM-DD")

            if delivered > datetime.now(
                timezone(timedelta(hours=1))
            ).date():
                raise ValueError(
                    "Delivery date cannot be in the future (Lagos time)"
                )

            payment = db.execute(
                "SELECT * FROM season_transactions WHERE id = ?",
                (transaction_id,),
            ).fetchone()

            if payment is None or payment["kind"] != "sale":
                raise ValueError("Select an existing sale payment")

            state = read_stock(db)

            harvest = next(
                (
                    h for h in state["harvests"]
                    if h["season_id"] == payment["season_id"]
                ),
                None,
            )

            if harvest is None or not harvest["form_current"]:
                raise ValueError(
                    "Confirm this season's harvest product form first"
                )

            season = next(
                s for s in state["seasons"]
                if s["id"] == payment["season_id"]
            )

            if value < season["planting_date"]:
                raise ValueError(
                    "Delivery cannot precede the season planting date"
                )

            other_sold = sum(
                r["quantity_g"]
                for r in state["links"]
                if r["eligible"]
                and r["harvest_id"] == harvest["id"]
                and r["transaction_id"] != transaction_id
            )

            total = grams(harvest["quantity_kg"], allow_zero=True)

            withdrawn = sum(
                m["quantity_g"]
                for m in state["movements"]
                if m["eligible"] and m["harvest_id"] == harvest["id"]
            )

            if other_sold + withdrawn + quantity > total:
                raise ValueError(
                    "Sales and withdrawals cannot exceed "
                    "the reported harvest"
                )

            db.execute(
                """
                INSERT INTO stock_sales VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(transaction_id) DO UPDATE SET
                    harvest_id = excluded.harvest_id,
                    quantity_g = excluded.quantity_g,
                    delivered_at = excluded.delivered_at,
                    confirmed_at = excluded.confirmed_at
                """,
                (transaction_id, harvest["id"], quantity, value, now),
            )

        elif action == "save_movement":
            harvest_id = positive_id(data.get("harvest_id"))
            kind = data.get("kind")

            if kind not in ("loss", "household_use", "other"):
                raise ValueError("Choose a withdrawal type")

            quantity = grams(data.get("quantity_kg"))
            note = data.get("note")

            if (
                not isinstance(note, str)
                or not note.strip()
                or len(note) > 1000
            ):
                raise ValueError(
                    "Describe the withdrawal, maximum 1000 characters"
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
                raise ValueError("Enter a withdrawal date as YYYY-MM-DD")

            if occurred > datetime.now(
                timezone(timedelta(hours=1))
            ).date():
                raise ValueError(
                    "Withdrawal date cannot be in the future (Lagos time)"
                )

            state = read_stock(db)

            harvest = next(
                (
                    h for h in state["harvests"]
                    if h["id"] == harvest_id
                ),
                None,
            )

            if harvest is None or not harvest["balance_known"]:
                raise ValueError(
                    "Confirm the harvest form and resolve "
                    "its stock records first"
                )

            season = next(
                s for s in state["seasons"]
                if s["id"] == harvest["season_id"]
            )

            if value < season["planting_date"]:
                raise ValueError("Withdrawal cannot precede planting")

            if quantity > grams(
                harvest["remaining_kg"], allow_zero=True
            ):
                raise ValueError(
                    "Withdrawal exceeds the recorded remaining balance"
                )

            if data.get("same_product_form") is not True:
                raise ValueError(
                    "Confirm that this quantity has the same "
                    "product form as the harvest"
                )

            db.execute(
                """
                INSERT INTO stock_movements
                (
                    harvest_id, kind, quantity_g, occurred_at,
                    note, product_form, recorded_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    harvest_id,
                    kind,
                    quantity,
                    value,
                    note.strip(),
                    harvest["product_form"],
                    now,
                ),
            )

        elif action == "cancel_movement":
            movement_id = positive_id(data.get("movement_id"))

            movement = db.execute(
                "SELECT * FROM stock_movements WHERE id = ?",
                (movement_id,),
            ).fetchone()

            if movement is None or movement["status"] != "active":
                raise ValueError("Active withdrawal record not found")

            db.execute(
                """
                UPDATE stock_movements
                SET status = 'cancelled', cancelled_at = ?
                WHERE id = ?
                """,
                (now, movement_id),
            )

        elif action == "unlink_sale":
            transaction_id = positive_id(data.get("transaction_id"))

            db.execute(
                "DELETE FROM stock_sales WHERE transaction_id = ?",
                (transaction_id,),
            )

        else:
            raise ValueError("Unknown stock action")