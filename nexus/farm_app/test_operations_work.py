import copy
import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from nexus.farm_app.store import FarmStore
from nexus.farm_app import work_orders as w
from nexus.farm_app.capture_review import capture_review


class WorkOrderTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.path=Path(t.name)/'farm.db';self.store=FarmStore(self.path)
        self.store.create('farms',{'name':'TEST','location':'Lokoja'})
        for name in ('South','North'):self.store.create('fields',{'farm_id':1,'name':name,'crop':'maize'})
        self.store.create('observations',{'field_id':1,'note':'TEST cobs'})
        w.initialize(self.store)
    def plan(self,**changes):
        return dict({'field_id':1,'observation_id':1,'title':'TEST inspection','reporter':'TEST farmer','owner':'TEST owner',
                     'priority':'routine','due_date':(datetime.now(timezone.utc)+timedelta(days=3)).date().isoformat(),
                     'resources':'Unknown','constraints':'Unknown','estimated_ngn':'100.25','checklist':['Count plants','Record maturity']},**changes)
    def create(self,**changes):return w.create(self.store,self.plan(**changes))
    def order(self):return w.state(self.store)['orders'][0]
    def event_data(self,action,**changes):
        o=self.order();return dict({'work_order_id':o['id'],'base_id':o['base_id'],'state_hash':o['state_hash'],
                                  'reporter':'TEST actor','note':'TEST actual work / reason','action':action},**changes)
    def event(self,action,**changes):return w.change(self.store,self.event_data(action,**changes))
    def test_initial_persistence_and_estimated_kobo(self):
        self.create();self.assertEqual(w.state(FarmStore(self.path))['orders'][0]['state']['estimated_kobo'],10025)
    def test_duplicate_plan_reuses_order(self):
        a=self.create();b=self.create();self.assertEqual(a['id'],b['id']);self.assertTrue(b['reused'])
    def test_zero_budget_distinct_from_unknown(self):
        self.create(estimated_ngn='');self.assertIsNone(self.order()['state']['estimated_kobo'])
        self.create(title='Zero budget',estimated_ngn='0');self.assertEqual(self.order()['state']['estimated_kobo'],0)
    def test_bad_budgets_rejected(self):
        for amount in ('NaN','Infinity','-1','0.001',True,'1000000001'):
            with self.subTest(amount=amount),self.assertRaises(ValueError):self.create(estimated_ngn=amount)
        self.assertEqual(w.state(self.store)['orders'],[])
    def test_cross_field_observation_rejected(self):
        with self.assertRaises(ValueError):self.create(field_id=2)
    def test_invalid_field_and_observation_ids_rejected(self):
        for changes in ({'field_id':True},{'field_id':999},{'observation_id':True},{'observation_id':999}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.create(**changes)
    def test_optional_observation_link(self):
        self.create(observation_id=None);self.assertIsNone(self.order()['observation_id'])
    def test_required_text_priority_and_date(self):
        for changes in ({'owner':''},{'title':' '},{'priority':'urgent'},{'due_date':'2026-99-20'},{'resources':'x'*3001}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.create(**changes)
    def test_distinct_bounded_checklist(self):
        for items in (['same','same'],['x']*31,'bad',['']):
            with self.subTest(items=items),self.assertRaises(ValueError):self.create(checklist=items)
    def test_start_block_resume_transitions(self):
        self.create();self.event('start');self.assertEqual(self.order()['state']['status'],'in_progress')
        self.event('block');self.assertEqual(self.order()['state']['status'],'blocked')
        self.event('resume');self.assertEqual(self.order()['state']['status'],'in_progress')
        self.assertEqual(len(self.order()['events']),3)
    def test_completion_requires_start_and_checklist(self):
        self.create()
        with self.assertRaises(ValueError):self.event('complete')
        self.event('start')
        with self.assertRaises(ValueError):self.event('complete')
        self.event('checklist',checked=[True,True]);self.event('complete')
        self.assertEqual(self.order()['state']['status'],'done')
        self.assertEqual(self.order()['state']['actual_work'],'TEST actual work / reason')
    def test_cancelled_orders_reject_more_status_events(self):
        self.create();self.event('cancel')
        for action in ('start','complete','checklist','revise'):
            with self.subTest(action=action),self.assertRaises(ValueError):self.event(action,checked=[True,True])
    def test_checklist_requires_boolean_values(self):
        self.create()
        for done in ([1,0],[True],None):
            with self.subTest(done=done),self.assertRaises(ValueError):self.event('checklist',checked=done)
    def test_stale_form_rejected_without_extra_event(self):
        self.create();old=self.event_data('block');self.event('start')
        with self.assertRaisesRegex(ValueError,'changed'):w.change(self.store,old)
        self.assertEqual(len(self.order()['events']),1)
    def test_repeat_event_safe_after_first_response_lost(self):
        self.create();request=self.event_data('start');a=w.change(self.store,request);b=w.change(self.store,request)
        self.assertEqual(a['id'],b['id']);self.assertTrue(b['reused']);self.assertEqual(len(self.order()['events']),1)
    def test_revision_preserves_old_events_and_progress(self):
        self.create();self.event('checklist',checked=[True,False]);before=copy.deepcopy(self.order())
        self.event('revise',**self.plan(title='Revised plan',checklist=['Count plants','New item']))
        after=self.order();self.assertEqual(after['payload'],before['payload']);self.assertEqual(after['events'][0],before['events'][0])
        self.assertTrue(after['state']['checklist'][0]['done']);self.assertFalse(after['state']['checklist'][1]['done'])
    def test_future_event_rejected(self):
        self.create()
        with self.assertRaises(ValueError):self.event('start',performed_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat())
    def test_time_before_creation_rejected(self):
        self.create()
        with self.assertRaises(ValueError):self.event('start',performed_at='2020-01-01T00:00:00+00:00')
    def test_event_does_not_complete_workspace_task(self):
        self.create(checklist=[]);self.event('start');self.event('complete')
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT status FROM tasks WHERE id=1').fetchone()[0],'pending')
            self.assertEqual(db.execute('SELECT count(*) FROM task_actions').fetchone()[0],0)
    def test_tampered_chain_rejected(self):
        self.create();self.event('start')
        with self.store.connect() as db:db.execute("UPDATE work_order_events SET content_sha256='bad'")
        with self.assertRaises(ValueError):self.order()
    def test_tampered_root_rejected(self):
        self.create()
        with self.store.connect() as db:db.execute("UPDATE work_orders SET content_sha256='bad'")
        with self.assertRaises(ValueError):self.order()
    def test_valid_hash_invalid_saved_state_is_rejected(self):
        from nexus.farm_app.operations_common import canonical,digest
        self.create()
        with self.store.connect() as db:
            payload=json.loads(db.execute('SELECT payload FROM work_orders').fetchone()[0]);payload['state']['status']='unverified_success'
            db.execute('UPDATE work_orders SET payload=?,content_sha256=?',(canonical(payload),digest(payload)))
        with self.assertRaises(ValueError):self.order()

    def test_capture_freezes_plan_and_event_chain(self):
        self.create();old=capture_review(self.path,1);self.event('start');new=capture_review(self.path,1)
        self.assertEqual(len(old['payload']['planned_work_orders'][0]['events']),0)
        self.assertEqual(len(new['payload']['planned_work_orders'][0]['events']),1)
        self.assertEqual(new,capture_review(self.path,1))
    def test_unlinked_order_excluded_from_observation_capture(self):
        self.create(observation_id=None);self.assertEqual(capture_review(self.path,1)['payload']['planned_work_orders'],[])
    def test_corruption_rolls_back_bundle_capture(self):
        self.create()
        with self.store.connect() as db:db.execute("UPDATE work_orders SET content_sha256='bad'")
        with self.assertRaises(ValueError):capture_review(self.path,1)
        with self.store.connect() as db:self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='decision_review_bundles'").fetchone())


if __name__=='__main__':unittest.main()
