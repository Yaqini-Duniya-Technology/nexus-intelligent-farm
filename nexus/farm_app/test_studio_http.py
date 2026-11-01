import json
import threading
from http.server import HTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from nexus.farm_app.studio_test_support import StudioFixture
from nexus.farm_app import operations,server,field_measurements

class StudioHTTPTests(StudioFixture):
    def setUp(self):
        super().setUp();self.http=HTTPServer(('127.0.0.1',0),operations.make_handler(server.make_handler(self.store),self.store))
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start();self.base='http://127.0.0.1:'+str(self.http.server_port)
        self.addCleanup(lambda:(self.http.shutdown(),self.http.server_close(),self.thread.join()))
    def get(self,path):
        with urlopen(self.base+path) as r:return r.read(),r.headers
    def post(self,path,data,origin=None):
        req=Request(self.base+path,data=json.dumps(data).encode(),headers={'Origin':origin or self.base,'Content-Type':'application/json'})
        with urlopen(req) as r:return json.load(r)
    def test_studio_page_and_script(self):
        self.assertIn(b'Field measurements',self.get('/evidence-studio')[0]);self.assertIn(b'function init()',self.get('/ops-assets/evidence_studio.js')[0])
    def test_metric_registry_metadata(self):
        data=json.loads(self.get('/api/studio/meta')[0]);self.assertEqual(data['metrics']['cob_length']['unit'],'cm')
    def test_measurement_roundtrip(self):
        saved=self.post('/api/studio/measurements',self.reading());data=json.loads(self.get('/api/studio/measurements?field_id=1')[0])
        self.assertEqual(data['entries'][0]['id'],saved['id'])
    def test_case_and_notebook_roundtrip(self):
        self.post('/api/studio/cases',self.case());self.post('/api/studio/notes',self.note())
        self.assertEqual(len(json.loads(self.get('/api/studio/cases')[0])['entries']),1)
        self.assertEqual(len(json.loads(self.get('/api/studio/notes')[0])['entries']),1)
    def test_source_preview_and_link_roundtrip(self):
        self.post('/api/studio/measurements',self.reading());source=json.loads(self.get('/api/studio/source?kind=measurement&id=1')[0])
        self.post('/api/studio/links',{'field_id':1,'observation_id':1,'kind':'measurement','target_id':1,'target_sha256':source['target_sha256'],
                                     'state':'active','reporter':'TEST','reason':'Explicit context'})
        self.assertEqual(json.loads(self.get('/api/studio/links')[0])['entries'][0]['reference_status'],'matches')
    def test_csv_preview_then_commit_http(self):
        preview=self.post('/api/studio/import-preview',{'field_id':1,'observation_id':1,'source':'farmer_measurement','filename':'TEST.csv','csv_text':self.csv()})
        self.assertEqual(field_measurements.readings(self.path),[])
        result=self.post('/api/studio/import-commit',{'preview_id':preview['preview_id'],'preview_sha256':preview['preview_sha256'],'confirm':True,'reviewer':'TEST'})
        self.assertEqual(result['inserted'],1)
    def test_csv_template_download(self):
        raw,headers=self.get('/api/studio/template');self.assertIn(b'metric,unit,value',raw);self.assertIn('attachment',headers['Content-Disposition'])
    def test_unknown_values_return_400(self):
        with self.assertRaises(HTTPError) as error:self.post('/api/studio/measurements',self.reading(value='NaN'))
        self.assertEqual(error.exception.code,400)
    def test_cross_origin_write_rejected(self):
        with self.assertRaises(HTTPError) as error:self.post('/api/studio/notes',self.note(),origin='http://attacker.invalid')
        self.assertEqual(error.exception.code,403)
    def test_backup_create_requires_confirmation(self):
        with self.assertRaises(HTTPError) as error:self.post('/api/studio/backup-create',{'confirm':False})
        self.assertEqual(error.exception.code,400)
    def test_quality_endpoint_and_export(self):
        self.post('/api/studio/measurements',self.reading());data=json.loads(self.get('/api/studio/quality')[0]);self.assertEqual(data['farm_measurement_count'],1)
        raw,headers=self.get('/api/studio/export?dataset=measurements&format=csv');self.assertIn(b'farmer_measurement',raw);self.assertIn('attachment',headers['Content-Disposition'])
    def test_saved_view_roundtrip(self):
        self.post('/api/studio/views',{'title':'TEST','reporter':'TEST','reason':'Save filter','tags':[],'path':'/evidence-studio','filters':{'view':'measurements','field_id':'1'}})
        self.assertEqual(json.loads(self.get('/api/studio/views')[0])['entries'][0]['url'],'/evidence-studio?field_id=1&view=measurements')
