import json,tempfile,unittest,threading
from pathlib import Path
from datetime import datetime,timedelta,timezone
from http.server import HTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from nexus.farm_app import farm_resources as R,operations,server,project_branding,page_guides
from nexus.farm_app.store import FarmStore

FIXTURES={
 'supply':dict(name='TEST sacks',unit='piece',minimum='2',storage='TEST store',notes='TEST only'),
 'movement':dict(supply_id=1,direction='receipt',quantity='10',occurred_at='2020-01-01T12:00:00+00:00',reference='TEST receipt',notes='TEST counted'),
 'reservation':dict(supply_id=1,quantity='3',purpose='TEST packing',status='active',due_date='2030-01-02',notes='TEST plan'),
 'equipment':dict(name='TEST scale',identifier='TEST 1',condition='unknown',owner='TEST owner',notes='TEST only'),
 'maintenance':dict(equipment_id=1,name='TEST check',due_date='2030-01-02',status='planned',performed_at=None,findings='TEST scope'),
 'labor':dict(name='TEST work',worker='TEST worker',occurred_at='2020-01-01T12:00:00+00:00',hours='2.5',hourly_ngn='1000',notes='TEST actual report'),
 'budget':dict(name='TEST budget',ceiling_ngn='10000',start_date='2030-01-01',end_date='2030-02-01',status='active',notes='TEST estimate'),
 'budget_line':dict(budget_id=1,name='TEST line',amount_ngn='3000',status='estimate',notes='TEST quote'),
 'contact':dict(name='TEST contact',role='adviser',contact='Unknown',permission='not_recorded',notes='TEST only'),
 'visit':dict(contact_id=1,name='TEST visit',due_date='2030-01-02',status='planned',performed_at=None,findings='TEST questions'),
 'risk':dict(name='TEST access',priority='routine',status='open',owner='TEST owner',due_date='2030-01-02',response='TEST inspect access'),
 'milestone':dict(name='TEST stock count',owner='TEST owner',due_date='2030-01-02',status='planned',evidence='TEST plan')}
class ResourcesTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.store=FarmStore(Path(self.temp.name)/'test.db')
  self.store.create('farms',dict(name='TEST',location='TEST'));self.store.create('fields',dict(farm_id=1,name='TEST',crop='maize'));self.store.create('fields',dict(farm_id=1,name='OTHER',crop='maize'));R.initialize(self.store)
 def data(self,kind,values=None,**changes):return dict(kind=kind,field_id=1,source='actual',reporter='TEST user',reason='TEST entry',values=FIXTURES[kind]|(values or {}))|changes
 def save(self,kind,values=None,**changes):return R.save(self.store,self.data(kind,values,**changes))
 def revise(self,kind,saved,values=None,**changes):return self.save(kind,values,record_id=saved['record_id'],base_id=saved['id'],reason='TEST correction',**changes)
 def state(self,**q):return R.state(self.store,q)
 def test_all_workflows_persist_and_reopen(self):
  ids={}
  for kind in FIXTURES:
   refs={}
   for f in R.SPECS[kind]['fields']:
    if f['type']=='reference':refs[f['key']]=ids[f['ref']]
   result=self.save(kind,refs);ids[kind]=result['record_id']
  reopened=FarmStore(self.store.path);self.assertEqual(len(R.state(reopened)['entries']),12)
 def test_receipts_issues_and_signed_adjustments(self):
  s=self.save('supply')['record_id'];self.save('movement',dict(supply_id=s));self.save('movement',dict(supply_id=s,direction='issue',quantity='4'));self.save('movement',dict(supply_id=s,direction='adjustment',quantity='-1'))
  self.assertEqual(self.state()['totals']['supplies'][0]['balance'],'5')
 def test_negative_stock_rolls_back(self):
  self.save('supply');self.save('movement');before=len(self.state()['entries'])
  with self.assertRaises(ValueError):self.save('movement',dict(direction='issue',quantity='11'))
  self.assertEqual(len(self.state()['entries']),before)
 def test_reservations_and_release_do_not_issue_stock(self):
  self.save('supply');self.save('movement');res=self.save('reservation');s=self.state()['totals']['supplies'][0];self.assertEqual((s['balance'],s['available']),('10','7'))
  self.revise('reservation',res,dict(status='fulfilled'));s=self.state()['totals']['supplies'][0];self.assertEqual((s['balance'],s['available']),('10','10'))
 def test_overreservation_rejected(self):
  self.save('supply');self.save('movement')
  with self.assertRaises(ValueError):self.save('reservation',dict(quantity='11'))
 def test_stock_correction_revalidates_reservations(self):
  self.save('supply');move=self.save('movement');self.save('reservation')
  with self.assertRaises(ValueError):self.revise('movement',move,dict(quantity='2'))
  self.assertEqual(self.state()['totals']['supplies'][0]['balance'],'10')
 def test_unit_frozen_after_movement(self):
  item=self.save('supply');self.save('movement')
  with self.assertRaises(ValueError):self.revise('supply',item,dict(unit='bag'))
 def test_no_cross_field_or_test_references(self):
  self.save('supply')
  for change in ({'field_id':2},{'source':'test'}):
   with self.assertRaises(ValueError):self.save('movement',**change)
 def test_references_use_root_after_revision(self):
  item=self.save('supply');self.revise('supply',item,dict(name='TEST renamed'));self.save('movement');self.assertEqual(self.state()['totals']['supplies'][0]['name'],'TEST renamed')
 def test_references_enforce_type(self):
  self.save('equipment')
  with self.assertRaises(ValueError):self.save('movement')
 def test_idempotent_create_and_revision_retry(self):
  item=self.save('supply');self.assertTrue(self.save('supply')['reused']);rev=self.revise('supply',item,dict(name='TEST renamed'));again=self.revise('supply',item,dict(name='TEST renamed'));self.assertTrue(again['reused']);self.assertEqual(rev['id'],again['id'])
 def test_stale_correction_rejected(self):
  item=self.save('supply');self.revise('supply',item,dict(name='TEST renamed'))
  with self.assertRaises(ValueError):self.revise('supply',item,dict(name='OTHER edit'))
  self.assertEqual(len(self.state(history='true')['entries']),2)
 def test_history_preserves_original_bytes(self):
  item=self.save('supply')
  with self.store.connect() as db:before=db.execute('SELECT payload FROM resource_entries WHERE id=?',(item['id'],)).fetchone()[0]
  self.revise('supply',item,dict(storage='TEST new store'))
  with self.store.connect() as db:self.assertEqual(before,db.execute('SELECT payload FROM resource_entries WHERE id=?',(item['id'],)).fetchone()[0])
 def test_source_and_field_frozen(self):
  item=self.save('supply')
  for change in ({'source':'test'},{'field_id':2}):
   with self.assertRaises(ValueError):self.revise('supply',item,**change)
 def test_tests_excluded_by_default(self):
  self.save('supply',source='test');self.assertEqual(self.state()['entries'],[]);self.assertEqual(len(self.state(include_tests='true')['entries']),1);self.assertEqual(self.state()['totals']['supplies'],[])
 def test_unknown_rate_and_zero_differ(self):
  self.save('labor',dict(hourly_ngn=None));self.save('labor',dict(name='TEST unpaid',hourly_ngn='0'));summary=self.state()['totals']['labor_summary'];self.assertEqual(summary['unknown_rate_count'],1);self.assertEqual(summary['known_cost_ngn'],'0.00');self.assertEqual(summary['hours'],'5.0')
 def test_decimal_cost_exact(self):
  self.save('labor',dict(hours='0.1',hourly_ngn='0.30'));self.assertEqual(self.state()['totals']['labor_summary']['known_cost_ngn'],'0.03')
 def test_budget_status_moves_line_without_double_count(self):
  self.save('budget');line=self.save('budget_line');self.revise('budget_line',line,dict(status='committed'));b=self.state()['totals']['budgets'][0];self.assertEqual((b['estimates_ngn'],b['committed_ngn'],b['unallocated_ngn']),('0','3000','7000'))
 def test_budget_overspend_is_visible_plan_not_cash(self):
  self.save('budget');self.save('budget_line',dict(amount_ngn='12000'));self.assertEqual(self.state()['totals']['budgets'][0]['unallocated_ngn'],'-2000')
 def test_contact_permission(self):
  with self.assertRaises(ValueError):self.save('contact',dict(contact='test@example.invalid'))
  self.save('contact',dict(contact='test@example.invalid',permission='granted'))
 def test_completion_requires_actual_time(self):
  self.save('equipment')
  with self.assertRaises(ValueError):self.save('maintenance',dict(status='completed'))
  self.save('maintenance',dict(status='completed',performed_at='2020-01-01T12:00:00+00:00'))
  self.assertEqual(self.state()['due'],[])
 def test_future_actual_times_rejected(self):
  future=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
  with self.assertRaises(ValueError):self.save('labor',dict(occurred_at=future))
 def test_invalid_numbers_and_dates_save_nothing(self):
  for value in (True,'NaN','Infinity','-1','0.0001','1000000001'):
   with self.subTest(value=value):
    with self.assertRaises(ValueError):self.save('labor',dict(hours=value))
  with self.assertRaises(ValueError):self.save('budget',dict(end_date='2029-01-01'))
  self.assertEqual(self.state()['entries'],[])
 def test_closed_due_records_excluded(self):
  risk=self.save('risk',dict(due_date='2020-01-01'));self.assertEqual(self.state()['due'][0]['timing'],'overdue');self.revise('risk',risk,dict(status='closed'));self.assertEqual(self.state()['due'],[])
 def test_filter_search_and_history(self):
  a=self.save('equipment');self.revise('equipment',a,dict(condition='needs_check'));self.save('risk');self.assertEqual(len(self.state(kind='equipment',status='needs_check')['entries']),1);self.assertEqual(len(self.state(q='access')['entries']),1);self.assertEqual(len(self.state(kind='equipment',history='true')['entries']),2)
 def test_hash_corruption_blocks_reads_and_writes(self):
  self.save('supply')
  with self.store.connect() as db:db.execute("UPDATE resource_entries SET payload='{}' WHERE id=1")
  with self.assertRaises(ValueError):self.state()
  with self.assertRaises(ValueError):self.save('equipment')
 def test_exports_and_calendar_no_database_change(self):
  self.save('risk',dict(name='TEST, road; access'))
  with self.store.connect() as db:before=db.execute('SELECT count(*) FROM resource_entries').fetchone()[0]
  for fmt in ('csv','json','html'):self.assertTrue(R.export(self.store,dict(format=fmt))[0])
  raw=R.calendar(self.store,{})[0];self.assertIn(b'TEST\\, road\\; access',raw);self.assertIn(b'VALUE=DATE:20300102',raw)
  with self.store.connect() as db:self.assertEqual(before,db.execute('SELECT count(*) FROM resource_entries').fetchone()[0])
 def test_no_core_task_or_finance_side_effect(self):
  with self.store.connect() as db:before={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('observations','tasks')}
  self.save('labor');self.save('budget')
  with self.store.connect() as db:self.assertEqual(before,{t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in before})
 def test_doctor_checks_resource_history(self):
  from nexus.farm_app.operations_recovery import doctor
  self.save('supply');self.assertTrue(doctor(self.store.path)['resource_ledger_checks'][0]['valid'])
  with self.store.connect() as db:db.execute("UPDATE resource_entries SET content_sha256='changed' WHERE id=1")
  self.assertFalse(doctor(self.store.path)['ok'])
 def test_bad_fields_object_is_value_error(self):
  data=self.data('supply');data['values']=['bad']
  with self.assertRaises(ValueError):R.save(self.store,data)
 def test_quantity_zero_vs_unknown_marker(self):
  self.save('supply',dict(minimum=None));self.assertIsNone(self.state()['totals']['supplies'][0]['low_stock'])
  self.save('supply',dict(name='TEST zero marker',minimum='0'));self.assertTrue(self.state()['totals']['supplies'][1]['low_stock'])
 def test_backup_contains_append_only_entries(self):
  from nexus.farm_app.backup import backup_database
  import sqlite3
  a=self.save('supply');self.revise('supply',a,dict(storage='TEST other'))
  target,_=backup_database(self.store.path,Path(self.temp.name)/'backups')
  db=sqlite3.connect(target)
  try:self.assertEqual(db.execute('SELECT count(*) FROM resource_entries').fetchone()[0],2)
  finally:db.close()
 def test_cost_rounds_half_up(self):
  self.save('labor',dict(hours='0.005',hourly_ngn='1'));self.assertEqual(self.state()['totals']['labor_summary']['known_cost_ngn'],'0.01')

 def test_unicode_calendar_lines_are_folded(self):
  self.save('risk',dict(name='TEST '+('ƙananan '*30)))
  raw=R.calendar(self.store,{})[0]
  self.assertTrue(all(len(line)<=75 for line in raw.split(b'\r\n')))
  self.assertIn('ƙananan'.encode(),raw.replace(b'\r\n ',b''))
 def test_concurrent_reservations_cannot_overbook(self):
  from concurrent.futures import ThreadPoolExecutor
  self.save('supply');self.save('movement')
  def reserve(name):
   try:return self.save('reservation',dict(quantity='7',purpose=name))
   except ValueError:return None
  with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(reserve,['TEST one','TEST two']))
  self.assertEqual(sum(r is not None for r in results),1)
  self.assertEqual(self.state()['totals']['supplies'][0]['available'],'3')
 def test_csv_neutralizes_formula_and_html_escapes(self):
  self.save('equipment',dict(name='=SUM(1,2)',notes='<script>TEST</script>'))
  csv=R.export(self.store,dict(format='csv'))[0];self.assertIn(b"'=SUM",csv)
  html=R.export(self.store,dict(format='html'))[0];self.assertNotIn(b'<script>TEST',html);self.assertIn(b'&lt;script&gt;',html)

