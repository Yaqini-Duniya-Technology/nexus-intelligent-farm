import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from nexus.farm_app.observations import normalize, review
from nexus.farm_app.store import FarmStore
from contextlib import closing

NOW = datetime(2026,10,3,12,tzinfo=timezone.utc)
class ObservationTests(unittest.TestCase):
    def test_missing_moisture_is_not_zero(self):
        missing=normalize({'category':'water'},NOW)
        self.assertIsNone(missing['soil_moisture_pct'])
        self.assertTrue(review(missing,NOW)['missing_information'])
        zero=normalize({'category':'water','soil_moisture_pct':0,'moisture_method':'volumetric_sensor'},NOW)
        self.assertEqual(zero['soil_moisture_pct'],0)
        self.assertEqual(review(zero,NOW)['missing_information'],[])
    def test_timezones_freshness_and_reported_priority(self):
        o=normalize({'observed_at':(NOW-timedelta(days=2)).isoformat(),'condition':'worsening'},NOW)
        r=review(o,NOW)
        self.assertEqual(r['priority'],'prompt')
        self.assertIn('updated field observation',r['missing_information'])
        with self.assertRaises(ValueError):normalize({'observed_at':'2026-10-03T12:00'},NOW)
        with self.assertRaises(ValueError):normalize({'observed_at':(NOW+timedelta(days=1)).isoformat()},NOW)
    def test_invalid_measurements_and_enums(self):
        for value in [True,-1,101,float('nan'),float('inf'),'bad']:
            with self.assertRaises(ValueError):normalize({'soil_moisture_pct':value,'moisture_method':'volumetric_sensor'},NOW)
        with self.assertRaises(ValueError):normalize({'soil_moisture_pct':20},NOW)
        with self.assertRaises(ValueError):normalize({'category':'unknown_category'},NOW)
    def test_legacy_database_migrates_without_losing_records(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'legacy.db'
            with closing(sqlite3.connect(path)) as db, db:
                db.executescript("CREATE TABLE farms(id INTEGER PRIMARY KEY,name TEXT NOT NULL,location TEXT NOT NULL); CREATE TABLE fields(id INTEGER PRIMARY KEY,farm_id INTEGER NOT NULL REFERENCES farms(id),name TEXT NOT NULL,crop TEXT NOT NULL); CREATE TABLE observations(id INTEGER PRIMARY KEY,field_id INTEGER NOT NULL REFERENCES fields(id),note TEXT NOT NULL,created TEXT NOT NULL); CREATE TABLE tasks(id INTEGER PRIMARY KEY,observation_id INTEGER NOT NULL UNIQUE REFERENCES observations(id),recommendation TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',outcome TEXT,completed TEXT); INSERT INTO farms VALUES(1,'Pilot','Lokoja'); INSERT INTO fields VALUES(1,1,'North','Maize'); INSERT INTO observations VALUES(1,1,'Original note','2026-10-01'); INSERT INTO tasks VALUES(1,1,'Original prompt','completed','Original outcome','2026-10-02');")
            store=FarmStore(path);state=store.snapshot()
            self.assertEqual(state['tasks'][0]['outcome'],'Original outcome')
            self.assertEqual(state['observations'][0]['note'],'Original note')
            store.create('observations',{'field_id':1,'note':'New note','category':'water','condition':'worsening'})
            state=FarmStore(path).snapshot()
            self.assertEqual(len(state['observations']),2)
            self.assertEqual(state['tasks'][0]['priority'],'prompt')
            self.assertIn('measured soil moisture',state['tasks'][0]['missing_information'])
if __name__=='__main__':unittest.main()
