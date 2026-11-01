import json,unittest
from datetime import date,timedelta
from pathlib import Path
from nexus.farm_app import test_farm_resources as fixtures
FIXTURES=fixtures.FIXTURES
from nexus.farm_app import farm_resources as R,resource_logistics as L,page_guides
from nexus.farm_app.seasons import initialize_seasons
from nexus.farm_app.finance import initialize_finance
from nexus.farm_app.capture_review import capture_review
from nexus.farm_app.review_bundles import bundle_page
NEW={
 'batch':dict(supply_id=1,name='TEST lot A',expiry_date='2020-01-01',status='active',storage='TEST store',notes='TEST label'),
 'allocation':dict(batch_id=1,movement_id=1,quantity='4',notes='TEST allocation'),
 'quote':dict(contact_id=1,supply_id=1,quantity='10',unit_ngn='500',valid_until='2030-01-01',notes='TEST quote'),
 'purchase':dict(supply_id=1,name='TEST purchase',quantity='10',estimated_ngn='5000',status='planned',due_date='2030-01-01',notes='TEST plan'),
 'delivery':dict(purchase_id=1,quantity='8',occurred_at='2020-01-01T12:00:00+00:00',result='accepted',notes='TEST report'),
 'lot_check':dict(batch_id=1,occurred_at='2020-01-01T12:00:00+00:00',result='uncertain',findings='TEST observation'),
 'dispatch':dict(supply_id=1,contact_id=1,quantity='3',due_date='2030-01-01',status='planned',performed_at=None,notes='TEST dispatch'),
 'stock_check':dict(supply_id=1,quantity='7',occurred_at='2020-01-01T12:00:00+00:00',method='TEST count all pieces',notes='TEST count'),
 'handover':dict(equipment_id=1,receiver='TEST receiver',occurred_at='2020-01-01T12:00:00+00:00',condition='unknown',notes='TEST handover'),
 'budget_scope':dict(budget_id=1,season_id=1,status='active',basis='TEST relevance'),
 'expense_match':dict(budget_line_id=1,expense_id=1,status='active',basis='TEST whole expense'),
 'case_link':dict(resource_id=1,observation_id=1,status='active',basis='TEST relevance only')}
