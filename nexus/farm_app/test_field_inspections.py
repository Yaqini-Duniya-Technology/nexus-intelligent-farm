import copy
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from nexus.farm_app.store import FarmStore
from nexus.farm_app import field_inspections as module
from nexus.farm_app.capture_review import capture_review
from nexus.farm_app.review_bundles import bundle_page
from nexus.farm_app.review_readiness import summarize
from nexus.farm_app.evidence_quality import bundle_checks
from nexus.farm_app.server import make_handler


class InspectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'farm.db'
        self.store = FarmStore(self.path)
        self.store.create('farms', {'name': 'TEST farm', 'location': 'Lokoja'})
        self.store.create('fields', {'farm_id': 1, 'name': 'TEST field', 'crop': 'maize'})
        self.when = datetime.now(timezone.utc) - timedelta(hours=1)
        for note in ('Small cobs', 'Other observation'):
            self.store.create('observations', {'field_id': 1, 'note': note,
                              'observed_at': self.when.isoformat()})
        module.initialize(self.store)

    def data(self, **changes):
        records = module.state(self.store)
        observation = next(o for o in records['observations'] if o['id'] == 1)
        latest = next((r for r in records['history'] if r['observation_id'] == 1), None)
        return dict({'observation_id': 1, 'observation_hash': observation['selection_hash'],
                     'base_id': latest['id'] if latest else None, 'supersedes_id': None,
                     'performed_at': (self.when + timedelta(minutes=10)).isoformat(),
                     'reporter': 'TEST farmer', 'area': 'South side',
                     'sampling_method': 'Reported sample; selection method unknown',
                     'observation_definition': 'Plants with small cobs, size criterion not measured',
                     'findings': 'TEST inspection. Season and growth stage remain unknown.',
                     'reason': 'Initial entry', 'plants_checked': 40, 'plants_affected': 19,
                     'cobs_checked': None, 'newly_forming_cobs': None,
                     'mature_small_cobs': None, 'uncertain_cobs': None}, **changes)

    def test_save_and_reopen_preserves_units_and_unknown(self):
        saved = module.save(self.store, self.data())
        reopened = FarmStore(self.path)
        row = module.state(reopened)['history'][0]
        self.assertEqual(row['id'], saved['id'])
        self.assertEqual(row['payload']['plants_checked'], 40)
        self.assertEqual(row['payload']['plants_affected'], 19)
        self.assertIsNone(row['payload']['cobs_checked'])
        self.assertEqual(module.digest(row['payload']), row['content_sha256'])
        with reopened.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM task_actions').fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT status FROM tasks WHERE observation_id=1").fetchone()[0], 'pending')

    def test_unknown_counts_and_observed_zero_are_distinct(self):
        module.save(self.store, self.data(plants_checked=None, plants_affected=None))
        module.save(self.store, self.data(plants_checked=40, plants_affected=0, reason='Later inspection'))
        rows = module.state(self.store)['history']
        self.assertEqual(rows[0]['payload']['plants_affected'], 0)
        self.assertIsNone(rows[1]['payload']['plants_affected'])

    def test_invalid_counts_save_nothing(self):
        cases = [{'plants_checked': True}, {'plants_checked': -1}, {'plants_checked': 2.5},
                 {'plants_checked': '40'}, {'plants_checked': 1000001}, {'plants_affected': 41},
                 {'plants_checked': None}, {'plants_affected': float('nan')},
                 {'cobs_checked': False}, {'newly_forming_cobs': 2},
                 {'cobs_checked': 10, 'newly_forming_cobs': 2, 'mature_small_cobs': 3, 'uncertain_cobs': 4}]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                module.save(self.store, self.data(**case))
        self.assertEqual(module.state(self.store)['history'], [])

    def test_cob_groups_use_cob_denominator(self):
        module.save(self.store, self.data(cobs_checked=50, newly_forming_cobs=20,
                    mature_small_cobs=10, uncertain_cobs=20))
        row = module.state(self.store)['history'][0]['payload']
        self.assertEqual(row['plants_checked'], 40)
        self.assertEqual(row['cobs_checked'], 50)
        self.assertEqual(row['mature_small_cobs'], 10)

    def test_reuse_and_explicit_correction_preserve_prior(self):
        data = self.data()
        first = module.save(self.store, data)
        self.assertEqual(module.save(self.store, data), {'id': first['id'], 'reused': True})
        before = module.state(self.store)['history'][0]
        second = module.save(self.store, self.data(supersedes_id=first['id'], plants_affected=18,
                                                  reason='Correction: recounted sample'))
        history = module.state(self.store)['history']
        self.assertEqual(history[1], before)
        self.assertEqual(history[0]['supersedes_id'], first['id'])
        self.assertNotEqual(first['id'], second['id'])
        with self.assertRaises(ValueError):
            module.save(self.store, self.data(supersedes_id=first['id'], reason='Branch correction'))

    def test_stale_form_and_observation_rejected(self):
        stale = self.data()
        module.save(self.store, self.data())
        with self.assertRaises(ValueError):
            module.save(self.store, {**stale, 'reason': 'Other browser entry'})
        with self.assertRaises(ValueError):
            module.save(self.store, self.data(observation_hash='bad'))
        self.assertEqual(len(module.state(self.store)['history']), 1)

    def test_bad_references_times_and_text_save_nothing(self):
        for changes in ({'observation_id': True}, {'observation_id': 999}, {'reporter': ' '},
                        {'reason': 'x'*1001}, {'supersedes_id': 99}, {'base_id': True},
                        {'performed_at': 'not a time'}, {'performed_at': '2026-10-01T10:00:00'},
                        {'performed_at': (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()},
                        {'performed_at': (self.when-timedelta(seconds=1)).isoformat()}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                module.save(self.store, self.data(**changes))
        self.assertEqual(module.state(self.store)['history'], [])

    def test_other_observation_cannot_be_correction_target(self):
        module.save(self.store, self.data())
        records = module.state(self.store)
        other = next(o for o in records['observations'] if o['id'] == 2)
        with self.assertRaises(ValueError):
            module.save(self.store, self.data(observation_id=2, observation_hash=other['selection_hash'],
                                             base_id=None, supersedes_id=1))

    def test_new_capture_freezes_inspections_and_old_bytes(self):
        first = capture_review(self.path, 1)
        module.save(self.store, self.data())
        second = capture_review(self.path, 1)
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(first['payload']['field_inspections'], [])
        self.assertEqual(len(second['payload']['field_inspections']), 1)
        self.assertEqual(second, capture_review(self.path, 1))
        module.save(self.store, self.data(supersedes_id=1, plants_affected=18, reason='Recount'))
        self.assertEqual(second['payload']['field_inspections'][0]['payload']['plants_affected'], 19)
        with self.store.connect() as db:
            frozen = json.loads(db.execute('SELECT payload FROM decision_review_bundles WHERE id=?',
                                          (second['id'],)).fetchone()[0])
        self.assertEqual(frozen, second['payload'])

    def test_missing_history_not_live_substituted(self):
        module.save(self.store, self.data())
        self.assertEqual(module.assess({'observation': {'id': 1}})['status'], 'not_captured')
        self.assertNotIn('South side', module.render_history({'observation': {'id': 1}}))
        other = capture_review(self.path, 2)
        self.assertEqual(other['payload']['field_inspections'], [])
        with self.store.connect() as db:
            db.execute('DROP TABLE field_inspections')
        missing = capture_review(self.path, 1)
        self.assertIsNone(missing['payload']['field_inspections'])

    def test_corrupt_history_aborts_capture(self):
        module.save(self.store, self.data())
        with self.store.connect() as db:
            db.execute("UPDATE field_inspections SET content_sha256='bad'")
        with self.assertRaises(ValueError):
            capture_review(self.path, 1)
        with self.store.connect() as db:
            self.assertFalse(db.execute("SELECT name FROM sqlite_master WHERE name='decision_review_bundles'").fetchone())

    def test_readiness_evidence_and_escaping(self):
        module.save(self.store, self.data(reporter='<script>bad()</script>'))
        bundle = capture_review(self.path, 1)
        self.assertEqual(summarize(bundle)['inspections']['entries'], 1)
        self.assertEqual(bundle_checks(bundle, 'supporting_bundle', 'original')['inspections']['status'], 'recorded')
        html = bundle_page(bundle)
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('<script>bad()', html)
        bad = copy.deepcopy(bundle['payload'])
        bad['field_inspections'][0]['payload']['plants_affected'] = 99
        self.assertEqual(module.assess(bad)['status'], 'invalid')

    def test_reports_and_cycles_use_frozen_original_and_reviewed_inspections(self):
        from nexus.farm_app.decision_report import read_report, render_report
        from nexus.farm_app.capture_decision_cycle import capture
        from nexus.farm_app.decision_cycles import render_cycle
        original = capture_review(self.path, 1)
        module.save(self.store, self.data())
        reviewed = capture_review(self.path, 1)
        now = datetime.now(timezone.utc).isoformat()
        with self.store.connect() as db:
            db.executescript("""CREATE TABLE human_decisions(id INTEGER PRIMARY KEY,bundle_id INTEGER,payload TEXT,recorded_at TEXT);
                CREATE TABLE decision_events(id INTEGER PRIMARY KEY,decision_id INTEGER,occurred_at TEXT,kind TEXT);
                CREATE TABLE human_decision_reviews(id INTEGER PRIMARY KEY,decision_id INTEGER,
                evidence_bundle_id INTEGER,evidence_bundle_sha256 TEXT,reviewed_at TEXT,recorded_at TEXT,
                reviewer TEXT,conclusion TEXT,disposition TEXT,next_review_date TEXT);""")
            db.execute('INSERT INTO human_decisions VALUES(1,?,?,?)',
                       (original['id'], json.dumps({'review_date': '2026-11-02'}), now))
            db.execute('INSERT INTO human_decision_reviews VALUES(1,1,?,?,?,?,?,?,?,?)',
                       (reviewed['id'], reviewed['content_sha256'], now, now,
                        'TEST reviewer', 'TEST reviewed records', 'keep', '2026-11-02'))
        module.save(self.store, self.data(supersedes_id=1, plants_affected=18, reason='LIVE ONLY CORRECTION'))
        report = read_report(self.store, 1)
        html = render_report(report)
        self.assertIn('Inspections in reviewed bundle #', html)
        self.assertIn('South side', html)
        self.assertNotIn('LIVE ONLY CORRECTION', html)
        self.assertEqual(report['bundle']['payload']['field_inspections'], [])
        snapshot = capture(self.path, 1)
        frozen = snapshot['payload']['review_evidence_bundles'][0]['bundle']['payload']['field_inspections']
        self.assertEqual(frozen[0]['payload']['plants_affected'], 19)
        self.assertEqual(len(frozen), 1)
        self.assertNotIn('LIVE ONLY CORRECTION', render_cycle({**snapshot, 'hash_matches': True}))

    def test_http_get_save_error_and_origin(self):
        server = HTTPServer(('127.0.0.1', 0), make_handler(self.store))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close(), thread.join()))
        base = 'http://127.0.0.1:' + str(server.server_port)
        with urlopen(base+'/field-inspections') as response:
            self.assertIn(b'Cob counts and maturity groups', response.read())
        def post(data, origin=base):
            request = Request(base+'/api/field-inspections', data=json.dumps(data).encode(),
                              headers={'Content-Type':'application/json', 'Origin':origin})
            with urlopen(request) as response:
                return json.load(response)
        self.assertEqual(post(self.data())['id'], 1)
        with urlopen(base+'/api/field-inspections') as response:
            self.assertEqual(len(json.load(response)['history']), 1)
        with self.assertRaises(HTTPError) as invalid:
            post(self.data(plants_affected=100))
        self.assertEqual(invalid.exception.code, 400)
        with self.assertRaises(HTTPError) as blocked:
            post(self.data(), 'http://example.invalid')
        self.assertEqual(blocked.exception.code, 403)


if __name__ == '__main__':
    unittest.main()
