import copy
import json
import tempfile
import unittest
from pathlib import Path

from nexus.farm_app.store import FarmStore
from nexus.farm_app.seasons import initialize_seasons, save_season
from nexus.farm_app.observation_seasons import initialize_observation_seasons, state, save, canonical, digest
from nexus.farm_app.capture_review import capture_review
from nexus.farm_app.season_context import assess, render_history
from nexus.farm_app.season_overview import overview_state, render_overview
from nexus.farm_app.review_bundles import bundle_page
from nexus.farm_app.review_readiness import summarize
from nexus.farm_app.evidence_quality import bundle_checks
from nexus.farm_app.decision_report import read_report


class SeasonContextIntegrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'farm.sqlite3'
        self.store = FarmStore(self.path)
        self.store.create('farms', {'name': 'TEST farm', 'location': 'Lokoja'})
        self.store.create('fields', {'farm_id': 1, 'name': 'TEST field', 'crop': 'maize'})
        for note in ('Small cobs', 'Other observation'):
            self.store.create('observations', {'field_id': 1, 'note': note})
        initialize_seasons(self.store)
        save_season(self.store, {'field_id': 1, 'name': '2026 maize', 'variety': 'Unknown',
                                'area_ha': 1, 'planting_date': '2026-04-01', 'expected_harvest_date': '2026-10-03'})
        initialize_observation_seasons(self.store)

    def add(self, sid=None, stage='unknown', reason='Initial reported context'):
        records = state(self.store)
        observation = next(o for o in records['observations'] if o['id'] == 1)
        season = next((s for s in records['seasons'] if s['id'] == sid), None)
        latest = next((h for h in records['history'] if h['observation_id'] == 1), None)
        return save(self.store, {'observation_id': 1, 'observation_hash': observation['selection_hash'],
                                'season_id': sid, 'season_hash': season['selection_hash'] if season else None,
                                'growth_stage': stage, 'reporter': 'TEST farmer', 'basis': 'TEST reported basis',
                                'reason': reason, 'base_id': latest['id'] if latest else None})

    def test_capture_reuses_and_freezes_full_history(self):
        self.add()
        first = capture_review(self.path, 1)
        self.assertEqual(first, capture_review(self.path, 1))
        self.assertEqual(first['payload']['bundle_version'], 'human-review-bundle-v9')
        self.add(1, 'maturing', 'Correction after reported examination')
        second = capture_review(self.path, 1)
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(len(second['payload']['observation_season_history']), 2)
        self.assertEqual(first['payload']['observation_season_history'][0]['payload']['growth_stage'], 'unknown')
        with self.store.connect() as db:
            stored = db.execute('SELECT payload FROM decision_review_bundles WHERE id=?', (first['id'],)).fetchone()
        self.assertEqual(json.loads(stored[0]), first['payload'])

    def test_missing_table_is_distinct_from_empty(self):
        empty = capture_review(self.path, 1)
        self.assertEqual(assess(empty['payload'])['status'], 'no_entry')
        with self.store.connect() as db:
            db.execute('DROP TABLE observation_season_history')
        missing = capture_review(self.path, 1)
        self.assertIsNone(missing['payload']['observation_season_history'])
        self.assertEqual(assess(missing['payload'])['status'], 'not_captured')

    def test_unrelated_observation_excluded(self):
        self.add()
        self.assertEqual(capture_review(self.path, 2)['payload']['observation_season_history'], [])

    def test_corrupt_entry_prevents_new_capture(self):
        self.add()
        with self.store.connect() as db:
            db.execute("UPDATE observation_season_history SET content_sha256='bad'")
        with self.assertRaisesRegex(ValueError, 'hash'):
            capture_review(self.path, 1)
        with self.store.connect() as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='decision_review_bundles'").fetchone())

    def test_valid_hash_wrong_season_field_is_rejected(self):
        self.add(1)
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM observation_season_history').fetchone()
            payload = json.loads(row['payload'])
            payload['season_at_capture']['field_id'] = 999
            db.execute('UPDATE observation_season_history SET payload=?,content_sha256=?', (canonical(payload), digest(payload)))
        with self.assertRaisesRegex(ValueError, 'different field'):
            capture_review(self.path, 1)

    def test_stage_and_unknown_checks_in_both_summaries(self):
        self.add()
        bundle = capture_review(self.path, 1)
        ready = summarize(bundle)
        self.assertEqual(ready['season_context']['growth_stage'], 'unknown')
        self.assertEqual(ready['season_context']['status'], 'recorded')
        checked = bundle_checks(bundle, 'supporting_bundle', 'original supporting')
        self.assertEqual(checked['season_context']['entries'], 1)
        self.assertTrue(any('Season linkage' in f['message'] for f in checked['findings']))

    def test_tampered_frozen_entry_flagged_without_mutation(self):
        self.add(1)
        bundle = capture_review(self.path, 1)
        bundle['payload']['observation_season_history'][0]['payload']['basis'] = 'Changed'
        before = copy.deepcopy(bundle)
        self.assertEqual(assess(bundle['payload'])['status'], 'invalid')
        self.assertIn('invalid', render_history(bundle['payload']))
        self.assertEqual(bundle, before)

    def test_renderer_shows_history_and_escapes_reporter(self):
        self.add(1)
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM observation_season_history').fetchone()
            payload = json.loads(row['payload'])
            payload['reporter'] = '<script>alert(1)</script>'
            db.execute('UPDATE observation_season_history SET payload=?,content_sha256=?', (canonical(payload), digest(payload)))
        bundle = capture_review(self.path, 1)
        output = bundle_page(bundle)
        self.assertIn('Season context entry #1', output)
        self.assertIn('&lt;script&gt;', output)
        self.assertNotIn('<script>alert', output)

    def test_legacy_bundle_renderer_does_not_use_current_context(self):
        self.add(1)
        self.assertIn('not available', render_history({'observation': {'id': 1, 'field_id': 1}}))

    def test_overview_counts_unknown_and_unrecorded(self):
        self.add()
        data = overview_state(self.store)
        self.assertEqual(data['counts'], {'unknown': 1, 'unrecorded': 1, 'linked': 0, 'needs_recheck': 0})
        self.assertIn('TEST field', render_overview(data))

    def test_overview_marks_changed_season_for_review(self):
        self.add(1, 'maturing')
        bundle = capture_review(self.path, 1)
        with self.store.connect() as db:
            db.execute("UPDATE crop_seasons SET name='Edited season' WHERE id=1")
        self.assertEqual(overview_state(self.store)['counts']['needs_recheck'], 1)
        self.assertEqual(assess(bundle['payload'])['status'], 'recorded')
        self.assertEqual(bundle['payload']['observation_season_history'][0]['payload']['season_at_capture']['name'], '2026 maize')

    def test_report_uses_original_and_reviewed_bundle_not_live_context(self):
        import hashlib
        first = capture_review(self.path, 1)
        self.add(1, 'maturing')
        newer = capture_review(self.path, 1)
        with self.store.connect() as db:
            db.executescript('''CREATE TABLE human_decisions(id INTEGER PRIMARY KEY,bundle_id INTEGER,payload TEXT,recorded_at TEXT);
                CREATE TABLE decision_events(id INTEGER PRIMARY KEY,decision_id INTEGER,occurred_at TEXT,kind TEXT);
                CREATE TABLE human_decision_reviews(id INTEGER PRIMARY KEY,decision_id INTEGER,evidence_bundle_id INTEGER,evidence_bundle_sha256 TEXT);''')
            db.execute('INSERT INTO human_decisions VALUES(1,?,?,?)', (first['id'], '{}', first['captured_at']))
            db.execute('INSERT INTO human_decision_reviews VALUES(1,1,?,?)', (newer['id'], newer['content_sha256']))
        self.add(None, reason='Later unknown linkage')
        report = read_report(self.store, 1)
        self.assertEqual(report['bundle']['payload']['observation_season_history'], [])
        frozen = report['season_evidence'][0]['payload']['observation_season_history']
        self.assertEqual(len(frozen), 1)
        self.assertEqual(frozen[0]['payload']['growth_stage'], 'maturing')
        with self.store.connect() as db:
            db.execute("UPDATE human_decision_reviews SET evidence_bundle_sha256='bad'")
        self.assertEqual(read_report(self.store, 1)['season_evidence'], [])


if __name__ == '__main__':
    unittest.main()
