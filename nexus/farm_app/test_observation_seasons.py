import ast
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

try:
    from nexus.farm_app import observation_seasons as module
except ModuleNotFoundError as error:
    if error.name not in ('nexus', 'nexus.farm_app'):
        raise
    spec = importlib.util.spec_from_file_location('season_links', Path(__file__).with_name('observation_seasons.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


class Store:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()


class ObservationSeasonTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Store(Path(temp.name) / 'test.sqlite3')
        with self.store.connect() as db:
            db.executescript('''
                CREATE TABLE farms(id INTEGER PRIMARY KEY,name TEXT);
                CREATE TABLE fields(id INTEGER PRIMARY KEY,farm_id INTEGER,name TEXT,crop TEXT);
                CREATE TABLE observations(id INTEGER PRIMARY KEY,field_id INTEGER,note TEXT,created TEXT,observed_at TEXT);
                CREATE TABLE crop_seasons(id INTEGER PRIMARY KEY,field_id INTEGER,name TEXT,crop TEXT,variety TEXT,area_ha REAL,planting_date TEXT,expected_harvest_date TEXT,created_at TEXT);
                CREATE TABLE tasks(id INTEGER PRIMARY KEY,status TEXT);
                CREATE TABLE review_snapshots(id INTEGER PRIMARY KEY,payload TEXT);
                INSERT INTO farms VALUES(1,'TEST');
                INSERT INTO fields VALUES(1,1,'North','maize'),(2,1,'South','maize');
                INSERT INTO observations VALUES(5,1,'Small cobs','2026-10-11T12:00:00+00:00','2026-10-11T09:43:00+00:00');
                INSERT INTO crop_seasons VALUES(1,1,'2026 maize','maize','Unknown',1,'2026-04-01','2026-10-03','2026-01-01');
                INSERT INTO crop_seasons VALUES(2,2,'Other field','maize','Unknown',1,'2026-04-01','2026-10-03','2026-01-01');
                INSERT INTO tasks VALUES(5,'pending');
                INSERT INTO review_snapshots VALUES(5,'Original frozen record');
            ''')
        module.initialize_observation_seasons(self.store)

    def data(self, season_id=1):
        state = module.state(self.store)
        season = next((s for s in state['seasons'] if s['id'] == season_id), None)
        latest = next(iter(state['history']), None)
        return {'observation_id': 5, 'observation_hash': state['observations'][0]['selection_hash'],
                'season_id': season_id, 'season_hash': season['selection_hash'] if season else None,
                'base_id': latest['id'] if latest else None, 'growth_stage': 'unknown',
                'reporter': 'TEST farmer', 'basis': 'Season identity checked; growth stage unknown.',
                'reason': 'Initial reported context.'}

    def test_persistence_freezes_season_and_preserves_original_records(self):
        module.save(self.store, self.data())
        with self.store.connect() as db:
            db.execute("UPDATE crop_seasons SET name='Revised' WHERE id=1")
            self.assertEqual(db.execute('SELECT status FROM tasks').fetchone()[0], 'pending')
            self.assertEqual(db.execute('SELECT payload FROM review_snapshots').fetchone()[0], 'Original frozen record')
        saved = module.state(Store(self.store.path))['history'][0]['payload']
        self.assertEqual(saved['season_at_capture']['name'], '2026 maize')
        self.assertEqual(saved['observation_at_capture']['note'], 'Small cobs')

    def test_retry_reuses_and_correction_appends(self):
        data = self.data()
        first = module.save(self.store, data)
        self.assertEqual(module.save(self.store, data), {'id': first['id'], 'reused': True})
        revised = self.data(None)
        revised['reason'] = 'Correction: season identity remains unresolved.'
        module.save(self.store, revised)
        rows = module.state(self.store)['history']
        self.assertEqual(len(rows), 2)
        self.assertIsNone(rows[0]['payload']['season_at_capture'])
        self.assertEqual(rows[1]['payload']['season_id'], 1)

    def test_stale_form_rejected(self):
        stale = self.data()
        module.save(self.store, stale)
        stale['basis'] = 'Changed basis on stale form'
        with self.assertRaisesRegex(ValueError, 'newer context'):
            module.save(self.store, stale)
        self.assertEqual(len(module.state(self.store)['history']), 1)

    def test_stale_observation_and_season_rejected(self):
        data = self.data()
        with self.store.connect() as db:
            db.execute("UPDATE observations SET note='Updated note' WHERE id=5")
        with self.assertRaisesRegex(ValueError, 'Observation changed'):
            module.save(self.store, data)
        data = self.data()
        with self.store.connect() as db:
            db.execute("UPDATE crop_seasons SET planting_date='2026-05-01' WHERE id=1")
        with self.assertRaisesRegex(ValueError, 'Season changed'):
            module.save(self.store, data)
        self.assertEqual(module.state(self.store)['history'], [])

    def test_cross_field_and_missing_season_rejected(self):
        with self.assertRaisesRegex(ValueError, 'same|belong'):
            module.save(self.store, self.data(2))
        with self.assertRaisesRegex(ValueError, 'not found'):
            module.save(self.store, self.data(999))
        self.assertEqual(module.state(self.store)['history'], [])

    def test_validation_saves_nothing(self):
        for change in [{'observation_id': True}, {'season_id': True}, {'base_id': True},
                       {'growth_stage': 'guessed'}, {'reporter': ''}, {'basis': ' '},
                       {'reason': 'x' * 3001}, {'season_id': None, 'season_hash': 'bad'}]:
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    module.save(self.store, {**self.data(), **change})
        self.assertEqual(module.state(self.store)['history'], [])

    def test_corrupt_history_rejected(self):
        module.save(self.store, self.data())
        with self.store.connect() as db:
            db.execute("UPDATE observation_season_history SET content_sha256='bad'")
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            module.state(self.store)
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            module.save(self.store, self.data_from_raw())

    def data_from_raw(self):
        with self.store.connect() as db:
            o = dict(db.execute('SELECT * FROM observations').fetchone())
            s = dict(db.execute('SELECT * FROM crop_seasons WHERE id=1').fetchone())
        return {'observation_id': 5, 'observation_hash': module.digest(o), 'season_id': 1,
                'season_hash': module.digest(s), 'base_id': 1, 'growth_stage': 'unknown',
                'reporter': 'TEST farmer', 'basis': 'basis', 'reason': 'reason'}

    def test_insert_failure_rolls_back(self):
        with self.store.connect() as db:
            db.execute("CREATE TRIGGER fail_context BEFORE INSERT ON observation_season_history BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            module.save(self.store, self.data())
        self.assertEqual(module.state(self.store)['history'], [])

    def test_initialize_is_idempotent(self):
        module.save(self.store, self.data(None))
        module.initialize_observation_seasons(self.store)
        self.assertEqual(len(module.state(self.store)['history']), 1)

    def test_server_routes_use_existing_origin_and_size_checks(self):
        source = Path(__file__).with_name('server.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        factory = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'make_handler')
        handler = next(n for n in factory.body if isinstance(n, ast.ClassDef))
        post = next(n for n in handler.body if isinstance(n, ast.FunctionDef) and n.name == 'do_POST')
        # Run the real POST handler with a harmless in-memory request object.
        import io
        from urllib.parse import urlparse
        calls = []
        scope = {'urlparse': urlparse, 'json': json, 'sqlite3': sqlite3, 'store': self.store,
                 'save_observation_season': lambda store, data: (calls.append(data) or {'id': 1})}
        exec(compile(ast.Module(body=[post], type_ignores=[]), '<server POST>', 'exec'), scope)
        def request(origin):
            body = json.dumps(self.data()).encode()
            obj = type('Request', (), {})()
            obj.path = '/api/observation-seasons'
            obj.headers = {'Origin': origin, 'Host': '127.0.0.1:8080', 'Content-Length': str(len(body))}
            obj.rfile = io.BytesIO(body)
            obj.respond = lambda *args: calls.append(args)
            scope['do_POST'](obj)
        request('http://evil.example')
        self.assertEqual(calls[0][0], 403)
        self.assertEqual(len(calls), 1)
        calls.clear()
        request('http://127.0.0.1:8080')
        self.assertEqual(calls[0]['observation_id'], 5)
        self.assertEqual(calls[1][0], 200)


if __name__ == '__main__':
    unittest.main()
