import hashlib
import io
import json
from zipfile import ZipFile
from nexus.farm_app.studio_test_support import StudioFixture
from nexus.farm_app import studio_reports as r,studio_backups as b,field_measurements as m,studio_cases as c,studio_links as l
from nexus.farm_app.capture_review import capture_review
from nexus.farm_app.seasons import initialize_seasons,save_season
from nexus.farm_app.finance import initialize_finance
from nexus.farm_app.operations_recovery import doctor
from nexus.farm_app.operations_common import readonly
from nexus.farm_app import evidence_studio

class StudioReportsTests(StudioFixture):
    def setup_cash(self):
        initialize_seasons(self.store);initialize_finance(self.store)
        for fid in (1,2):save_season(self.store,{'field_id':fid,'name':'TEST season '+str(fid),'crop':'maize','variety':'Unknown','area_ha':1,'planting_date':'2026-04-01','expected_harvest_date':'2026-10-03'})
        with self.store.connect() as db:
            for sid,kind,date,amount in ((1,'expense','2026-09-01',10000),(1,'sale','2026-10-01',25000),(1,'expense','2026-10-15',5000),(2,'sale','2026-10-01',99999)):
                db.execute('INSERT INTO season_transactions(season_id,kind,occurred_at,description,amount_kobo,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(sid,kind,date,'TEST '+kind,amount,self.when,self.when))
    def test_cash_date_window_and_net_not_profit(self):
        self.setup_cash();data=r.finance(self.path,{'field_id':1,'from':'2026-10-01','to':'2026-10-31'})
        self.assertEqual(data['totals'],{'sales_kobo':25000,'expenses_kobo':5000,'net_cash_kobo':20000});self.assertIn('not profit',data['limitations'][0])
    def test_cash_season_and_entry_kind_filters(self):
        self.setup_cash();data=r.finance(self.path,{'season_id':1,'kind':'expense'})
        self.assertEqual(len(data['entries']),2);self.assertEqual(data['totals']['sales_kobo'],0)
    def test_cash_description_filter(self):
        self.setup_cash();self.assertEqual(len(r.finance(self.path,{'q':'sale','field_id':1})['entries']),1)
    def test_cash_months_not_filled_with_inferred_zeroes(self):
        self.setup_cash();months=r.finance(self.path,{'field_id':1})['months'];self.assertEqual([v['month'] for v in months],['2026-09','2026-10'])
    def test_invalid_cash_date_range_rejected(self):
        self.setup_cash()
        with self.assertRaises(ValueError):r.finance(self.path,{'from':'2026-11-02','to':'2026-10-01'})
    def test_bundle_diff_flags_added_measurements(self):
        first=capture_review(self.path,1);m.save(self.store,self.reading());second=capture_review(self.path,1)
        data=r.compare(self.path,first['id'],second['id'],'evidence_studio')
        self.assertTrue(any('measurement_history' in row['path'] for row in data['differences']))
        self.assertEqual(first['payload']['evidence_studio']['measurement_history'],[])
    def test_identical_bundle_and_cross_observation_rejected(self):
        first=capture_review(self.path,1);second=capture_review(self.path,2)
        with self.assertRaises(ValueError):r.compare(self.path,first['id'],first['id'])
        with self.assertRaises(ValueError):r.compare(self.path,first['id'],second['id'])
    def test_bundle_hash_mismatch_prevents_comparison(self):
        first=capture_review(self.path,1);m.save(self.store,self.reading());second=capture_review(self.path,1)
        with self.store.connect() as db:db.execute("UPDATE decision_review_bundles SET content_sha256='bad' WHERE id=?",(second['id'],))
        with self.assertRaises(ValueError):r.compare(self.path,first['id'],second['id'])
    def test_quality_unknown_queue_and_latest_coverage(self):
        m.save(self.store,self.reading(value='',unknown_reason='No ruler available'));c.save(self.store,'case',self.case())
        data=r.quality(self.path);self.assertEqual(len(data['unknown_measurements']),1);self.assertEqual(len(data['case_review_queue']),1)
        self.assertIsNone(data['latest_measurement_coverage'][0]['value'])
    def test_doctor_recognises_new_ledger_hash_failure(self):
        m.save(self.store,self.reading());self.assertTrue(doctor(self.path)['ok'])
        with self.store.connect() as db:db.execute("UPDATE field_measurements SET content_sha256='bad'")
        self.assertFalse(doctor(self.path)['ok'])
    def test_new_exports_keep_source_labels(self):
        m.save(self.store,self.reading(source='test_measurement'))
        raw,typ,filename=evidence_studio.get(self.store,'export',{'dataset':'measurements','format':'csv','include_tests':'true'})
        self.assertIn(b'test_measurement',raw);self.assertTrue(filename.endswith('.csv'))
    def test_bundle_render_escapes_studio_notes(self):
        from nexus.farm_app.review_bundles import bundle_page
        c.save(self.store,'note',self.note(content='<script>bad()</script>'));html=bundle_page(capture_review(self.path,1))
        self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>bad()',html)

class StudioBackupTests(StudioFixture):
    def create(self):return b.create(self.path,True)
    def test_catalogue_and_verify_new_backup(self):
        saved=self.create();files=b.catalogue(self.path)['backups'];self.assertEqual(len(files),1)
        self.assertTrue(files[0]['manifest_available']);self.assertTrue(b.verify(self.path,files[0]['name'])['ok'])
    def test_backup_creation_requires_explicit_request(self):
        with self.assertRaises(ValueError):b.create(self.path,False)
    def test_backup_paths_cannot_escape_catalogue(self):
        for name in ('../farm.sqlite3','..\\farm.sqlite3','/tmp/farm.sqlite3','other.txt'):
            with self.subTest(name=name),self.assertRaises(ValueError):b.selected(self.path,name)
    def test_portable_backup_contains_database_manifest_and_checks(self):
        saved=self.create();name=b.catalogue(self.path)['backups'][0]['name'];raw=b.portable(self.path,name)
        with ZipFile(io.BytesIO(raw)) as zipped:
            self.assertIn(name,zipped.namelist());self.assertIn(name+'.manifest.json',zipped.namelist());self.assertTrue(json.loads(zipped.read('CHECKS.json'))['ok'])
    def test_recovery_copy_preserves_running_database(self):
        saved=self.create();name=b.catalogue(self.path)['backups'][0]['name'];before=self.path.read_bytes();result=b.restore_copy(self.path,name,True)
        self.assertTrue(result['verified']);self.assertEqual(self.path.read_bytes(),before);self.assertNotEqual(result['destination'],str(self.path))
    def test_recovery_copy_needs_confirmation(self):
        self.create();name=b.catalogue(self.path)['backups'][0]['name']
        with self.assertRaises(ValueError):b.restore_copy(self.path,name,False)
    def test_manifest_mismatch_blocks_download_and_recovery(self):
        saved=self.create();from pathlib import Path
        manifest=Path(saved['manifest']);data=json.loads(manifest.read_text());data['sha256']='bad';manifest.write_text(json.dumps(data));name=b.catalogue(self.path)['backups'][0]['name']
        with self.assertRaises(ValueError):b.portable(self.path,name)
        with self.assertRaises(ValueError):b.restore_copy(self.path,name,True)
