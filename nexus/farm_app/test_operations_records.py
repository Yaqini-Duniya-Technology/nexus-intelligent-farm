import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from nexus.farm_app.store import FarmStore
from nexus.farm_app import operations_records as r,field_inspections as f,work_orders as w
from nexus.farm_app.operations_common import digest


class RecordsTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.path=Path(t.name)/'farm.db';self.store=FarmStore(self.path)
        self.store.create('farms',{'name':'TEST','location':'Lokoja'})
        for name in ('South','North'):self.store.create('fields',{'farm_id':1,'name':name,'crop':'maize'})
        self.now=datetime.now(timezone.utc);self.observed=(self.now-timedelta(days=1)).isoformat()
        for fid,note in ((1,'TEST small cobs 100%'),(2,'TEST yellow leaves')):self.store.create('observations',{'field_id':fid,'note':note,'observed_at':self.observed})
        f.initialize(self.store);w.initialize(self.store)
    def sample(self,**change):
        data={'observation_id':1,'observation_hash':f.state(self.store)['observations'][1]['selection_hash'],
              'base_id':None,'performed_at':self.now.isoformat(),'reporter':'TEST farmer','area':'South','sampling_method':'TEST method',
              'observation_definition':'TEST small cobs','findings':'TEST findings','reason':'Initial','plants_checked':40,'plants_affected':19,
              'cobs_checked':None,'newly_forming_cobs':None,'mature_small_cobs':None,'uncertain_cobs':None}
        data.update(change);return f.save(self.store,data)
    def reviews(self):
        with self.store.connect() as db:
            db.executescript('''CREATE TABLE human_decisions(id INTEGER PRIMARY KEY,bundle_id INTEGER,recorded_at TEXT,payload TEXT);
             CREATE TABLE human_decision_reviews(id INTEGER PRIMARY KEY,decision_id INTEGER,disposition TEXT,next_review_date TEXT);''')
            for i,date in enumerate(('2026-10-01','2026-10-31','2026-11-02'),1):db.execute('INSERT INTO human_decisions VALUES(?,?,?,?)',(i,1,'2026-10-01T12:00:00+00:00',json.dumps({'review_date':date,'next_step':'TEST plan Hausa ƙananan, commas; line\nsecond'})))
    def test_text_filter(self):
        rows=r.search(self.path,{'q':'yellow'})['records'];self.assertEqual(len(rows),1);self.assertEqual(rows[0]['field_id'],2)
    def test_literal_percent_not_wildcard(self):
        rows=r.search(self.path,{'q':'100%'})['records'];self.assertEqual(len(rows),1)
        self.assertEqual(r.search(self.path,{'q':'_'})['total'],0)
    def test_type_filter_excludes_other_records(self):
        data=r.search(self.path,{'kind':'observation'});self.assertEqual(data['total'],2);self.assertTrue(all(x['kind']=='observation' for x in data['records']))
    def test_field_and_observation_filters(self):
        data=r.search(self.path,{'field_id':'1','observation_id':'1'});self.assertEqual({x['field_id'] for x in data['records']},{1})
    def test_pagination_no_repeated_ids(self):
        a=r.search(self.path,{'kind':'observation','page_size':1,'page':1});b=r.search(self.path,{'kind':'observation','page_size':1,'page':2})
        self.assertEqual(a['total'],2);self.assertNotEqual(a['records'][0]['id'],b['records'][0]['id'])
    def test_sort_oldest_reverses_newest(self):
        a=r.search(self.path,{'kind':'observation','sort':'newest'})['records'];b=r.search(self.path,{'kind':'observation','sort':'oldest'})['records']
        self.assertEqual([x['id'] for x in a],list(reversed([x['id'] for x in b])))
    def test_lagos_date_boundary(self):
        with self.store.connect() as db:db.execute("UPDATE observations SET observed_at='2026-10-30T23:30:00+00:00' WHERE id=1")
        result=r.search(self.path,{'kind':'observation','observation_id':1,'from':'2026-10-31','to':'2026-10-31'})
        self.assertEqual(result['total'],1)
    def test_invalid_filters_and_sql_like_input(self):
        for p in ({'kind':'observations; DROP TABLE fields'},{'field_id':True},{'page':-1},{'page_size':101}, {'from':'bad'},{'from':'2026-11-02','to':'2026-11-01'},{'q':'x'*201}):
            with self.subTest(p=p),self.assertRaises(ValueError):r.search(self.path,p)
        self.assertEqual(r.search(self.path,{'q':"' OR 1=1 --"})['total'],0)
    def test_record_detail_parses_payload_without_images(self):
        self.sample();record=r.detail(self.path,'inspection',1);self.assertIsInstance(record['payload'],dict)
    def test_unknown_record_rejected(self):
        with self.assertRaises(ValueError):r.detail(self.path,'not-a-type',1)
        with self.assertRaises(ValueError):r.detail(self.path,'observation',999)
    def test_missing_optional_record_types_reported(self):
        self.assertIn('decision',r.search(self.path)['missing_record_types'])
    def test_inspection_ledger_excludes_corrections_by_default(self):
        self.sample();self.sample(base_id=1,supersedes_id=1,reason='Correction',plants_affected=18)
        self.assertEqual(len(r.inspection_ledger(self.path)['entries']),1)
        rows=r.inspection_ledger(self.path,{'active':'false'})['entries'];self.assertEqual(len(rows),2);self.assertTrue(next(x for x in rows if x['id']==1)['corrected'])
    def test_comparison_keeps_both_samples_without_totals(self):
        self.sample();self.sample(base_id=1,reason='A separate inspection',plants_affected=20)
        data=r.compare_inspections(self.path,[1,2]);self.assertEqual(len(data['inspections']),2);self.assertNotIn('total_affected',data)
    def test_bad_comparison_ids(self):
        for ids in ([],[1,2,3],[1,1],[999],['bad']):
            with self.subTest(ids=ids),self.assertRaises(ValueError):r.compare_inspections(self.path,ids)
    def test_queue_uses_latest_saved_review_and_closed_filter(self):
        self.reviews()
        with self.store.connect() as db:
            db.execute("INSERT INTO human_decision_reviews VALUES(1,1,'keep','2026-11-03')")
            db.execute("INSERT INTO human_decision_reviews VALUES(2,1,'close',NULL)")
        queue=r.review_queue(self.path,now=datetime(2026,10,31,12,tzinfo=timezone.utc))['items']
        self.assertEqual([x['decision_id'] for x in queue],[2,3])
        closed=r.review_queue(self.path,{'status':'closed'})['items'];self.assertEqual(closed[0]['latest_review_id'],2)
    def test_queue_timing_and_timezone(self):
        self.reviews();items=r.review_queue(self.path,now=datetime(2026,10,30,23,30,tzinfo=timezone.utc))['items']
        self.assertEqual([x['timing'] for x in items],['overdue','today','upcoming'])
    def test_calendar_utf8_folding_escaping_and_no_alarm(self):
        self.reviews();raw=r.calendar(self.path);lines=raw.decode().split('\r\n')
        self.assertIn('BEGIN:VCALENDAR',lines);self.assertIn('DTSTART;VALUE=DATE:20261031',lines)
        self.assertTrue(all(len(line.encode())<=75 for line in lines));self.assertIn('\\,',raw.decode());self.assertNotIn('VALARM',raw.decode())
    def test_search_does_not_mutate_database(self):
        before=self.path.read_bytes();r.search(self.path);r.detail(self.path,'observation',1);self.assertEqual(self.path.read_bytes(),before)


if __name__=='__main__':unittest.main()
