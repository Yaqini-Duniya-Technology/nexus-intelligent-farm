import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
try:
    from nexus.farm_app.capture_review import capture_review
    from nexus.farm_app.review_readiness import summarize
except ModuleNotFoundError:
    from capture_review import capture_review
    from review_readiness import summarize


class LinkedDecisionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'test.sqlite3'
        with closing(sqlite3.connect(self.path)) as db,db:
            db.executescript('''CREATE TABLE farms(id INTEGER PRIMARY KEY);
                CREATE TABLE fields(id INTEGER PRIMARY KEY,farm_id INTEGER);
                CREATE TABLE observations(id INTEGER PRIMARY KEY,field_id INTEGER);
                CREATE TABLE tasks(id INTEGER PRIMARY KEY,observation_id INTEGER);
                CREATE TABLE decision_review_bundles(id INTEGER PRIMARY KEY, observation_id INTEGER,
                    captured_at TEXT,content_sha256 TEXT UNIQUE,payload TEXT);
                CREATE TABLE human_decisions(id INTEGER PRIMARY KEY,bundle_id INTEGER,payload TEXT,recorded_at TEXT);
                CREATE TABLE decision_events(id INTEGER PRIMARY KEY,decision_id INTEGER,kind TEXT,
                    action_id INTEGER,description TEXT);
                INSERT INTO farms VALUES(1); INSERT INTO fields VALUES(1,1);
                INSERT INTO observations VALUES(1,1); INSERT INTO observations VALUES(2,1);
                INSERT INTO tasks VALUES(1,1);
                INSERT INTO decision_review_bundles VALUES(1,1,'time','old-hash','{}');
                INSERT INTO decision_review_bundles VALUES(2,2,'time','other-hash','{}');
                INSERT INTO human_decisions VALUES(1,1,'{"next_step":"Inspect"}','time');
                INSERT INTO human_decisions VALUES(2,2,'{"next_step":"Other"}','time');
                INSERT INTO decision_events VALUES(3,1,'action',NULL,'40 checked; 19 small cobs');
                INSERT INTO decision_events VALUES(4,2,'action',NULL,'Unrelated');''')

    def test_only_decisions_for_selected_observation(self):
        bundle=capture_review(self.path,1)
        records=bundle['payload']['linked_human_decisions']
        self.assertEqual([r['decision']['id'] for r in records],[1])
        self.assertEqual([e['id'] for e in records[0]['events']],[3])
        self.assertEqual(bundle['payload']['task_actions'],[])
        counts=summarize(bundle)['linked_decision_counts']
        self.assertEqual(counts,{'human_decisions':1,'decision_actions':1,'decision_outcomes':0})

    def test_repeat_and_later_event_preserve_earlier_bundle(self):
        first=capture_review(self.path,1)
        self.assertEqual(first,capture_review(self.path,1))
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("INSERT INTO decision_events VALUES(5,1,'outcome',3,'Uncertain')")
        second=capture_review(self.path,1)
        self.assertNotEqual(first['id'],second['id'])
        self.assertEqual(summarize(second)['linked_decision_counts']['decision_outcomes'],1)
        with closing(sqlite3.connect(self.path)) as db:
            old=json.loads(db.execute('SELECT payload FROM decision_review_bundles WHERE id=?',(first['id'],)).fetchone()[0])
        self.assertEqual(old,first['payload'])

    def test_invalid_outcome_link_rejected(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute("INSERT INTO decision_events VALUES(5,1,'outcome',4,'Wrong decision action')")
        with self.assertRaises(ValueError):capture_review(self.path,1)

    def test_missing_events_table_not_zero(self):
        with closing(sqlite3.connect(self.path)) as db,db:
            db.execute('DROP TABLE decision_events')
        bundle=capture_review(self.path,1)
        self.assertIsNone(summarize(bundle)['linked_decision_counts']['decision_actions'])


if __name__=='__main__':unittest.main()
