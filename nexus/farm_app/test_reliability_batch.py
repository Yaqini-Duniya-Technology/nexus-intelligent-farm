import io,json,tempfile,threading,unittest,http.client,contextlib
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from http.server import HTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from nexus.farm_app import request_inputs as inputs,page_guides,operations,server,farm_resources as resources
from nexus.farm_app.operations_common import canonical,digest
from nexus.farm_app import test_farm_resources as fixtures

class Connection:
 def __init__(self):self.timeout=None
 def gettimeout(self):return self.timeout
 def settimeout(self,value):self.timeout=value

class InputTests(unittest.TestCase):
 def handler(self,raw=b'{}',**changes):
  h=Message();h['Content-Length']=str(len(raw));h['Content-Type']='application/json'
  return SimpleNamespace(headers=h,path='/api/resources/save',rfile=io.BytesIO(raw),connection=Connection(),**changes)
 def test_duplicate_fields_rejected_even_nested(self):
  for raw in (b'{"a":1,"a":2}',b'{"a":{"v":1,"v":2}}'):
   with self.assertRaises(inputs.RequestError):inputs.parse_object(raw)
 def test_nonfinite_and_overflow_rejected(self):
  for raw in (b'{"a":NaN}',b'{"a":Infinity}',b'{"a":1e999}'):
   with self.assertRaises(inputs.RequestError):inputs.parse_object(raw)
 def test_depth_is_bounded(self):
  with self.assertRaises(inputs.RequestError):inputs.parse_object((b'{"a":'*70)+b'0'+b'}'*70)
 def test_invalid_utf8_and_array(self):
  for raw in (b'\xff',b'[]'):
   with self.assertRaises(inputs.RequestError):inputs.parse_object(raw)
 def test_good_body_and_timeout_restored(self):
  h=self.handler(b'{"a":1}');self.assertEqual(inputs.read_request(h),b'{"a":1}');self.assertIsNone(h.connection.timeout)
 def test_duplicate_length_and_transfer_encoding(self):
  h=self.handler();h.headers['Content-Length']='2'
  with self.assertRaises(inputs.RequestError):inputs.read_request(h)
  h=self.handler();h.headers['Transfer-Encoding']='chunked'
  with self.assertRaises(inputs.RequestError):inputs.read_request(h)
 def test_zero_negative_and_overlarge_lengths(self):
  for length in ('0','-1','999999999','1,2','bad'):
   h=self.handler();h.headers.replace_header('Content-Length',length)
   with self.assertRaises(inputs.RequestError):inputs.read_request(h)
 def test_incomplete_body_rejected(self):
  h=self.handler();h.headers.replace_header('Content-Length','3')
  with self.assertRaises(inputs.RequestError):inputs.read_request(h)
 def test_wrong_media_and_charset(self):
  for media in ('text/plain','application/json; charset=latin-1'):
   h=self.handler();h.headers.replace_header('Content-Type',media)
   with self.assertRaises(inputs.RequestError) as e:inputs.read_request(h)
   self.assertEqual(e.exception.status,415)
 def test_unsupported_compression_rejected(self):
  h=self.handler();h.headers['Content-Encoding']='gzip'
  with self.assertRaises(inputs.RequestError):inputs.read_request(h)
 def test_audio_transport_preserved_without_model_loading(self):
  h=self.handler(b'RIFFTEST');h.path='/api/voice-drafts';h.headers.replace_header('Content-Type','audio/wav');self.assertEqual(inputs.read_request(h),b'RIFFTEST')
 def test_body_timeout_is_recoverable(self):
  h=self.handler();h.rfile=SimpleNamespace(read=lambda _:(_ for _ in ()).throw(TimeoutError()))
  with self.assertRaises(inputs.RequestError) as e:inputs.read_request(h)
  self.assertEqual(e.exception.status,408);self.assertIsNone(h.connection.timeout)

