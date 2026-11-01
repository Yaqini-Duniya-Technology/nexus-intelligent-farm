import csv
import io
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from nexus.farm_app.store import FarmStore
from nexus.farm_app import evidence_studio,field_measurements as measurements

class StudioFixture(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.directory=Path(temp.name);self.path=self.directory/'farm.sqlite3'
        self.store=FarmStore(self.path);self.store.create('farms',{'name':'TEST farm','location':'Lokoja'})
        for name in ('South','North'):self.store.create('fields',{'farm_id':1,'name':name,'crop':'maize'})
        for fid in (1,2):self.store.create('observations',{'field_id':fid,'note':'TEST field report'})
        evidence_studio.initialize(self.store)
        self.when=(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat()
    def reading(self,**changes):
        return dict({'field_id':1,'observation_id':1,'metric':'cob_length','unit':'cm','value':'12.5','observed_at':self.when,
                     'source':'farmer_measurement','area':'South sample 1','method':'TEST ruler measurement',
                     'instrument':'TEST ruler','reporter':'TEST farmer','notes':'TEST only','unknown_reason':'','reason':'Initial entry'},**changes)
    def case(self,**changes):
        return dict({'field_id':1,'observation_id':1,'title':'TEST unresolved growth stage','reporter':'TEST farmer','owner':'TEST owner',
                     'status':'open','next_review_date':'2026-11-03','tags':['maize'],
                     'questions':[{'question':'Which crop season?','status':'open','answer':''}],'reason':'Initial case'},**changes)
    def note(self,**changes):
        return dict({'field_id':1,'observation_id':1,'title':'TEST field note','reporter':'TEST farmer','content':'TEST only',
                     'tags':['maize'],'pinned':False,'reason':'Initial note'},**changes)
    def csv(self,rows=None):
        out=io.StringIO(newline='');writer=csv.DictWriter(out,fieldnames=measurements.COLUMNS);writer.writeheader()
        for data in rows or [self.reading()]:writer.writerow({key:data[key] for key in measurements.COLUMNS})
        return out.getvalue()
    def preview(self,**changes):
        return measurements.preview(self.store,dict({'field_id':1,'observation_id':1,'filename':'TEST.csv','source':'farmer_measurement','csv_text':self.csv()},**changes))
    def commit(self,preview,**changes):
        return measurements.commit(self.store,dict({'preview_id':preview['preview_id'],'preview_sha256':preview['preview_sha256'],
                                                  'confirm':True,'reviewer':'TEST reviewer'},**changes))
