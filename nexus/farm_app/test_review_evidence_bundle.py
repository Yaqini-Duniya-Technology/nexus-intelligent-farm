import ast
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4
try:
    from nexus.farm_app.decision_review_completion import initialize_reviews, save_review
except ModuleNotFoundError:
    # Isolated execution of the exact production functions when the full app is absent.
    source=Path(__file__).with_name('decision_review_completion.py').read_text()
    tree=ast.parse(source)
    functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('initialize_reviews','save_review')]
    namespace=dict(hashlib=hashlib,json=json,sqlite3=sqlite3,closing=closing,date=date,
                   datetime=datetime,timezone=timezone,UUID=UUID,LAGOS=timezone(timedelta(hours=1)),
                   parse_time=lambda value:datetime.fromisoformat(value).astimezone(timezone.utc))
    exec(compile(ast.Module(body=functions,type_ignores=[]),'production-functions','exec'),namespace)
    initialize_reviews=namespace['initialize_reviews'];save_review=namespace['save_review']


class ReviewEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.store=SimpleNamespace(path=str(Path(temp.name)/'test.sqlite3'))
        self.now=datetime.now(timezone.utc)
        payload=json.dumps({'observation':{'id':5}},sort_keys=True,ensure_ascii=False,allow_nan=False)
        self.digest=hashlib.sha256(payload.encode()).hexdigest()
        with closing(sqlite3.connect(self.store.path)) as db,db:
            db.executescript('''CREATE TABLE decision_review_bundles(id INTEGER PRIMARY KEY,
                observation_id INTEGER,captured_at TEXT,content_sha256 TEXT,payload TEXT);
                CREATE TABLE human_decisions(id INTEGER PRIMARY KEY,bundle_id INTEGER,recorded_at TEXT);''')
            for id,obs in [(5,5),(7,5),(8,8)]:
                db.execute('INSERT INTO decision_review_bundles VALUES(?,?,?,?,?)',
                           (id,obs,(self.now-timedelta(hours=1)).isoformat(),self.digest,payload))
            db.execute('INSERT INTO human_decisions VALUES(2,5,?)',((self.now-timedelta(hours=2)).isoformat(),))
        initialize_reviews(self.store)
        self.data=dict(decision_id=2,expected_review_id=None,request_id=str(uuid4()),
                       reviewer='Test reviewer',conclusion='Test findings',disposition='keep',
                       reviewed_at=self.now.isoformat(),next_review_date=(self.now+timedelta(days=1)).date().isoformat(),
                       evidence_bundle_id=7)

    def test_save_reference_and_retry_preserves_original_bundle(self):
        first=save_review(self.store,self.data)
        self.assertEqual(first,save_review(self.store,self.data))
        self.assertEqual(first['evidence_bundle_id'],7)
        self.assertEqual(first['evidence_bundle_sha256'],self.digest)
        with closing(sqlite3.connect(self.store.path)) as db:
            self.assertEqual(db.execute('SELECT bundle_id FROM human_decisions WHERE id=2').fetchone()[0],5)

    def test_wrong_observation_rejected(self):
        with self.assertRaises(ValueError):save_review(self.store,{**self.data,'evidence_bundle_id':8})

    def test_later_capture_rejected(self):
        with closing(sqlite3.connect(self.store.path)) as db,db:
            db.execute('UPDATE decision_review_bundles SET captured_at=? WHERE id=7',((self.now+timedelta(hours=1)).isoformat(),))
        with self.assertRaises(ValueError):save_review(self.store,self.data)

    def test_bad_hash_rejected(self):
        with closing(sqlite3.connect(self.store.path)) as db,db:
            db.execute("UPDATE decision_review_bundles SET content_sha256='bad' WHERE id=7")
        with self.assertRaises(ValueError):save_review(self.store,self.data)

    def test_optional_reference_and_repeat_initialization(self):
        initialize_reviews(self.store)
        row=save_review(self.store,{**self.data,'evidence_bundle_id':None})
        self.assertIsNone(row['evidence_bundle_id'])
        self.assertIsNone(row['evidence_bundle_sha256'])


if __name__=='__main__':unittest.main()
