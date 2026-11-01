import hashlib,json,tempfile,threading,unittest
from pathlib import Path
from http.server import HTTPServer
from urllib.request import urlopen
from urllib.error import HTTPError
from nexus.farm_app import page_guides as help,operations,server
from nexus.farm_app.store import FarmStore

class GuideTests(unittest.TestCase):
    def test_catalog_complete_and_all_routes_resolve(self):
        topics=help.catalog()['topics'];self.assertEqual(len(topics),89)
        self.assertEqual(len({t['id'] for t in topics}),89)
        for topic in topics:
            self.assertTrue(topic['steps']);self.assertTrue(topic['save_effect']);self.assertIn('fictional',topic['example_notice'].lower())
            for route in topic['routes']:self.assertIn(topic,help.context(route['path'],route.get('view','')))
            self.assertTrue(help.standalone(topic['id']).startswith(b'<!doctype'))
    def test_context_defaults_and_isolation(self):
        self.assertEqual(help.context('/evidence-studio')[0]['id'],'measurements')
        self.assertEqual(help.context('/evidence-studio','imports')[0]['id'],'csv-import')
        self.assertEqual(help.context('/missing'),[])
        for bad in ('https://evil.test/','//evil.test/','relative'):
            with self.assertRaises(ValueError):help.context(bad)
    def test_search_and_invalid_inputs(self):
        self.assertTrue(help.search('cob'))
        self.assertEqual(help.search('xyzzzz-not-a-term'),[])
        with self.assertRaises(ValueError):help.search('a'*201)
        with self.assertRaises(ValueError):help.topic_by_id('missing')
    def test_injection_preserves_forms_and_is_idempotent(self):
        form='<form id="actual"><input value="unsaved"><button>Save</button></form>'
        raw=('<html><body>'+form+'</body></html>').encode();result=help.inject(raw,'/?q=private&bundle_id=42')
        self.assertIn(form.encode(),result);self.assertEqual(help.inject(result,'/'),result)
        self.assertNotIn(b'private',result);self.assertNotIn(b'bundle_id',result)
        self.assertEqual(help.inject(raw,'/api/export'),raw)
        self.assertEqual(help.inject(b'\xff','/'),b'\xff')
    def test_centre_escapes_search_and_works_without_script(self):
        result=help.centre({'q':'<script>alert(1)</script>'})
        self.assertIn(b'&lt;script&gt;',result);self.assertNotIn(b'<script>alert',result)
        self.assertIn(b'<noscript>',result);self.assertIn(b'method="get"',result)
    def test_offline_has_no_remote_assets_or_farm_records(self):
        result=help.standalone('measurements')
        self.assertNotIn(b'<script',result);self.assertNotIn(b'<link',result)
        self.assertIn(b'fictional',result);self.assertIn(b'<style>',result)
    def test_error_references_are_valid(self):
        for error in help.catalog()['errors']:self.assertTrue(help.topic_by_id(error['topic']))

class GuideHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.store=FarmStore(Path(cls.temp.name)/'test.db')
        cls.http=HTTPServer(('127.0.0.1',0),operations.make_handler(server.make_handler(cls.store),cls.store))
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start()
        cls.base='http://127.0.0.1:'+str(cls.http.server_port)
    @classmethod
    def tearDownClass(cls):cls.http.shutdown();cls.http.server_close();cls.thread.join();cls.temp.cleanup()
    def get(self,path):
        with urlopen(self.base+path) as r:
            raw=r.read();self.assertEqual(int(r.headers['Content-Length']),len(raw));return raw,r.headers
    def test_catalog_and_topic_api(self):
        raw,_=self.get('/api/help/catalog');self.assertEqual(len(json.loads(raw)['topics']),89)
        raw,_=self.get('/api/help/topic?id=measurements');self.assertEqual(json.loads(raw)['id'],'measurements')
    def test_context_and_search_api(self):
        raw,_=self.get('/api/help/context?path=/evidence-studio&view=imports');self.assertEqual(json.loads(raw)['topics'][0]['id'],'csv-import')
        raw,_=self.get('/api/help/search?q=cob');self.assertTrue(json.loads(raw)['topics'])
    def test_pages_injected_and_help_no_duplicate(self):
        raw,_=self.get('/evidence-studio');self.assertIn(b'data-nxh-boot="1"',raw)
        raw,_=self.get('/help-centre?topic=measurements');self.assertIn(b'data-nxh-centre="1"',raw);self.assertNotIn(b'data-nxh-boot',raw)
    def test_download_is_readonly_and_self_contained(self):
        before=hashlib.sha256(Path(self.store.path).read_bytes()).digest()
        raw,h=self.get('/api/help/download?topic=measurements');self.assertIn('attachment',h['Content-Disposition']);self.assertNotIn(b'data-nxh-boot',raw)
        self.assertEqual(before,hashlib.sha256(Path(self.store.path).read_bytes()).digest())
    def test_assets_and_unknown_topic(self):
        for asset,mime in [('js','javascript'),('css','css')]:
            raw,h=self.get('/ops-assets/page_guides.'+asset);self.assertIn(mime,h['Content-Type']);self.assertTrue(raw)
        with self.assertRaises(HTTPError) as e:self.get('/api/help/topic?id=unknown')
        self.assertEqual(e.exception.code,400)

if __name__=='__main__':unittest.main()
