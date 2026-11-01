import tempfile
import unittest
import sqlite3
from pathlib import Path
from nexus.farm_app.store import FarmStore

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.path=Path(self.temp.name)/'farm.db';self.store=FarmStore(self.path)
    def tearDown(self): self.temp.cleanup()
    def setup_records(self):
        farm=self.store.create('farms',{'name':'Pilot','location':'Lokoja'})
        field=self.store.create('fields',{'farm_id':farm,'name':'North','crop':'Maize'})
        return self.store.create('observations',{'field_id':field,'note':'Yellow leaves'})
    def test_workflow_survives_restart(self):
        self.setup_records();task=self.store.snapshot()['tasks'][0]['id']
        self.store.transition(task,'approve');self.store.transition(task,'complete','Adviser inspected; monitoring agreed')
        snapshot=FarmStore(self.path).snapshot()
        self.assertEqual(snapshot['tasks'][0]['status'],'completed')
        self.assertEqual(snapshot['tasks'][0]['outcome'],'Adviser inspected; monitoring agreed')
        self.assertEqual(len(snapshot['observations']),1)
    def test_completion_requires_approval_and_outcome(self):
        self.setup_records();task=self.store.snapshot()['tasks'][0]['id']
        with self.assertRaises(ValueError): self.store.transition(task,'complete','Done')
        self.store.transition(task,'approve')
        with self.assertRaises(ValueError): self.store.transition(task,'complete',' ')
        with self.assertRaises(ValueError): self.store.transition(task,'approve')
    def test_invalid_parents_and_empty_records(self):
        with self.assertRaises(sqlite3.IntegrityError): self.store.create('fields',{'farm_id':99,'name':'x','crop':'Maize'})
        with self.assertRaises(ValueError): self.store.create('farms',{'name':' ','location':'Lokoja'})
        self.assertEqual(self.store.snapshot()['fields'],[])
if __name__=='__main__': unittest.main()
