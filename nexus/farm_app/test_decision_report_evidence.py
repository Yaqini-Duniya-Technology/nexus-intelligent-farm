import ast
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date,datetime,timedelta,timezone
from html import escape
from pathlib import Path
from types import SimpleNamespace
try:
    from nexus.farm_app.decision_report import read_report,render_reviews
except ModuleNotFoundError:
    tree=ast.parse(Path(__file__).with_name('decision_report.py').read_text())
    functions=[n for n in tree.body if isinstance(n,ast.FunctionDef)]
    ns=dict(hashlib=hashlib,json=json,sqlite3=sqlite3,closing=closing,date=date,datetime=datetime,
            timedelta=timedelta,timezone=timezone,text=lambda v:escape('Not recorded' if v is None else str(v)),
            local_time=lambda v:v or 'Not recorded')
    exec(compile(ast.Module(body=functions,type_ignores=[]),'report-functions','exec'),ns)
    read_report=ns['read_report'];render_reviews=ns['render_reviews']


class ReportEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.store=SimpleNamespace(path=str(Path(temp.name)/'test.sqlite3'))
        raw=json.dumps({'observation':{'id':5}},sort_keys=True,ensure_ascii=False,allow_nan=False)
        self.digest=hashlib.sha256(raw.encode()).hexdigest()
        with closing(sqlite3.connect(self.store.path)) as db,db:
            db.executescript('''CREATE TABLE human_decisions(id INTEGER PRIMARY KEY,bundle_id INTEGER,recorded_at TEXT,payload TEXT);
                CREATE TABLE decision_review_bundles(id INTEGER PRIMARY KEY,captured_at TEXT,content_sha256 TEXT,payload TEXT);
                CREATE TABLE decision_events(id INTEGER PRIMARY KEY,decision_id INTEGER,occurred_at TEXT);
                CREATE TABLE human_decision_reviews(id INTEGER PRIMARY KEY,decision_id INTEGER,reviewer TEXT,
                reviewed_at TEXT,recorded_at TEXT,conclusion TEXT,disposition TEXT,next_review_date TEXT,
                evidence_bundle_id INTEGER,evidence_bundle_sha256 TEXT);
                INSERT INTO human_decisions VALUES(2,5,'2026-10-13T17:30:00+00:00','{"review_date":"2026-10-16"}');''')
            for id in (5,7):
                db.execute('INSERT INTO decision_review_bundles VALUES(?,?,?,?)',(id,'2026-10-13T18:40:00+00:00',self.digest,raw))
            db.execute('INSERT INTO human_decision_reviews VALUES(2,2,?,?,?,?,?,?,7,?)',
                       ('Test reviewer','2026-10-13T19:00:00+00:00','2026-10-13T19:00:00+00:00','Test findings','keep','2026-10-16',self.digest))

    def test_original_bundle_preserved_and_review_reference_rendered(self):
        report=read_report(self.store,2)
        self.assertEqual(report['bundle']['id'],5)
        html=render_reviews(report)
        self.assertIn('Read reviewed evidence bundle #7',html)
        self.assertIn('content hashes match',html)

    def test_mismatch_shown(self):
        with closing(sqlite3.connect(self.store.path)) as db,db:
            db.execute("UPDATE decision_review_bundles SET payload='{}' WHERE id=7")
        self.assertIn('Hash mismatch',render_reviews(read_report(self.store,2)))

    def test_missing_reference_target_shown(self):
        with closing(sqlite3.connect(self.store.path)) as db,db:
            db.execute('DELETE FROM decision_review_bundles WHERE id=7')
        self.assertIn('Referenced bundle is unavailable',render_reviews(read_report(self.store,2)))

    def test_older_review_without_reference(self):
        with closing(sqlite3.connect(self.store.path)) as db,db:
            db.execute('UPDATE human_decision_reviews SET evidence_bundle_id=NULL,evidence_bundle_sha256=NULL')
        self.assertIn('No additional evidence bundle reference',render_reviews(read_report(self.store,2)))

    def test_hash_text_escaped(self):
        with closing(sqlite3.connect(self.store.path)) as db,db:
            db.execute('UPDATE human_decision_reviews SET evidence_bundle_sha256=?',('<script>bad</script>',))
        html=render_reviews(read_report(self.store,2))
        self.assertNotIn('<script>bad</script>',html)
        self.assertIn('&lt;script&gt;',html)


if __name__=='__main__':unittest.main()