class BrandingTests(unittest.TestCase):
 def test_brand_is_readable_safe_and_idempotent(self):
  raw=project_branding.inject(b'<html><body><form>Unchanged</form></body></html>','/?private=1');self.assertIn(b'https://yd.ydtech.workers.dev',raw);self.assertIn(b'rel="noopener noreferrer"',raw);self.assertNotIn(b'private=1',raw);self.assertIn(b'<form>Unchanged</form>',raw);self.assertEqual(project_branding.inject(raw,'/'),raw)
 def test_exports_and_non_utf8_not_changed(self):
  raw=b'<html>saved export</html>';self.assertEqual(project_branding.inject(raw,'/api/resources/export'),raw);self.assertEqual(project_branding.inject(b'\xff','/'),b'\xff')
 def test_each_resource_workflow_has_help(self):
  for kind in R.SPECS:
   guide=page_guides.context('/resources',kind)[0];self.assertEqual(guide['id'],'resource-'+kind);self.assertEqual(len(guide['fields']),len(R.SPECS[kind]['fields'])+4)

class ResourceHTTPTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.temp=tempfile.TemporaryDirectory();cls.store=FarmStore(Path(cls.temp.name)/'test.db');cls.store.create('farms',dict(name='TEST',location='TEST'));cls.store.create('fields',dict(farm_id=1,name='TEST',crop='maize'));cls.http=HTTPServer(('127.0.0.1',0),operations.make_handler(server.make_handler(cls.store),cls.store));cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start();cls.base='http://127.0.0.1:'+str(cls.http.server_port)
 @classmethod
 def tearDownClass(cls):cls.http.shutdown();cls.http.server_close();cls.thread.join();cls.temp.cleanup()
 def request(self,path,data=None,origin=None):
  req=Request(self.base+path,data=json.dumps(data).encode() if data is not None else None,headers={'Origin':origin or self.base,'Content-Type':'application/json'})
  with urlopen(req) as r:
   raw=r.read();self.assertEqual(int(r.headers['Content-Length']),len(raw));return raw,r.headers
 def test_pages_and_assets(self):
  raw,_=self.request('/resources');self.assertIn(b'data-nexus-brand="1"',raw);self.assertIn(b'data-nxh-boot="1"',raw)
  for asset in ('resource_workspace.js','resource_workspace.css'):self.assertTrue(self.request('/ops-assets/'+asset)[0])
 def test_create_and_read_api(self):
  data=dict(kind='supply',field_id=1,source='actual',reporter='TEST',reason='TEST',values=FIXTURES['supply']);saved=json.loads(self.request('/api/resources/save',data)[0]);self.assertTrue(saved['record_id']);self.assertTrue(json.loads(self.request('/api/resources/state')[0])['entries'])
 def test_origin_and_array_rejected(self):
  with self.assertRaises(HTTPError) as e:self.request('/api/resources/save',{},'http://evil.invalid')
  self.assertEqual(e.exception.code,403)
  with self.assertRaises(HTTPError) as e:self.request('/api/resources/save',[])
  self.assertEqual(e.exception.code,400)
 def test_malformed_values_object_rejected(self):
  data=dict(kind='supply',field_id=1,source='actual',reporter='TEST',reason='TEST',values=['bad'])
  with self.assertRaises(HTTPError) as e:self.request('/api/resources/save',data)
  self.assertEqual(e.exception.code,400)
 def test_export_has_download_headers_not_brand(self):
  raw,h=self.request('/api/resources/export?format=html');self.assertIn('attachment',h['Content-Disposition']);self.assertNotIn(b'data-nexus-brand',raw)
 def test_guide_route_and_catalogue(self):
  raw,_=self.request('/help-centre?topic=resource-supply');self.assertIn(b'fictional',raw);self.assertIn(b'data-nexus-brand',raw)
  self.assertEqual(len(json.loads(self.request('/api/resources/meta')[0])['specs']),36)

if __name__=='__main__':unittest.main()
