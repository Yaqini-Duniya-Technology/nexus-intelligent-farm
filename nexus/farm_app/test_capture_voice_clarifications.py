import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
try:
    from nexus.farm_app.capture_review import capture_review
except ModuleNotFoundError:
    from capture_review import capture_review


def raw(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class BundleClarificationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'test.sqlite3'
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript('''CREATE TABLE farms(id INTEGER PRIMARY KEY,name TEXT);
                CREATE TABLE fields(id INTEGER PRIMARY KEY,farm_id INTEGER,name TEXT);
                CREATE TABLE observations(id INTEGER PRIMARY KEY,field_id INTEGER,note TEXT);
                CREATE TABLE tasks(id INTEGER PRIMARY KEY,observation_id INTEGER);
                INSERT INTO farms VALUES(1,'Test farm');
                INSERT INTO fields VALUES(1,1,'Test field');
                INSERT INTO observations VALUES(1,1,'Original transcript');
                INSERT INTO observations VALUES(2,1,'Other observation');
                INSERT INTO tasks VALUES(1,1);''')

    def add_answers(self, answer='Unknown', linked_observation=1):
        review = {'extraction': {'clarification_questions': ['Growth stage?']}}
        review_hash = hashlib.sha256(raw(review).encode()).hexdigest()
        payload = {'version': 'voice-clarification-answers-v1', 'observation_id': 1,
                   'review_id': 3, 'review_hash': review_hash, 'reporter': 'Test farmer',
                   'questions': ['Growth stage?'], 'answers': [answer]}
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript('''CREATE TABLE IF NOT EXISTS natlas_voice_observation_links(
                id INTEGER PRIMARY KEY,observation_id INTEGER,review_id INTEGER,provenance TEXT);
                CREATE TABLE IF NOT EXISTS voice_clarification_answers(
                id INTEGER PRIMARY KEY,observation_id INTEGER,link_id INTEGER,
                recorded_at TEXT,content_sha256 TEXT,payload TEXT);''')
            db.execute('INSERT OR IGNORE INTO natlas_voice_observation_links VALUES(1,?,3,?)',
                       (linked_observation,json.dumps({'human_review':review,'human_review_sha256':review_hash})))
            db.execute('INSERT INTO voice_clarification_answers(observation_id,link_id,recorded_at,content_sha256,payload) VALUES(1,1,?,?,?)',
                       ('2026-10-13T05:00:00+00:00',hashlib.sha256(raw(payload).encode()).hexdigest(),raw(payload)))

    def test_missing_optional_table_supported(self):
        result = capture_review(self.path,1)
        self.assertEqual(result['payload']['voice_clarification_history'],[])
        self.assertIn('voice_clarification_answers',result['payload']['unavailable_tables'])

    def test_capture_parsed_history_and_reuse(self):
        self.add_answers()
        first = capture_review(self.path,1)
        second = capture_review(self.path,1)
        self.assertEqual(first,second)
        self.assertEqual(first['payload']['bundle_version'],'human-review-bundle-v9')
        self.assertEqual(first['payload']['voice_clarification_history'][0]['payload']['answers'],['Unknown'])

    def test_later_answers_new_bundle_preserves_prior_payload(self):
        self.add_answers()
        first = capture_review(self.path,1)
        self.add_answers('Mature')
        second = capture_review(self.path,1)
        self.assertNotEqual(first['id'],second['id'])
        with closing(sqlite3.connect(self.path)) as db:
            saved = json.loads(db.execute('SELECT payload FROM decision_review_bundles WHERE id=?',(first['id'],)).fetchone()[0])
        self.assertEqual(saved,first['payload'])
        self.assertEqual(second['payload']['voice_clarification_history'][0]['payload']['answers'],['Mature'])
        self.assertEqual(len(second['payload']['voice_clarification_history']),2)

    def test_corrupt_answer_rejected_without_bundle(self):
        self.add_answers()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE voice_clarification_answers SET content_sha256='bad'")
        with self.assertRaises(ValueError): capture_review(self.path,1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='decision_review_bundles'").fetchone())

    def test_wrong_confirmation_observation_rejected(self):
        self.add_answers(linked_observation=2)
        with self.assertRaises(ValueError): capture_review(self.path,1)

    def test_unrelated_observation_excludes_answers(self):
        self.add_answers()
        self.assertEqual(capture_review(self.path,2)['payload']['voice_clarification_history'],[])


if __name__ == '__main__': unittest.main()
