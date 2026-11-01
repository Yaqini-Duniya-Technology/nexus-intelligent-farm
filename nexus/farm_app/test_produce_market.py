import json,unittest,threading
from pathlib import Path
from http.server import HTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from nexus.farm_app import test_farm_resources as fixtures
from nexus.farm_app import farm_resources as R,produce_market as M,operations,server,page_guides
from nexus.farm_app.seasons import initialize_seasons
from nexus.farm_app.harvests import initialize_harvests
from nexus.farm_app.finance import initialize_finance
F={
'produce_lot':dict(name='TEST maize A',crop='maize',quantity_kg='100',harvest_id=None,status='available',storage='TEST store',notes='TEST weighed'),
'produce_adjustment':dict(lot_id=1,quantity_kg='-2',occurred_at='2020-02-01T12:00:00+00:00',notes='TEST weighing'),
'produce_check':dict(lot_id=1,occurred_at='2020-02-01T12:00:00+00:00',result='uncertain',method='TEST five bags',findings='TEST observation'),
'market_offer':dict(lot_id=1,name='TEST offer',unit_ngn='500',valid_until=None,status='open',description='TEST local draft'),
'buyer_enquiry':dict(contact_id=1,lot_id=1,quantity_kg='20',due_date='2030-01-01',status='new',notes='TEST request'),
'sales_order':dict(name='TEST order',contact_id=1,order_date='2020-01-01',due_date='2030-01-01',status='draft',terms='TEST agreement'),
'sales_line':dict(order_id=1,lot_id=1,quantity_kg='20',status='active',unit_ngn='500',notes='TEST terms'),
'order_delivery':dict(line_id=1,quantity_kg='5',occurred_at='2020-02-01T12:00:00+00:00',reference='TEST delivery A',notes='TEST delivered'),
'customer_payment':dict(order_id=1,direction='receipt',amount_ngn='1000',occurred_at='2020-02-01T12:00:00+00:00',reference='TEST receipt A',notes='TEST user report'),
'customer_return':dict(delivery_id=1,quantity_kg='1',occurred_at='2020-02-02T12:00:00+00:00',disposition='restocked',notes='TEST return'),
'transport_quote':dict(order_id=1,contact_id=1,amount_ngn='2000',valid_until=None,notes='TEST estimate'),
'sale_note':dict(order_id=1,owner='TEST user',due_date='2030-01-01',status='open',notes='TEST planned follow-up')}
class MarketTests(unittest.TestCase):
 def setUp(self):
  fixtures.ResourcesTests.setUp(self);self.ids={};self.source='actual'
  initialize_seasons(self.store);initialize_harvests(self.store);initialize_finance(self.store)
  with self.store.connect() as db:
   for i in (1,2):
    db.execute('INSERT INTO crop_seasons VALUES(?,?,?,?,?,?,?,?,?)',(i,i,'TEST season','maize','Unknown',1,'2020-01-01','2020-08-01','2020-01-01T00:00:00+00:00'))
    db.execute('INSERT INTO harvests VALUES(?,?,?,?,?,?,?)',(i,i,'2020-08-01',100,1,'TEST harvest','2020-08-01T00:00:00+00:00'))
 def data(self,kind,values=None,**kw):return dict(kind=kind,field_id=1,source=self.source,reporter='TEST user',reason='TEST entry',values=dict((fixtures.FIXTURES|F)[kind])|(values or {}))|kw
 def save(self,kind,values=None,**kw):return R.save(self.store,self.data(kind,values,**kw))
 def current(self,rid):return next(e for e in R.state(self.store,dict(include_tests='true'))['references'] if e['record_id']==rid)
 def revise(self,rid,values):
  row=self.current(rid);d=dict(kind=row['kind'],field_id=row['field_id'],source=row['payload']['source'],reporter='TEST user',reason='TEST correction',values=row['payload']['values']|values,record_id=rid,base_id=row['id']);return R.save(self.store,d)
 def make(self,kind):
  if kind in self.ids:return self.ids[kind]
  values={}
  for f in R.SPECS[kind]['fields']:
   if f['type']=='reference' and f['ref'] in R.SPECS:values[f['key']]=self.make(f['ref'])
  if kind in ('order_delivery','customer_payment'):self.confirm()
  rid=self.save(kind,values)['record_id'];self.ids[kind]=rid;return rid
 def confirm(self):
  line=self.make('sales_line');order=self.current(line)['payload']['values']['order_id']
  if self.current(order)['payload']['values']['status']=='draft':self.revise(order,dict(status='confirmed'))
  return order
 def report(self):return R.state(self.store,dict(include_tests='true'))['market']
 def test_twelve_workflows_persist(self):
  for kind in F:self.make(kind)
  self.assertTrue(all(R.state(self.store)['counts'][k]==1 for k in F))
 def test_draft_order_does_not_reserve(self):
  self.make('sales_line');self.assertEqual(self.report()['produce_lots'][0]['reserved_kg'],'0')
 def test_confirmed_order_reserves(self):
  self.confirm();lot=self.report()['produce_lots'][0];self.assertEqual((lot['reserved_kg'],lot['available_kg']),('20','80'))
 def test_confirm_empty_order_rejected(self):
  order=self.make('sales_order')
  with self.assertRaises(ValueError):self.revise(order,dict(status='confirmed'))
 def test_create_confirmed_without_draft_rejected(self):
  contact=self.make('contact')
  with self.assertRaises(ValueError):self.save('sales_order',dict(contact_id=contact,status='confirmed'))
 def test_second_order_cannot_overbook(self):
  self.confirm();contact=self.ids['contact'];order=self.save('sales_order',dict(contact_id=contact,name='TEST second'))['record_id'];self.save('sales_line',dict(order_id=order,lot_id=self.ids['produce_lot'],quantity_kg='90'))
  with self.assertRaises(ValueError):self.revise(order,dict(status='confirmed'))
  self.assertEqual(self.report()['produce_lots'][0]['available_kg'],'80')
 def test_increased_confirmed_line_cannot_overbook(self):
  self.confirm()
  with self.assertRaises(ValueError):self.revise(self.ids['sales_line'],dict(quantity_kg='101'))
 def test_deliveries_update_market_balance_and_reservation(self):
  self.make('order_delivery');lot=self.report()['produce_lots'][0];self.assertEqual((lot['balance_kg'],lot['reserved_kg'],lot['available_kg']),('95','15','80'))
 def test_oversupply_rejected(self):
  self.confirm()
  with self.assertRaises(ValueError):self.save('order_delivery',dict(line_id=self.ids['sales_line'],quantity_kg='21'))
 def test_draft_delivery_rejected(self):
  line=self.make('sales_line')
  with self.assertRaises(ValueError):self.save('order_delivery',dict(line_id=line))
 def test_price_frozen_after_delivery(self):
  self.make('order_delivery')
  with self.assertRaises(ValueError):self.revise(self.ids['sales_line'],dict(unit_ngn='600'))
 def test_price_frozen_after_receipt(self):
  self.make('customer_payment')
  with self.assertRaises(ValueError):self.revise(self.ids['sales_line'],dict(unit_ngn='600'))
 def test_receipt_and_refund_exact(self):
  self.make('customer_payment');self.save('customer_payment',dict(order_id=self.ids['sales_order'],direction='refund',amount_ngn='200',occurred_at='2020-02-02T12:00:00+00:00'));order=self.report()['sales_orders'][0];self.assertEqual((order['total_ngn'],order['net_receipts_ngn'],order['unreceived_ngn']),('10000.00','800','9200.00'))
 def test_overpayment_rejected(self):
  self.confirm()
  with self.assertRaises(ValueError):self.save('customer_payment',dict(order_id=self.ids['sales_order'],amount_ngn='10001'))
 def test_refund_before_receipt_rejected(self):
  self.make('customer_payment')
  with self.assertRaises(ValueError):self.save('customer_payment',dict(order_id=self.ids['sales_order'],direction='refund',amount_ngn='100',occurred_at='2020-01-20T12:00:00+00:00'))
 def test_refund_over_receipts_rejected(self):
  self.make('customer_payment')
  with self.assertRaises(ValueError):self.save('customer_payment',dict(order_id=self.ids['sales_order'],direction='refund',amount_ngn='1001'))
 def test_return_restocks_and_reopens_outstanding_quantity(self):
  self.make('customer_return');lot=self.report()['produce_lots'][0];self.assertEqual((lot['balance_kg'],lot['reserved_kg']),('96','16'));self.assertEqual(self.report()['sales_orders'][0]['net_delivered_kg'],'4')
 def test_quarantined_returns_not_available(self):
  self.make('order_delivery');self.save('customer_return',dict(delivery_id=self.ids['order_delivery'],disposition='quarantined'));lot=self.report()['produce_lots'][0];self.assertEqual((lot['balance_kg'],lot['quarantined_returns_kg']),('95','1'))
 def test_returns_cannot_exceed_delivery(self):
  self.make('order_delivery')
  with self.assertRaises(ValueError):self.save('customer_return',dict(delivery_id=self.ids['order_delivery'],quantity_kg='6'))
 def test_return_cannot_predate_delivery(self):
  self.make('order_delivery')
  with self.assertRaises(ValueError):self.save('customer_return',dict(delivery_id=self.ids['order_delivery'],occurred_at='2020-01-31T12:00:00+00:00'))
 def test_hold_blocks_new_confirmation(self):
  self.make('sales_line');self.revise(self.ids['produce_lot'],dict(status='hold'))
  with self.assertRaises(ValueError):self.confirm()
 def test_hold_can_be_recorded_after_confirmation(self):
  self.confirm();self.revise(self.ids['produce_lot'],dict(status='hold'));self.assertEqual(self.report()['produce_lots'][0]['status'],'hold')
 def test_hold_blocks_new_delivery(self):
  self.confirm();self.revise(self.ids['produce_lot'],dict(status='hold'))
  with self.assertRaises(ValueError):self.save('order_delivery',dict(line_id=self.ids['sales_line']))
 def test_close_releases_remaining_reservation_without_success_claim(self):
  self.make('order_delivery');self.revise(self.ids['sales_order'],dict(status='closed'));self.assertEqual(self.report()['produce_lots'][0]['reserved_kg'],'0');self.assertEqual(self.report()['sales_orders'][0]['undelivered_kg'],'15')
 def test_loss_can_expose_commitment_shortfall(self):
  self.confirm();self.save('produce_adjustment',dict(lot_id=self.ids['produce_lot'],quantity_kg='-90'));lot=self.report()['produce_lots'][0];self.assertEqual((lot['balance_kg'],lot['available_kg'],lot['commitment_shortfall_kg']),('10','0','10'))
 def test_negative_quantity_balance_rejected(self):
  self.make('produce_lot')
  with self.assertRaises(ValueError):self.save('produce_adjustment',dict(lot_id=self.ids['produce_lot'],quantity_kg='-101'))
 def test_harvest_snapshot_and_drift(self):
  rid=self.save('produce_lot',dict(harvest_id=1))['record_id'];cap=self.current(rid)['payload']['captures']['harvest']
  with self.store.connect() as db:db.execute('UPDATE harvests SET note=? WHERE id=1',('TEST later',))
  self.assertEqual(self.current(rid)['payload']['captures']['harvest'],cap);self.assertEqual(self.report()['harvest_links'][0]['status'],'changed_since_link')
 def test_harvest_assignments_cannot_exceed_snapshot(self):
  self.save('produce_lot',dict(harvest_id=1,quantity_kg='60'))
  with self.assertRaises(ValueError):self.save('produce_lot',dict(harvest_id=1,quantity_kg='50',name='TEST second lot'))
 def test_harvest_cross_field_rejected(self):
  with self.assertRaises(ValueError):self.save('produce_lot',dict(harvest_id=2))
 def test_test_harvest_link_rejected(self):
  with self.assertRaises(ValueError):self.save('produce_lot',dict(harvest_id=1),source='test')
 def test_test_contacts_and_market_separate(self):
  self.source='test';self.confirm();self.assertEqual(R.state(self.store,dict(area='market'))['entries'],[]);state=R.state(self.store,dict(area='market',include_tests='true'));self.assertTrue(state['entries']);self.assertTrue(any(r['kind']=='contact' for r in state['references']))
 def test_market_export_does_not_include_unrelated_resources(self):
  self.make('sales_line');self.save('risk');raw=R.export(self.store,dict(area='market',format='json'))[0];data=json.loads(raw);self.assertNotIn('logistics',data);self.assertTrue(all(e['kind'] in M.SPECS for e in data['entries']))
 def test_statement_omits_contact_details_and_is_readonly(self):
  self.make('customer_payment');self.revise(self.ids['contact'],dict(permission='granted',contact='PRIVATE@example.invalid'));before=Path(self.store.path).read_bytes();raw=M.statement(self.store,self.ids['sales_order'],'json')[0];self.assertNotIn(b'PRIVATE@example.invalid',raw);self.assertIn(b'not a frozen',raw);self.assertEqual(before,Path(self.store.path).read_bytes())
 def test_offer_sheet_is_manual_escaped_copy(self):
  rid=self.make('market_offer');self.revise(rid,dict(description='<script>TEST</script>'));raw=M.offer_sheet(self.store,rid)[0];self.assertIn(b'&lt;script&gt;',raw);self.assertNotIn(b'<script>TEST',raw);self.assertIn(b'nothing is published',raw)
 def test_decimal_price_rounds_half_up(self):
  self.make('sales_line');self.revise(self.ids['sales_line'],dict(quantity_kg='0.005',unit_ngn='1'));self.assertEqual(self.report()['sales_orders'][0]['total_ngn'],'0.01')
 def test_no_core_stock_finance_or_harvest_mutation(self):
  with self.store.connect() as db:before={t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in ('harvests','season_transactions','observations','tasks')}
  self.make('customer_return');self.make('customer_payment')
  with self.store.connect() as db:self.assertEqual(before,{t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in before})
 def test_guides_and_route_context(self):
  self.assertEqual(page_guides.context('/market')[0]['id'],'market-overview')
  for kind in F:self.assertEqual(page_guides.context('/market',kind)[0]['id'],'resource-'+kind)
 def test_idempotent_receipt_retry(self):
  self.make('customer_payment');same=self.save('customer_payment',dict(order_id=self.ids['sales_order']));self.assertTrue(same['reused']);self.assertEqual(self.report()['sales_orders'][0]['net_receipts_ngn'],'1000')

 def test_concurrent_confirmations_cannot_oversell(self):
  from concurrent.futures import ThreadPoolExecutor
  lot=self.make('produce_lot');buyer=self.make('contact');orders=[]
  for name in ('TEST A','TEST B'):
   order=self.save('sales_order',dict(name=name,contact_id=buyer))['record_id'];self.save('sales_line',dict(order_id=order,lot_id=lot,quantity_kg='60'));orders.append(order)
  def confirm(rid):
   try:self.revise(rid,dict(status='confirmed'));return True
   except ValueError:return False
  with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(confirm,orders))
  self.assertEqual(sum(results),1);self.assertEqual(self.report()['produce_lots'][0]['reserved_kg'],'60')
 def test_return_with_shortfall_still_records_actual_fact(self):
  self.make('sales_line');self.revise(self.ids['sales_line'],dict(quantity_kg='100'));self.make('order_delivery');self.revise(self.ids['order_delivery'],dict(quantity_kg='100'));self.save('customer_return',dict(delivery_id=self.ids['order_delivery'],quantity_kg='5',disposition='quarantined'));lot=self.report()['produce_lots'][0];self.assertEqual((lot['balance_kg'],lot['reserved_kg'],lot['commitment_shortfall_kg']),('0','5','5'))
 def test_sales_line_cancelled_history_kept(self):
  line=self.make('sales_line');self.revise(line,dict(status='cancelled'));self.assertEqual(self.report()['sales_orders'][0]['total_ngn'],'0');self.assertEqual(len(R.state(self.store,dict(kind='sales_line',history='true'))['entries']),2)
 def test_stale_market_revision_rejected(self):
  rid=self.make('market_offer');old=self.current(rid);self.revise(rid,dict(status='paused'))
  with self.assertRaises(ValueError):R.save(self.store,dict(kind='market_offer',field_id=1,source='actual',reporter='TEST user',reason='TEST stale',values=old['payload']['values']|dict(status='withdrawn'),record_id=rid,base_id=old['id']))
 def test_replacement_delivery_after_return(self):
  self.make('order_delivery');self.revise(self.ids['order_delivery'],dict(quantity_kg='20'));self.make('customer_return');self.save('order_delivery',dict(line_id=self.ids['sales_line'],quantity_kg='1',occurred_at='2020-02-03T12:00:00+00:00',reference='TEST replacement'));self.assertEqual(self.report()['sales_orders'][0]['net_delivered_kg'],'20')

class MarketHTTPTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  import tempfile
  cls.temp=tempfile.TemporaryDirectory();from nexus.farm_app.store import FarmStore
  cls.store=FarmStore(Path(cls.temp.name)/'test.db');cls.http=HTTPServer(('127.0.0.1',0),operations.make_handler(server.make_handler(cls.store),cls.store));cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start();cls.base='http://127.0.0.1:'+str(cls.http.server_port)
 @classmethod
 def tearDownClass(cls):cls.http.shutdown();cls.http.server_close();cls.thread.join();cls.temp.cleanup()
 def get(self,path):
  with urlopen(self.base+path) as r:
   raw=r.read();self.assertEqual(len(raw),int(r.headers['Content-Length']));return raw
 def test_market_page_and_guides(self):
  raw=self.get('/market');self.assertIn(b'market-report',raw);self.assertIn(b'data-nexus-brand',raw);self.assertIn(b'data-nxh-boot',raw);self.assertIn(b'fictional',self.get('/help-centre?topic=resource-sales_order'))
 def test_area_filter_api(self):self.assertEqual(json.loads(self.get('/api/resources/state?area=market'))['entries'],[])
 def test_statement_errors(self):
  for path in ('/api/market/statement?order_id=0','/api/market/offer?offer_id=99'):
   with self.assertRaises(HTTPError) as e:self.get(path)
   self.assertEqual(e.exception.code,400)

if __name__=='__main__':unittest.main()
