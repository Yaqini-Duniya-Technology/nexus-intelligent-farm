from contextlib import closing
from datetime import datetime, timezone


def initialize_advisers(store):
    with store.connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS adviser_reviews (
                id INTEGER PRIMARY KEY,
                observation_id INTEGER NOT NULL
                    REFERENCES observations(id),
                adviser_name TEXT NOT NULL,
                adviser_role TEXT NOT NULL,
                reviewed_at TEXT NOT NULL,
                findings TEXT NOT NULL,
                assessment TEXT NOT NULL,
                basis TEXT NOT NULL,
                next_step TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            )
        """)


def adviser_state(store):
    with store.connect() as db:
        db.execute("BEGIN")

        observations = [
            dict(row)
            for row in db.execute("""
                SELECT
                    o.id,
                    o.note,
                    o.category,
                    o.observed_at,
                    o.created,
                    f.name AS field_name,
                    f.crop,
                    farms.name AS farm_name
                FROM observations o
                JOIN fields f ON f.id = o.field_id
                JOIN farms ON farms.id = f.farm_id
                ORDER BY o.id DESC
            """)
        ]

        reviews = [
            dict(row)
            for row in db.execute("""
                SELECT *
                FROM adviser_reviews
                ORDER BY id DESC
            """)
        ]

        return {
            "observations": observations,
            "reviews": reviews,
        }


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except (AttributeError, TypeError, ValueError):
        raise ValueError(
            "Invalid review or observation time"
        ) from None

    if parsed.tzinfo is None:
        raise ValueError(
            "Review time must include a timezone"
        )

    return parsed.astimezone(timezone.utc)


def save_adviser_review(store, data):
    observation_id = data.get("observation_id")

    if (
        isinstance(observation_id, bool)
        or not isinstance(observation_id, int)
        or observation_id < 1
    ):
        raise ValueError("Select an existing observation")

    values = {}

    for key, limit in [
        ("adviser_name", 200),
        ("adviser_role", 200),
        ("findings", 3000),
        ("basis", 3000),
        ("next_step", 3000),
    ]:
        value = data.get(key)

        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > limit
        ):
            label = key.replace("_", " ")
            raise ValueError(
                f"Complete {label} "
                f"(maximum {limit} characters)"
            )

        values[key] = value.strip()

    assessment = data.get("assessment")

    if assessment not in (
        "unconfirmed",
        "suspected",
        "adviser_reported_confirmation",
    ):
        raise ValueError("Choose a valid assessment")

    now = datetime.now(timezone.utc)
    raw_time = data.get("reviewed_at")

    reviewed = (
        now
        if raw_time is None or raw_time == ""
        else timestamp(raw_time)
    )

    if reviewed > now:
        raise ValueError(
            "Review time cannot be in the future"
        )

    with store.connect() as db:
        observation = db.execute(
            """
            SELECT observed_at, created
            FROM observations
            WHERE id = ?
            """,
            (observation_id,),
        ).fetchone()

        if observation is None:
            raise ValueError("Observation not found")

        original = (
            observation["observed_at"]
            or observation["created"]
        )

        try:
            original_time = datetime.fromisoformat(
                original.replace("Z", "+00:00")
            )
        except (AttributeError, ValueError):
            raise ValueError(
                "Original observation time is invalid"
            ) from None

        # Existing legacy records without an offset used UTC.
        if original_time.tzinfo is None:
            original_time = original_time.replace(
                tzinfo=timezone.utc
            )

        if reviewed < original_time:
            raise ValueError(
                "Review cannot predate the original observation"
            )

        db.execute(
            """
            INSERT INTO adviser_reviews (
                observation_id,
                adviser_name,
                adviser_role,
                reviewed_at,
                findings,
                assessment,
                basis,
                next_step,
                recorded_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observation_id,
                values["adviser_name"],
                values["adviser_role"],
                reviewed.isoformat(),
                values["findings"],
                assessment,
                values["basis"],
                values["next_step"],
                now.isoformat(),
            ),
        )