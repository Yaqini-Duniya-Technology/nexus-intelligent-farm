import json
import tempfile
import threading
import unittest
from datetime import datetime,timedelta,timezone
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from nexus.farm_app.store import FarmStore
from nexus.farm_app import operations,server,work_orders


class OperationsHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.path=Path(cls.temp.name)/'farm.db';cls.store=FarmStore(cls.path)
        cls.store.create('farms',{'name':'TEST','location':'Lokoja'});cls.store.create('fields',{'farm_id':1,'name':'South','crop':'maize'})
        cls.store.create('observations',{'field_id':1,'note':'TEST observations'})
        cls.http=HTTPServer(('127.0.0.1',0),operations.make_handler(server.make_handler(cls.store),cls.store))
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start();cls.base='http://127.0.0.1:'+str(cls.http.server_port)
    @classmethod
    def tearDownClass(cls):cls.http.shutdown();cls.http.server_close();cls.thread.join();cls.temp.cleanup()
    def get(self,path):
        with urlopen(self.base+path) as response:return response.status,response.read(),response.headers
    def test_bootstrap_optional_creates_no_voice_or_farm_evidence(self):
        operations.bootstrap_optional(self.store)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM natlas_voice_responses').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM voice_drafts').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM observations').fetchone()[0],1)
    def test_valid_work_plan_and_event_roundtrip(self):
        data={'field_id':1,'observation_id':1,'title':'TEST HTTP order','reporter':'TEST farmer','owner':'TEST owner',
              'priority':'routine','due_date':(datetime.now(timezone.utc)+timedelta(days=1)).date().isoformat(),
              'resources':'Unknown','constraints':'Unknown','checklist':[]}
        def post(path,data):
            request=Request(self.base+path,data=json.dumps(data).encode(),headers={'Origin':self.base,'Content-Type':'application/json'})
            with urlopen(request) as response:return json.load(response)
        saved=post('/api/ops/work',data)
        order=next(o for o in json.loads(self.get('/api/ops/work')[1])['orders'] if o['id']==saved['id'])
        post('/api/ops/work-events',{'work_order_id':order['id'],'base_id':order['base_id'],'state_hash':order['state_hash'],
                                    'action':'start','reporter':'TEST farmer','note':'TEST work started'})
        current=next(o for o in json.loads(self.get('/api/ops/work')[1])['orders'] if o['id']==saved['id'])
        self.assertEqual(current['state']['status'],'in_progress')
    def test_full_launcher_runs_before_any_voice_import(self):
        import socket,subprocess,sys,time
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
        target=Path(self.temp.name)/'fresh-launch.db'
        with tempfile.TemporaryFile() as log:
            proc=subprocess.Popen([sys.executable,'-u','-m','nexus.farm_app.operations','--port',str(port),'--database',str(target)],stdout=log,stderr=log)
            try:
                for attempt in range(100):
                    if proc.poll() is not None:
                        log.seek(0);self.fail(log.read().decode())
                    try:
                        with urlopen('http://127.0.0.1:'+str(port)+'/api/ops/meta',timeout=.2) as response:
                            data=json.load(response)
                        self.assertEqual(data['counts']['observations'],0)
                        break
                    except OSError:time.sleep(.05)
                else:self.fail('Combined launcher did not become ready')
            finally:
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()

    def test_workbench_html_and_static_assets(self):
        self.assertIn(b'Work orders',self.get('/workbench')[1]);self.assertIn(b'function init()',self.get('/ops-assets/operations_workbench.js')[1])
        self.assertIn(b'@media',self.get('/ops-assets/operations_workbench.css')[1])
    def test_help_redirects_to_offline_help_view(self):self.assertEqual(self.get('/help')[0],200)
    def test_metadata(self):self.assertEqual(json.loads(self.get('/api/ops/meta')[1])['fields'][0]['id'],1)
    def test_search_and_record_routes(self):
        self.assertEqual(json.loads(self.get('/api/ops/search?kind=observation')[1])['total'],1)
        self.assertEqual(json.loads(self.get('/api/ops/record?kind=observation&id=1')[1])['note'],'TEST observations')
    def test_timeline_requires_field_or_observation(self):
        with self.assertRaises(HTTPError) as error:self.get('/api/ops/timeline')
        self.assertEqual(error.exception.code,400);self.assertEqual(self.get('/api/ops/timeline?field_id=1')[0],200)
    def test_unknown_operations_route_returns_404(self):
        with self.assertRaises(HTTPError) as error:self.get('/api/ops/no-such-route')
        self.assertEqual(error.exception.code,404)
    def test_invalid_host_is_blocked(self):
        request=Request(self.base+'/api/ops/meta',headers={'Host':'attacker.invalid'})
        with self.assertRaises(HTTPError) as error:urlopen(request)
        self.assertEqual(error.exception.code,403)
    def test_cross_origin_write_is_blocked(self):
        request=Request(self.base+'/api/ops/work',data=b'{}',headers={'Origin':'http://attacker.invalid','Content-Type':'application/json'})
        with self.assertRaises(HTTPError) as error:urlopen(request)
        self.assertEqual(error.exception.code,403)
    def test_malformed_json_is_400(self):
        request=Request(self.base+'/api/ops/work',data=b'{bad}',headers={'Origin':self.base,'Content-Type':'application/json'})
        with self.assertRaises(HTTPError) as error:urlopen(request)
        self.assertEqual(error.exception.code,400)
    def test_json_list_is_rejected(self):
        request=Request(self.base+'/api/ops/work',data=b'[]',headers={'Origin':self.base,'Content-Type':'application/json'})
        with self.assertRaises(HTTPError) as error:urlopen(request)
        self.assertEqual(error.exception.code,400)
    def test_export_is_download_with_safe_headers(self):
        _,body,headers=self.get('/api/ops/export?kind=observation&format=csv');self.assertIn(b'TEST observations',body)
        self.assertIn('attachment;',headers['Content-Disposition']);self.assertEqual(headers['X-Content-Type-Options'],'nosniff')
    def test_calendar_download(self):self.assertIn(b'BEGIN:VCALENDAR',self.get('/api/ops/calendar')[1])
    def test_legacy_workspace_still_served(self):self.assertIn(b'NEXUS',self.get('/')[1])
    def test_health_json(self):self.assertTrue(json.loads(self.get('/api/ops/health')[1])['ok'])


if __name__=='__main__':unittest.main()
