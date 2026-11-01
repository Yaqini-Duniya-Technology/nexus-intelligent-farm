import base64
import binascii
import hashlib
from datetime import datetime, timezone


PHOTO_SOURCES = (
    "farmer_photo",
    "adviser_photo",
    "test_image",
    "unknown",
)

MAX_IMAGE_BYTES = 2 * 1024 * 1024


def initialize_photos(store):
    with store.connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS observation_photos (
                id INTEGER PRIMARY KEY,
                observation_id INTEGER NOT NULL
                    REFERENCES observations(id),
                caption TEXT NOT NULL,
                image_data BLOB NOT NULL,
                sha256 TEXT NOT NULL,
                uploaded_at TEXT NOT NULL,
                UNIQUE(observation_id, sha256)
            );
        """)

        columns = {
            row["name"]
            for row in db.execute(
                "PRAGMA table_info(observation_photos)"
            )
        }

        if "source_kind" not in columns:
            db.execute("""
                ALTER TABLE observation_photos
                ADD COLUMN source_kind TEXT NOT NULL
                DEFAULT 'unknown'
            """)


def photo_state(store):
    with store.connect() as db:
        db.execute("BEGIN")

        observations = [
            dict(row)
            for row in db.execute("""
                SELECT
                    observations.id,
                    observations.note,
                    observations.category,
                    fields.name AS field_name,
                    fields.crop,
                    farms.name AS farm_name
                FROM observations
                JOIN fields
                    ON fields.id = observations.field_id
                JOIN farms
                    ON farms.id = fields.farm_id
                ORDER BY observations.id DESC
            """)
        ]

        photos = [
            dict(row)
            for row in db.execute("""
                SELECT
                    id,
                    observation_id,
                    caption,
                    sha256,
                    uploaded_at,
                    source_kind,
                    length(image_data) AS size_bytes
                FROM observation_photos
                ORDER BY id DESC
            """)
        ]

        return {
            "observations": observations,
            "photos": photos,
        }


def save_photo(store, data):
    source = data.get("source_kind", "unknown")

    if source not in PHOTO_SOURCES:
        raise ValueError("Choose a valid photo source")

    action = data.get("action", "upload")

    if action == "set_source":
        photo_id = data.get("photo_id")

        if (
            isinstance(photo_id, bool)
            or not isinstance(photo_id, int)
            or photo_id < 1
        ):
            raise ValueError("Select a valid photo")

        with store.connect() as db:
            cursor = db.execute(
                """
                UPDATE observation_photos
                SET source_kind = ?
                WHERE id = ?
                """,
                (source, photo_id),
            )

            if cursor.rowcount != 1:
                raise ValueError("Photo not found")

        return

    if action != "upload":
        raise ValueError("Unknown photo action")

    observation_id = data.get("observation_id")

    if (
        isinstance(observation_id, bool)
        or not isinstance(observation_id, int)
        or observation_id < 1
    ):
        raise ValueError("Select an existing observation")

    caption = data.get("caption")

    if (
        not isinstance(caption, str)
        or not caption.strip()
        or len(caption) > 1000
    ):
        raise ValueError(
            "Describe what the photo shows, "
            "maximum 1000 characters"
        )

    encoded = data.get("image_base64")

    if (
        not isinstance(encoded, str)
        or len(encoded) > 2800000
    ):
        raise ValueError(
            "Photo must be at most 2 MB after resizing"
        )

    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("Invalid photo encoding") from None

    if not 0 < len(raw) <= MAX_IMAGE_BYTES:
        raise ValueError(
            "Photo must be at most 2 MB after resizing"
        )

    # Boundary checks for the JPEG prepared by the page.
    # These checks do not fully decode or diagnose an image.
    if (
        not raw.startswith(b"\xff\xd8\xff")
        or not raw.endswith(b"\xff\xd9")
    ):
        raise ValueError(
            "Expected a JPEG photo prepared by the photo page"
        )

    digest = hashlib.sha256(raw).hexdigest()

    with store.connect() as db:
        observation = db.execute(
            "SELECT 1 FROM observations WHERE id = ?",
            (observation_id,),
        ).fetchone()

        if observation is None:
            raise ValueError("Observation not found")

        db.execute(
            """
            INSERT INTO observation_photos (
                observation_id,
                caption,
                image_data,
                sha256,
                uploaded_at,
                source_kind
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(observation_id, sha256) DO NOTHING
            """,
            (
                observation_id,
                caption.strip(),
                raw,
                digest,
                datetime.now(timezone.utc).isoformat(),
                source,
            ),
        )


def get_photo(store, photo_id):
    with store.connect() as db:
        row = db.execute(
            """
            SELECT image_data
            FROM observation_photos
            WHERE id = ?
            """,
            (photo_id,),
        ).fetchone()

        if row is None:
            raise ValueError("Photo not found")

        return bytes(row["image_data"])