class LedgerPagingTests(unittest.TestCase):
 def setUp(self):fixtures.ResourcesTests.setUp(self)
 def save(self,name):return resources.save(self.store,dict(kind='risk',field_id=1,source='actual',reporter='TEST',reason='TEST',values=fixtures.FIXTURES['risk']|dict(name=name)))
 def test_paging_preserves_totals_and_exports(self):
  for i in range(105):self.save('TEST '+str(i))
  first=resources.state(self.store);second=resources.state(self.store,dict(offset='100'))
  self.assertEqual((len(first['entries']),len(second['entries']),first['page']['total']),(100,5,105));self.assertEqual(first['counts']['risk'],105);self.assertFalse({r['id'] for r in first['entries']} & {r['id'] for r in second['entries']})
  data=json.loads(resources.export(self.store,dict(format='json',offset='100'))[0]);self.assertEqual(len(data['entries']),105)
 def test_query_switches_and_limits_validated(self):
  for q in (dict(limit='1000'),dict(offset='-1'),dict(history='yes'),dict(include_tests='1'),dict(area='unknown')):
   with self.assertRaises(ValueError):resources.state(self.store,q)
 def test_bad_saved_domain_rejected_even_with_consistent_hash(self):
  rid=self.save('TEST invalid')
  with self.store.connect() as db:
   row=db.execute('SELECT payload FROM resource_entries WHERE id=?',(rid['id'],)).fetchone();p=json.loads(row[0]);p['values']['status']='invented';db.execute('UPDATE resource_entries SET payload=?,content_sha256=? WHERE id=?',(canonical(p),digest(p),rid['id']))
  with self.assertRaises(ValueError):resources.state(self.store)
 def test_old_payload_without_captures_still_reads_unchanged(self):
  rid=self.save('TEST older')
  with self.store.connect() as db:
   p=json.loads(db.execute('SELECT payload FROM resource_entries WHERE id=?',(rid['id'],)).fetchone()[0]);p.pop('captures',None);raw=canonical(p);db.execute('UPDATE resource_entries SET payload=?,content_sha256=? WHERE id=?',(raw,digest(p),rid['id']))
  resources.state(self.store)
  with self.store.connect() as db:self.assertEqual(db.execute('SELECT payload FROM resource_entries WHERE id=?',(rid['id'],)).fetchone()[0],raw)
 def test_help_index_compact_and_detail_complete(self):
  index=page_guides.centre({});detail=page_guides.centre(dict(topic='resource-sales_order'));self.assertLess(len(index),60000);self.assertNotIn(b'Show a fictional example',index);self.assertIn(b'Show a fictional example',detail);self.assertIn(b'<noscript>',index)

class BoundaryHTTPTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  from nexus.farm_app.store import FarmStore
  cls.temp=tempfile.TemporaryDirectory();cls.store=FarmStore(Path(cls.temp.name)/'test.db');server.initialize_audit(cls.store);server.initialize_scheduling(cls.store);cls.http=HTTPServer(('127.0.0.1',0),operations.make_handler(server.make_handler(cls.store),cls.store));cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start();cls.base='http://127.0.0.1:'+str(cls.http.server_port)
 @classmethod
 def tearDownClass(cls):cls.http.shutdown();cls.http.server_close();cls.thread.join();cls.temp.cleanup()
 def post(self,path,raw=b'{}',origin=True,media='application/json'):
  headers={'Content-Type':media}
  if origin:headers['Origin']=self.base
  req=Request(self.base+path,data=raw,headers=headers)
  try:
   with urlopen(req) as r:return r.status,r.read(),r.headers
  except HTTPError as e:return e.code,e.read(),e.headers
 def test_legacy_route_also_requires_origin(self):self.assertEqual(self.post('/api/farms',origin=False)[0],403)
 def test_duplicate_json_fails_before_mutation(self):
  code,_,_=self.post('/api/farms',b'{"name":"TEST","name":"OTHER","location":"TEST"}');self.assertEqual(code,400)
  with self.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM farms').fetchone()[0],0)
 def test_valid_core_write_still_roundtrips(self):self.assertEqual(self.post('/api/farms',b'{"name":"TEST","location":"TEST"}')[0],200)
 def test_trace_header_and_log_omit_query(self):
  log=io.StringIO()
  with contextlib.redirect_stderr(log):
   with urlopen(self.base+'/api/resources/state?q=PRIVATE_QUERY') as r:raw=r.read();trace=r.headers['X-Nexus-Request-ID']
  self.assertRegex(trace,r'^[a-f0-9]{32}$');self.assertNotIn('PRIVATE_QUERY',log.getvalue());self.assertIn(trace,log.getvalue())
 def test_text_plain_rejected(self):self.assertEqual(self.post('/api/farms',media='text/plain')[0],415)
 def test_wire_duplicate_length_rejected(self):
  connection=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=5)
  try:
   connection.putrequest('POST','/api/farms');connection.putheader('Origin',self.base);connection.putheader('Content-Type','application/json');connection.putheader('Content-Length','2');connection.putheader('Content-Length','2');connection.endheaders(b'{}');r=connection.getresponse();r.read();self.assertEqual(r.status,400)
  finally:connection.close()

if __name__=='__main__':unittest.main()
