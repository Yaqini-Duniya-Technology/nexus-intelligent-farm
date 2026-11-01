from contextlib import closing


TRIGGER = '''
CREATE TRIGGER IF NOT EXISTS skip_unchanged_field_context
BEFORE INSERT ON field_context_versions
WHEN EXISTS (
    SELECT 1
    FROM field_context_versions AS previous
    WHERE previous.id = (
        SELECT MAX(id)
        FROM field_context_versions
        WHERE field_id = NEW.field_id
    )
    AND previous.context_date IS NEW.context_date
    AND previous.location IS NEW.location
    AND previous.location_precision IS NEW.location_precision
    AND previous.latitude IS NEW.latitude
    AND previous.longitude IS NEW.longitude
    AND previous.soil_type IS NEW.soil_type
    AND previous.crop_stage IS NEW.crop_stage
    AND previous.water_access IS NEW.water_access
    AND previous.resources IS NEW.resources
    AND previous.basis IS NEW.basis
)
BEGIN
    SELECT RAISE(IGNORE);
END;
'''


def install_guard(store):
    with store.connect() as db:
        db.execute(TRIGGER)


def main():
    from nexus.farm_app import field_context

    original = field_context.initialize_context

    def initialize_with_guard(store):
        original(store)
        install_guard(store)

    field_context.initialize_context = initialize_with_guard

    print(
        'Unchanged field-context submissions are skipped. '
        'Existing versions are preserved.',
        flush=True,
    )

    try:
        field_context.main()
    finally:
        field_context.initialize_context = original


if __name__ == '__main__':
    main()