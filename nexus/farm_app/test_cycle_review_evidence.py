import ast
from contextlib import closing
import hashlib
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

try:
    from nexus.farm_app import capture_decision_cycle as module
except ModuleNotFoundError as error:
    if error.name not in ('nexus', 'nexus.farm_app'):
        raise
    spec = importlib.util.spec_from_file_location('cycle_capture', Path(__file__).with_name('capture_decision_cycle.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


class CycleReviewEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'test.sqlite3'
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript('''
                CREATE TABLE human_decisions(id INTEGER PRIMARY KEY, bundle_id INTEGER, payload TEXT);
                CREATE TABLE decision_review_bundles(id INTEGER PRIMARY KEY, observation_id INTEGER,
                    captured_at TEXT, content_sha256 TEXT, payload TEXT);
                CREATE TABLE decision_events(id INTEGER PRIMARY KEY, decision_id INTEGER, kind TEXT);
                CREATE TABLE human_decision_reviews(id INTEGER PRIMARY KEY, decision_id INTEGER,
                    disposition TEXT, next_review_date TEXT, reviewed_at TEXT,
                    evidence_bundle_id INTEGER, evidence_bundle_sha256 TEXT);
            ''')
            for bid in (5, 7):
                raw = json.dumps({'bundle': bid}, sort_keys=True, ensure_ascii=False, allow_nan=False)
                digest = hashlib.sha256(raw.encode()).hexdigest()
                db.execute('INSERT INTO decision_review_bundles VALUES(?,?,?,?,?)',
                           (bid, 5, '2026-10-13T18:00:00+00:00', digest, raw))
                if bid == 7:
                    self.digest = digest
            db.execute('INSERT INTO human_decisions VALUES(2,5,?)',
                       (json.dumps({'review_date': '2026-10-16'}),))
            db.execute('INSERT INTO human_decision_reviews VALUES(2,2,?,?,?,7,?)',
                       ('keep', '2026-10-16', '2026-10-13T19:04:06+00:00', self.digest))

    def change(self, sql):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(sql)

    def test_freezes_evidence_and_reuses_identical_capture(self):
        saved = module.capture(self.path, 2)
        self.assertEqual(saved['payload']['snapshot_version'], 'decision-cycle-v2')
        self.assertEqual(saved['payload']['supporting_bundle']['id'], 5)
        entry = saved['payload']['review_evidence_bundles'][0]
        self.assertEqual(entry['bundle']['id'], 7)
        self.assertEqual(entry['review_ids'], [2])
        self.assertEqual(module.capture(self.path, 2), saved)
        self.change("UPDATE decision_review_bundles SET payload='{}' WHERE id=7")
        with self.assertRaises(ValueError):
            module.capture(self.path, 2)
        with closing(sqlite3.connect(self.path)) as db, db:
            frozen = json.loads(db.execute('SELECT payload FROM decision_cycle_snapshots').fetchone()[0])
        self.assertEqual(frozen, saved['payload'])

    def test_missing_mismatched_cross_observation_and_future_rejected(self):
        changes = [
            'DELETE FROM decision_review_bundles WHERE id=7',
            "UPDATE decision_review_bundles SET content_sha256='bad' WHERE id=7",
            'UPDATE decision_review_bundles SET observation_id=99 WHERE id=7',
            "UPDATE decision_review_bundles SET captured_at='2026-10-14T00:00:00+00:00' WHERE id=7",
            "UPDATE human_decision_reviews SET evidence_bundle_sha256='bad'",
        ]
        for sql in changes:
            with self.subTest(sql=sql):
                # Roll back each fixture mutation after exercising capture on another DB.
                copy = self.path.with_name('copy.sqlite3')
                copy.write_bytes(self.path.read_bytes())
                with closing(sqlite3.connect(copy)) as db, db:
                    db.execute(sql)
                with self.assertRaises(ValueError):
                    module.capture(copy, 2)
                with closing(sqlite3.connect(copy)) as db, db:
                    self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='decision_cycle_snapshots'").fetchone())
                copy.unlink()

    def test_deduplicates_bundle_retaining_each_review(self):
        self.change('INSERT INTO human_decision_reviews SELECT 3,decision_id,disposition,next_review_date,reviewed_at,evidence_bundle_id,evidence_bundle_sha256 FROM human_decision_reviews')
        entries = module.capture(self.path, 2)['payload']['review_evidence_bundles']
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['review_ids'], [3, 2])

    def test_no_references_and_legacy_columns(self):
        self.change('UPDATE human_decision_reviews SET evidence_bundle_id=NULL,evidence_bundle_sha256=NULL')
        self.assertEqual(module.capture(self.path, 2)['payload']['review_evidence_bundles'], [])
        self.change('ALTER TABLE human_decision_reviews DROP COLUMN evidence_bundle_id')
        self.change('ALTER TABLE human_decision_reviews DROP COLUMN evidence_bundle_sha256')
        self.assertEqual(module.capture(self.path, 2)['payload']['review_evidence_bundles'], [])

    def test_absent_review_table(self):
        self.change('DROP TABLE human_decision_reviews')
        saved = module.capture(self.path, 2)['payload']
        self.assertEqual(saved['review_evidence_bundles'], [])
        self.assertFalse(saved['review_tracking']['records_available'])

    def test_older_snapshot_bytes_preserved(self):
        module.capture(self.path, 2)
        self.change("UPDATE decision_cycle_snapshots SET payload='{\"snapshot_version\":\"decision-cycle-v1\"}',content_sha256='old' WHERE id=1")
        module.capture(self.path, 2)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute('SELECT payload FROM decision_cycle_snapshots WHERE id=1').fetchone()[0], '{"snapshot_version":"decision-cycle-v1"}')

    def test_viewer_uses_only_frozen_data(self):
        # Isolate the renderer from the local web-app import chain.
        source = Path(__file__).with_name('decision_cycles.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'render_frozen_review_evidence')
        scope = {'records': lambda title, rows: title + json.dumps(rows)}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<viewer>', 'exec'), scope)
        render = scope['render_frozen_review_evidence']
        self.assertIn('older snapshot', render({}))
        self.assertIn('No additional evidence', render({'review_evidence_bundles': []}))
        output = render(module.capture(self.path, 2)['payload'])
        self.assertIn('Reviewed bundle #7', output)
        self.assertIn('referencing_review_ids', output)


if __name__ == '__main__':
    unittest.main()
