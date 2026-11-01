from datetime import datetime,timezone
from nexus.farm_app.studio_test_support import StudioFixture
from nexus.farm_app import studio_cases as c,studio_links as l,field_measurements as m,studio_ledger as ledger,studio_reports
from nexus.farm_app.operations_common import readonly
from nexus.farm_app.capture_review import capture_review
from nexus.farm_app.operations_records import search

class CaseNotebookTests(StudioFixture):
    def test_case_save_and_answer_revision_preserve_original(self):
        a=c.save(self.store,'case',self.case());c.save(self.store,'case',self.case(root_id=a['id'],base_id=a['id'],reason='Human answer',questions=[{'question':'Which crop season?','status':'answered','answer':'Not established; reviewed by farmer'}]))
        rows=c.entries(self.path,'case',{'history':'true'});self.assertEqual(len(rows),2);self.assertEqual(rows[1]['payload']['data']['questions'][0]['status'],'open')
    def test_answered_requires_text(self):
        with self.assertRaises(ValueError):c.save(self.store,'case',self.case(questions=[{'question':'Why?','status':'answered','answer':' '}]))
    def test_active_case_requires_review_date(self):
        with self.assertRaises(ValueError):c.save(self.store,'case',self.case(next_review_date=None))
    def test_closed_case_does_not_complete_task(self):
        c.save(self.store,'case',self.case(status='closed',next_review_date=None,reason='Closed tracking, cause unresolved'))
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT status FROM tasks WHERE id=1').fetchone()[0],'pending')
    def test_case_queue_lagos_timing(self):
        c.save(self.store,'case',self.case(next_review_date='2026-11-01'))
        row=c.queue(self.path,datetime(2026,10,31,23,30,tzinfo=timezone.utc))[0]
        self.assertEqual(row['timing'],'today');self.assertEqual(row['open_questions'],1)
    def test_stale_case_revision_rejected(self):
        c.save(self.store,'case',self.case());c.save(self.store,'case',self.case(root_id=1,base_id=1,title='Revised',reason='Revision'))
        with self.assertRaises(ValueError):c.save(self.store,'case',self.case(root_id=1,base_id=1,title='Stale',reason='Old form'))
    def test_tags_are_bounded_and_filtered(self):
        c.save(self.store,'case',self.case(tags=['Maize','Season']))
        self.assertEqual(len(c.entries(self.path,'case',{'tag':'maize'})),1)
        self.assertEqual(c.entries(self.path,'case',{'tag':'water'}),[])
        with self.assertRaises(ValueError):c.save(self.store,'case',self.case(tags=['Maize','maize']))
    def test_note_revisions_and_pinned_sorting(self):
        c.save(self.store,'note',self.note(pinned=True));c.save(self.store,'note',self.note(title='Later unpinned'))
        self.assertTrue(c.entries(self.path,'note')[0]['payload']['data']['pinned'])
        c.save(self.store,'note',self.note(root_id=1,base_id=1,content='Revised note',reason='Correction',pinned=True))
        self.assertEqual(len(c.entries(self.path,'note',{'history':'true'})),3)
    def test_note_cannot_change_field_on_revision(self):
        c.save(self.store,'note',self.note())
        with self.assertRaises(ValueError):c.save(self.store,'note',self.note(root_id=1,base_id=1,field_id=2,observation_id=2,reason='Wrong field'))
    def test_views_are_local_and_query_encoded(self):
        data={'title':'TEST saved view','reporter':'TEST','reason':'Bookmark','tags':[],
              'path':'/evidence-studio','filters':{'view':'measurements','field_id':'1','q':'a&b'}}
        c.save(self.store,'view',data);url=c.entries(self.path,'view')[0]['url'];self.assertIn('q=a%26b',url)
        with self.assertRaises(ValueError):c.save(self.store,'view',{**data,'path':'https://example.invalid'})
    def test_case_and_note_frozen_in_bundle(self):
        c.save(self.store,'case',self.case());c.save(self.store,'note',self.note())
        first=capture_review(self.path,1);ctx=first['payload']['evidence_studio'];self.assertEqual(len(ctx['case_history']),1);self.assertEqual(len(ctx['notebook_history']),1)
        c.save(self.store,'note',self.note(root_id=1,base_id=1,content='Later note',reason='Changed'))
        self.assertEqual(first['payload']['evidence_studio']['notebook_history'][0]['payload']['data']['content'],'TEST only')
    def test_new_record_types_searchable(self):
        m.save(self.store,self.reading());c.save(self.store,'case',self.case());c.save(self.store,'note',self.note())
        self.assertEqual(search(self.path,{'kind':'measurement'})['total'],1)
        self.assertEqual(search(self.path,{'kind':'field_note','q':'TEST'})['total'],1)