class LogisticsTests(unittest.TestCase):
 def setUp(self):
  fixtures.ResourcesTests.setUp(self);self.ids={}
  self.store.create('observations',dict(field_id=1,note='TEST case'))
  initialize_seasons(self.store);initialize_finance(self.store)
  with self.store.connect() as db:
   for i,fid in ((1,1),(2,2)):
    db.execute('INSERT INTO crop_seasons VALUES(?,?,?,?,?,?,?,?,?)',(i,fid,'TEST season','maize','Unknown',1,'2020-01-01','2020-08-01','2020-01-01T00:00:00+00:00'))
    db.execute('INSERT INTO season_transactions VALUES(?,?,?,?,?,?,?,?)',(i,i,'expense','2020-03-01T00:00:00+00:00','TEST cost',250000,'2020-03-01T00:00:00+00:00','2020-03-01T00:00:00+00:00'))
 def data(self,kind,values=None,**changes):return dict(kind=kind,field_id=1,source='actual',reporter='TEST user',reason='TEST entry',values=dict((FIXTURES|NEW)[kind])|(values or {}))|changes
 def save(self,kind,values=None,**changes):return R.save(self.store,self.data(kind,values,**changes))
 def make(self,kind):
  if kind in self.ids:return self.ids[kind]
  refs={}
  for field in R.SPECS[kind]['fields']:
   if field['type']=='reference' and field['ref'] in R.SPECS:refs[field['key']]=self.make(field['ref'])
  if kind=='expense_match':self.make('budget_scope')
  if kind=='case_link':refs['resource_id']=self.make('labor')
  result=self.save(kind,refs);self.ids[kind]=result['record_id'];return result['record_id']
 def current(self,rid):return next(r for r in R.state(self.store,{'include_tests':'true'})['references'] if r['record_id']==rid)
 def revise(self,rid,values,**changes):
  old=self.current(rid);data=dict(kind=old['kind'],field_id=old['field_id'],source=old['payload']['source'],reporter='TEST user',reason='TEST revision',values=old['payload']['values']|values,record_id=rid,base_id=old['id'])|changes;return R.save(self.store,data)
 def report(self):return R.state(self.store)['logistics']
 def test_all_twelve_new_workflows_persist(self):
  for kind in NEW:self.make(kind)
  self.assertTrue(all(R.state(self.store)['counts'][kind]==1 for kind in NEW))
 def test_allocations_preserve_overall_stock(self):
  self.make('allocation');report=self.report();self.assertEqual(report['lots'][0]['allocated_balance'],'4');self.assertEqual(report['unallocated_movements'][0]['unallocated'],'6');self.assertEqual(R.state(self.store)['totals']['supplies'][0]['balance'],'10')
 def test_overallocation_rejected_atomically(self):
  self.make('allocation');count=len(R.state(self.store)['entries'])
  with self.assertRaises(ValueError):self.save('allocation',dict(batch_id=self.ids['batch'],movement_id=self.ids['movement'],quantity='7'))
  self.assertEqual(len(R.state(self.store)['entries']),count)
 def test_lot_cannot_be_negative(self):
  self.make('allocation');issue=self.save('movement',dict(supply_id=self.ids['supply'],direction='issue',quantity='6'))['record_id']
  with self.assertRaises(ValueError):self.save('allocation',dict(batch_id=self.ids['batch'],movement_id=issue,quantity='5'))
 def test_cross_supply_allocation_rejected(self):
  self.make('batch');other=self.save('supply',dict(name='TEST second'))['record_id'];move=self.save('movement',dict(supply_id=other))['record_id']
  with self.assertRaises(ValueError):self.save('allocation',dict(batch_id=self.ids['batch'],movement_id=move))
 def test_movement_correction_revalidates_lots(self):
  self.make('allocation')
  with self.assertRaises(ValueError):self.revise(self.ids['movement'],dict(quantity='2'))
  self.assertEqual(self.report()['lots'][0]['allocated_balance'],'4')
 def test_signed_adjustment_allocation(self):
  self.make('allocation');move=self.save('movement',dict(supply_id=self.ids['supply'],direction='adjustment',quantity='-1'))['record_id']
  self.save('allocation',dict(batch_id=self.ids['batch'],movement_id=move,quantity='-1'));self.assertEqual(self.report()['lots'][0]['allocated_balance'],'3')
 def test_wrong_sign_rejected(self):
  self.make('batch');self.make('movement')
  with self.assertRaises(ValueError):self.save('allocation',dict(batch_id=self.ids['batch'],movement_id=self.ids['movement'],quantity='-1'))
 def test_expiry_unknown_soon_and_expired(self):
  lot=self.make('batch');self.assertEqual(self.report()['lots'][0]['expiry_state'],'expired');self.revise(lot,dict(expiry_date=None));self.assertEqual(self.report()['lots'][0]['expiry_state'],'unknown');self.revise(lot,dict(expiry_date=(date.today()+timedelta(days=5)).isoformat()));self.assertEqual(self.report()['lots'][0]['expiry_state'],'within_30_days')
 def test_lot_checks_do_not_change_status(self):
  self.make('lot_check');self.assertEqual(self.current(self.ids['batch'])['payload']['values']['status'],'active')
 def test_delivery_does_not_receive_stock(self):
  self.make('delivery');self.assertEqual(R.state(self.store)['totals']['supplies'][0]['balance'],'0')
 def test_dispatch_does_not_issue_stock(self):
  self.make('dispatch');self.assertEqual(R.state(self.store)['totals']['supplies'][0]['balance'],'0')
 def test_dispatch_completion_requires_actual_time(self):
  rid=self.make('dispatch')
  with self.assertRaises(ValueError):self.revise(rid,dict(status='completed'))
  self.revise(rid,dict(status='completed',performed_at='2020-01-01T12:00:00+00:00'))
 def test_handover_does_not_change_custodian(self):
  self.make('handover');self.assertEqual(self.current(self.ids['equipment'])['payload']['values']['owner'],'TEST owner')
 def test_quote_total_and_validity(self):
  self.make('quote');self.assertEqual(self.report()['quotes'][0]['quoted_total_ngn'],'5000.00')
 def test_physical_count_freezes_comparison_without_adjustment(self):
  self.make('movement');rid=self.make('stock_check');cap=self.current(rid)['payload']['captures']['count_comparison'];self.assertEqual((cap['recorded_balance'],cap['difference']),('10','-3'));self.revise(self.ids['movement'],dict(quantity='12'));self.assertEqual(self.current(rid)['payload']['captures']['count_comparison'],cap)
 def test_zero_count_is_supported(self):
  self.make('supply');self.save('stock_check',dict(supply_id=self.ids['supply'],quantity='0'));self.assertEqual(self.report()['stock_counts'][0]['counted'],'0')
 def test_budget_scope_same_field_only(self):
  self.make('budget')
  with self.assertRaises(ValueError):self.save('budget_scope',dict(budget_id=self.ids['budget'],season_id=2))
 def test_budget_cannot_have_two_active_scopes(self):
  self.make('budget_scope')
  with self.assertRaises(ValueError):self.save('budget_scope',dict(budget_id=self.ids['budget'],basis='TEST second scope'))
 def test_matching_requires_established_scope(self):
  self.make('budget_line')
  with self.assertRaises(ValueError):self.save('expense_match',dict(budget_line_id=self.ids['budget_line']))
 def test_one_whole_expense_cannot_be_matched_twice(self):
  self.make('expense_match')
  with self.assertRaises(ValueError):self.save('expense_match',dict(budget_line_id=self.ids['budget_line'],basis='TEST duplicate'))
 def test_withdrawn_match_allows_replacement(self):
  rid=self.make('expense_match');self.revise(rid,dict(status='withdrawn'));self.save('expense_match',dict(budget_line_id=self.ids['budget_line'],basis='TEST replacement'));self.assertEqual(self.report()['reconciliation'][0]['matched_expense_count'],1)
 def test_expense_snapshot_and_drift_are_separate(self):
  rid=self.make('expense_match');before=self.current(rid)['payload']['captures']['expense']
  with self.store.connect() as db:db.execute('UPDATE season_transactions SET amount_kobo=300000 WHERE id=1')
  self.assertEqual(self.current(rid)['payload']['captures']['expense'],before);self.assertTrue(any(r['status']=='changed_since_link' for r in self.report()['association_checks']));self.assertEqual(self.report()['reconciliation'][0]['matched_expenses_ngn'],'2500')
 def test_reconciliation_never_changes_cash(self):
  with self.store.connect() as db:before=[tuple(r) for r in db.execute('SELECT * FROM season_transactions')]
  self.make('expense_match')
  with self.store.connect() as db:self.assertEqual(before,[tuple(r) for r in db.execute('SELECT * FROM season_transactions')])
 def test_reconciliation_plan_difference_is_not_full_field_spending(self):
  self.make('expense_match');r=self.report()['reconciliation'][0];self.assertEqual(r['plan_minus_matched_ngn'],'500');self.assertIn('not all field',r['basis'])
 def test_test_resources_cannot_link_actual_expenses_or_cases(self):
  labor=self.save('labor',source='test')['record_id']
  with self.assertRaises(ValueError):self.save('case_link',dict(resource_id=labor),source='test')
 def test_case_target_snapshot_survives_correction(self):
  rid=self.make('case_link');before=self.current(rid)['payload']['captures']['resource'];self.revise(self.ids['labor'],dict(notes='TEST updated findings'));self.assertEqual(self.current(rid)['payload']['captures']['resource'],before);self.assertTrue(any(r['target_kind']=='resource' and r['status']=='changed_since_link' for r in self.report()['association_checks']))
 def test_contacts_not_selectable_for_case_capture(self):
  contact=self.make('contact')
  with self.assertRaises(ValueError):self.save('case_link',dict(resource_id=contact))
 def test_case_link_cannot_cross_field(self):
  rid=self.make('labor');self.store.create('observations',dict(field_id=2,note='TEST other'))
  with self.assertRaises(ValueError):self.save('case_link',dict(resource_id=rid,observation_id=2))
 def test_bundle_captures_selected_resource_and_preserves_earlier(self):
  first=capture_review(self.store.path,1);self.assertEqual(first['payload']['resource_case_links']['links'],[]);self.make('case_link');second=capture_review(self.store.path,1);self.assertEqual(len(second['payload']['resource_case_links']['links']),1);self.assertNotEqual(first['id'],second['id']);again=capture_review(self.store.path,1);self.assertEqual(second['id'],again['id']);self.assertIn('Explicit resource case links',bundle_page(second));self.revise(self.ids['labor'],dict(notes='TEST later'));self.assertNotIn('TEST later',json.dumps(second))
 def test_withdrawal_is_captured_explicitly(self):
  rid=self.make('case_link');self.revise(rid,dict(status='withdrawn'));bundle=capture_review(self.store.path,1);self.assertEqual(bundle['payload']['resource_case_links']['links'][0]['payload']['values']['status'],'withdrawn')
 def test_optional_missing_resource_table_supported(self):
  with self.store.connect() as db:db.execute('DROP TABLE resource_entries')
  self.assertIsNone(capture_review(self.store.path,1)['payload']['resource_case_links'])
 def test_new_form_guides_cover_fields(self):
  for kind in NEW:
   topic=page_guides.topic_by_id('resource-'+kind);self.assertEqual(len(topic['fields']),len(R.SPECS[kind]['fields'])+4);self.assertIn('fictional',topic['example_notice'])
 def test_exports_include_frozen_links_and_readonly_reports(self):
  self.make('case_link');raw=R.export(self.store,dict(format='json'))[0];self.assertIn(b'captures',raw);self.assertIn(b'association_checks',raw)

 def test_readiness_counts_frozen_links(self):
  from nexus.farm_app.review_readiness import summarize
  self.make('case_link');self.revise(self.ids['labor'],dict(notes='TEST new evidence'));bundle=capture_review(self.store.path,1);checks=summarize(bundle)['resource_case_links'];self.assertEqual((checks['active'],checks['changed_targets']),(1,1))
 def test_case_capture_checks_nested_expense_drift(self):
  rid=self.make('expense_match');self.save('case_link',dict(resource_id=rid))
  with self.store.connect() as db:db.execute('UPDATE season_transactions SET amount_kobo=260000 WHERE id=1')
  link=capture_review(self.store.path,1)['payload']['resource_case_links']['links'][0]
  self.assertEqual(link['dependency_checks_at_capture'][0]['status'],'changed_since_link')
 def test_removed_expense_is_flagged_not_replaced(self):
  self.make('expense_match')
  with self.store.connect() as db:db.execute('DELETE FROM season_transactions WHERE id=1')
  self.assertTrue(any(r['status']=='current_record_missing' for r in self.report()['association_checks']));self.assertEqual(self.report()['reconciliation'][0]['matched_expenses_ngn'],'2500')
 def test_no_future_delivery_event_is_saved(self):
  self.make('purchase')
  with self.assertRaises(ValueError):self.save('delivery',dict(purchase_id=self.ids['purchase'],occurred_at='2099-01-01T12:00:00+00:00'))
 def test_old_bundle_payload_not_rewritten_by_new_capture(self):
  first=capture_review(self.store.path,1)
  with self.store.connect() as db:before=db.execute('SELECT payload FROM decision_review_bundles WHERE id=?',(first['id'],)).fetchone()[0]
  self.make('case_link');capture_review(self.store.path,1)
  with self.store.connect() as db:self.assertEqual(before,db.execute('SELECT payload FROM decision_review_bundles WHERE id=?',(first['id'],)).fetchone()[0])

if __name__=='__main__':unittest.main()
