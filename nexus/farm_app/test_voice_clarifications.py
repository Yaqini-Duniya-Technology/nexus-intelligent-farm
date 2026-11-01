import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

try:
    from nexus.farm_app import voice_clarifications as module
except ModuleNotFoundError:
    import voice_clarifications as module


class Store:
    def __init__(self, path):
        self.path = path

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        try:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            with db:
                yield db
        finally:
            db.close()


class ClarificationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Store(str(Path(temp.name) / 'test.sqlite3'))
        review = {'extraction': {'clarification_questions': ['Growth stage?', 'How many?']}}
        self.digest = module.hashlib.sha256(module.canonical(review).encode()).hexdigest()
        with self.store.connect() as db:
            db.executescript('''CREATE TABLE fields(id INTEGER PRIMARY KEY, name TEXT);
                CREATE TABLE observations(id INTEGER PRIMARY KEY, field_id INTEGER, note TEXT);
                CREATE TABLE natlas_voice_observation_links(id INTEGER PRIMARY KEY,
                    observation_id INTEGER, review_id INTEGER, provenance TEXT);
                INSERT INTO fields VALUES(1, 'Test field');
                INSERT INTO observations VALUES(1,1,'Original Hausa text');''')
            db.execute('INSERT INTO natlas_voice_observation_links VALUES(1,1,3,?)',
                       (json.dumps({'human_review': review, 'human_review_sha256': self.digest}),))
        module.initialize(self.store)
        self.data = {'observation_id': 1, 'base_id': 0, 'review_hash': self.digest,
                     'reporter': 'Test farmer', 'answers': ['Unknown', '10 checked; 3 affected']}

    def test_persistence_and_original_capture_unchanged(self):
        with self.store.connect() as db:
            before = db.execute('SELECT provenance FROM natlas_voice_observation_links').fetchone()[0]
        module.save(self.store, self.data)
        state = module.state(Store(self.store.path))
        self.assertEqual(state['history'][0]['payload']['answers'], self.data['answers'])
        with self.store.connect() as db:
            self.assertEqual(before, db.execute('SELECT provenance FROM natlas_voice_observation_links').fetchone()[0])
            self.assertEqual(db.execute('SELECT note FROM observations').fetchone()[0], 'Original Hausa text')

    def test_double_save_reuses_and_revision_preserves_history(self):
        first = module.save(self.store, self.data)
        repeat = module.save(self.store, self.data)
        self.assertTrue(repeat['reused'])
        self.assertEqual(first['id'], repeat['id'])
        module.save(self.store, {**self.data, 'base_id': first['id'], 'answers': ['Mature', '10 checked; 3 affected']})
        self.assertEqual(len(module.state(self.store)['history']), 2)

    def test_stale_form_rejected_without_extra_entry(self):
        module.save(self.store, self.data)
        with self.assertRaises(ValueError):
            module.save(self.store, {**self.data, 'answers': ['Changed', 'Changed']})
        self.assertEqual(len(module.state(self.store)['history']), 1)

    def test_invalid_answers_or_context_save_nothing(self):
        for changes in ({'answers': ['Only one']}, {'answers': ['', 'Unknown']},
                        {'review_hash': 'wrong'}, {'reporter': ''}, {'observation_id': True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                module.save(self.store, {**self.data, **changes})
        self.assertEqual(module.state(self.store)['history'], [])

    def test_corrupt_review_rejected(self):
        with self.store.connect() as db:
            db.execute("UPDATE natlas_voice_observation_links SET provenance=?",
                       (json.dumps({'human_review': {}, 'human_review_sha256': self.digest}),))
        with self.assertRaises(ValueError):
            module.save(self.store, self.data)
        self.assertEqual(module.state(self.store)['history'], [])
        self.assertIn('error', module.state(self.store)['observations'][0])


if __name__ == '__main__':
    unittest.main()