class EvidenceLinkTests(StudioFixture):
    def link_data(self,kind='measurement',target_id=1,**changes):
        with readonly(self.path) as db:source=l.target(db,kind,target_id)
        return dict({'field_id':1,'observation_id':1,'kind':kind,'target_id':target_id,'target_sha256':source['target_sha256'],
                     'state':'active','reporter':'TEST farmer','reason':'Explicitly relevant to this observation'},**changes)
    def test_link_freezes_source_and_hash(self):
        m.save(self.store,self.reading());l.save(self.store,self.link_data());row=l.entries(self.path)[0]
        self.assertEqual(row['reference_status'],'matches');self.assertEqual(row['payload']['data']['record']['payload']['data']['value'],'12.5')
    def test_preview_hash_required(self):
        m.save(self.store,self.reading())
        with self.assertRaises(ValueError):l.save(self.store,self.link_data(target_sha256='bad'))
    def test_cross_field_evidence_rejected(self):
        m.save(self.store,self.reading(field_id=2,observation_id=2))
        with self.assertRaises(ValueError):l.save(self.store,self.link_data())
    def test_test_measurement_cannot_link_as_farm_evidence(self):
        m.save(self.store,self.reading(source='test_measurement'))
        with readonly(self.path) as db:
            with self.assertRaises(ValueError):l.target(db,'measurement',1)
    def test_correction_marks_reference_superseded_without_rewrite(self):
        m.save(self.store,self.reading());l.save(self.store,self.link_data());before=l.entries(self.path)[0]['payload']
        m.save(self.store,self.reading(root_id=1,base_id=1,value='14',reason='Re-measured'))
        row=l.entries(self.path)[0];self.assertEqual(row['reference_status'],'superseded');self.assertEqual(row['payload'],before)
    def test_withdrawal_preserves_old_link(self):
        m.save(self.store,self.reading());l.save(self.store,self.link_data())
        l.save(self.store,{'field_id':1,'observation_id':1,'root_id':1,'base_id':1,'state':'withdrawn','reporter':'TEST','reason':'Withdraw reference'})
        rows=l.entries(self.path,{'history':'true'});self.assertEqual(len(rows),2);self.assertEqual(rows[0]['reference_status'],'withdrawn')
    def test_link_capture_is_frozen(self):
        m.save(self.store,self.reading());l.save(self.store,self.link_data());bundle=capture_review(self.path,1)
        self.assertEqual(bundle['payload']['evidence_studio']['evidence_links'][0]['reference_status'],'matches')
        m.save(self.store,self.reading(root_id=1,base_id=1,value='14',reason='Correction'))
        self.assertEqual(bundle['payload']['evidence_studio']['evidence_links'][0]['reference_status'],'matches')
    def test_missing_target_flagged_and_can_withdraw(self):
        m.save(self.store,self.reading());l.save(self.store,self.link_data())
        with self.store.connect() as db:db.execute('DELETE FROM field_measurements')
        self.assertEqual(l.entries(self.path)[0]['reference_status'],'unavailable')
        l.save(self.store,{'field_id':1,'observation_id':1,'root_id':1,'base_id':1,'state':'withdrawn','reporter':'TEST','reason':'Source missing'})
        self.assertEqual(l.entries(self.path)[0]['reference_status'],'withdrawn')
    def test_unknown_link_type_rejected(self):
        with readonly(self.path) as db:
            with self.assertRaises(ValueError):l.target(db,'arbitrary_table',1)
    def test_quality_keeps_tests_out_of_farm_count(self):
        m.save(self.store,self.reading());m.save(self.store,self.reading(source='test_measurement',value='1'))
        data=studio_reports.quality(self.path);self.assertEqual(data['farm_measurement_count'],1);self.assertEqual(data['test_measurement_count'],1)
        self.assertEqual(len(data['latest_measurement_coverage']),1)

    def test_changed_mutable_source_is_flagged_without_replacing_snapshot(self):
        from nexus.farm_app.advisers import initialize_advisers
        initialize_advisers(self.store)
        with self.store.connect() as db:
            db.execute("INSERT INTO adviser_reviews(observation_id,adviser_name,adviser_role,reviewed_at,findings,assessment,basis,next_step,recorded_at) VALUES(1,'TEST','TEST',?,'Original TEST findings','unconfirmed','TEST basis','TEST next',?)",(self.when,self.when))
        l.save(self.store,self.link_data(kind='adviser'))
        with self.store.connect() as db:db.execute("UPDATE adviser_reviews SET findings='Changed TEST findings' WHERE id=1")
        row=l.entries(self.path)[0];self.assertEqual(row['reference_status'],'changed');self.assertEqual(row['payload']['data']['record']['findings'],'Original TEST findings')
