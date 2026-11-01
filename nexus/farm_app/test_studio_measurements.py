import json
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from nexus.farm_app.studio_test_support import StudioFixture
from nexus.farm_app import field_measurements as m,studio_ledger as ledger
from nexus.farm_app.operations_common import canonical,digest
from nexus.farm_app.capture_review import capture_review

class MeasurementTests(StudioFixture):
    def test_save_persists_exact_numeric_string_and_unit(self):
        m.save(self.store,self.reading());row=m.readings(self.path)[0]
        self.assertEqual(row['payload']['data']['value'],'12.5');self.assertEqual(row['payload']['data']['unit'],'cm')
    def test_unknown_and_zero_are_distinct(self):
        m.save(self.store,self.reading(value='',unknown_reason='Not measured'));m.save(self.store,self.reading(value='0',reason='Measured zero'))
        self.assertEqual({r['payload']['data']['value'] for r in m.readings(self.path)},{None,'0'})
    def test_unknown_requires_reason(self):
        with self.assertRaises(ValueError):m.save(self.store,self.reading(value=''))
    def test_metric_and_unit_validation(self):
        for data in ({'metric':'made_up'},{'unit':'mm'},{'metric':[]}):
            with self.subTest(data=data),self.assertRaises(ValueError):m.save(self.store,self.reading(**data))
    def test_nonfinite_and_boolean_rejected(self):
        for value in ('NaN','Infinity',True,float('inf')):
            with self.subTest(value=value),self.assertRaises(ValueError):m.save(self.store,self.reading(value=value))
    def test_bounds_and_precision_rejected(self):
        for value in ('-1','10001','1.1234567'):
            with self.subTest(value=value),self.assertRaises(ValueError):m.save(self.store,self.reading(value=value))
    def test_negative_temperature_is_a_valid_record(self):
        m.save(self.store,self.reading(metric='air_temperature',unit='C',value='-2'))
        self.assertEqual(m.readings(self.path)[0]['payload']['data']['value'],'-2')
    def test_future_or_naive_time_rejected(self):
        for value in ('2026-10-01T12:00:00',(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()):
            with self.subTest(value=value),self.assertRaises(ValueError):m.save(self.store,self.reading(observed_at=value))
    def test_required_method_instrument_reporter(self):
        for key in ('method','instrument','reporter','area','notes','reason'):
            with self.subTest(key=key),self.assertRaises(ValueError):m.save(self.store,self.reading(**{key:''}))
    def test_cross_field_observation_rejected(self):
        with self.assertRaises(ValueError):m.save(self.store,self.reading(observation_id=2))
    def test_identical_save_reused(self):
        a=m.save(self.store,self.reading());b=m.save(self.store,self.reading());self.assertEqual(a['id'],b['id']);self.assertTrue(b['reused'])
    def test_correction_preserves_original_and_latest_filter(self):
        m.save(self.store,self.reading());m.save(self.store,self.reading(root_id=1,base_id=1,value='13',reason='Ruler correction'))
        self.assertEqual(m.readings(self.path)[0]['payload']['data']['value'],'13')
        rows=m.readings(self.path,{'history':'true'});self.assertEqual(len(rows),2);self.assertEqual(rows[1]['payload']['data']['value'],'12.5')
    def test_stale_correction_rejected(self):
        m.save(self.store,self.reading());m.save(self.store,self.reading(root_id=1,base_id=1,value='13',reason='Correction'))
        with self.assertRaises(ValueError):m.save(self.store,self.reading(root_id=1,base_id=1,value='14',reason='Stale form'))
    def test_test_source_not_relabelled_or_shown_by_default(self):
        m.save(self.store,self.reading(source='test_measurement'));self.assertEqual(m.readings(self.path),[])
        self.assertEqual(len(m.readings(self.path,{'include_tests':'true'})),1)
        with self.assertRaises(ValueError):m.save(self.store,self.reading(root_id=1,base_id=1,source='farmer_measurement',reason='Relabel'))
    def test_capture_excludes_tests_and_freezes_history(self):
        m.save(self.store,self.reading());m.save(self.store,self.reading(source='test_measurement'))
        first=capture_review(self.path,1);ctx=first['payload']['evidence_studio']
        self.assertEqual(len(ctx['measurement_history']),1);self.assertEqual(ctx['excluded_test_measurements'],1)
        m.save(self.store,self.reading(root_id=1,base_id=1,value='13',reason='Later correction'))
        second=capture_review(self.path,1);self.assertNotEqual(first['id'],second['id']);self.assertEqual(len(first['payload']['evidence_studio']['measurement_history']),1)
    def test_field_only_measurement_not_silently_assigned(self):
        m.save(self.store,self.reading(observation_id=None));self.assertEqual(capture_review(self.path,1)['payload']['evidence_studio']['measurement_history'],[])
    def test_corrupt_hash_rejected(self):
        m.save(self.store,self.reading())
        with self.store.connect() as db:db.execute("UPDATE field_measurements SET content_sha256='bad'")
        with self.assertRaises(ValueError):m.readings(self.path)
    def test_recomputed_hash_invalid_unit_still_rejected(self):
        m.save(self.store,self.reading())
        with self.store.connect() as db:
            payload=json.loads(db.execute('SELECT payload FROM field_measurements').fetchone()[0]);payload['data']['unit']='wrong'
            db.execute('UPDATE field_measurements SET payload=?,content_sha256=?',(canonical(payload),digest(payload)))
        with self.assertRaises(ValueError):m.readings(self.path)

class MeasurementImportTests(StudioFixture):
    def test_template_has_named_columns(self):
        self.assertEqual(m.template().decode('utf-8-sig').strip(),','.join(m.COLUMNS))
    def test_preview_saves_no_measurements(self):
        preview=self.preview();self.assertTrue(preview['can_commit']);self.assertEqual(m.readings(self.path),[])
    def test_commit_persists_and_second_commit_reuses(self):
        preview=self.preview();a=self.commit(preview);b=self.commit(preview)
        self.assertEqual(a['record_ids'],b['record_ids']);self.assertTrue(b['reused']);self.assertEqual(len(m.readings(self.path)),1)
    def test_invalid_header_rejected(self):
        with self.assertRaises(ValueError):self.preview(csv_text='bad,value\na,2\n')
    def test_empty_rows_rejected(self):
        with self.assertRaises(ValueError):self.preview(csv_text=m.template().decode('utf-8-sig'))
    def test_bad_row_prevents_all_commit(self):
        rows=[self.reading(),self.reading(value='NaN')];preview=self.preview(csv_text=self.csv(rows))
        self.assertFalse(preview['can_commit']);self.assertEqual(preview['errors'][0]['row'],3);self.assertEqual(m.readings(self.path),[])
    def test_duplicate_rows_counted_and_reused(self):
        preview=self.preview(csv_text=self.csv([self.reading(),self.reading()]));self.assertEqual(preview['duplicate_rows'],1)
        result=self.commit(preview);self.assertEqual(result['inserted'],1);self.assertEqual(result['reused_rows'],1)
    def test_existing_manual_reading_reused_by_import(self):
        m.save(self.store,self.reading());preview=self.preview();self.assertEqual(preview['new_rows'],0)
        self.assertEqual(self.commit(preview)['inserted'],0);self.assertEqual(len(m.readings(self.path)),1)
    def test_confirmation_and_reviewer_required(self):
        preview=self.preview()
        for changes in ({'confirm':False},{'reviewer':''},{'preview_sha256':'bad'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.commit(preview,**changes)
        self.assertEqual(m.readings(self.path),[])
    def test_changed_field_rejects_commit(self):
        preview=self.preview()
        with self.store.connect() as db:db.execute("UPDATE fields SET name='Edited field' WHERE id=1")
        with self.assertRaises(ValueError):self.commit(preview)
    def test_preview_size_and_row_limit(self):
        with self.assertRaises(ValueError):self.preview(csv_text='x'*200001)
        with self.assertRaises(ValueError):self.preview(csv_text=self.csv([self.reading()]*501))
    def test_database_failure_rolls_back_whole_import(self):
        preview=self.preview(csv_text=self.csv([self.reading(),self.reading(value='15')]))
        original=m.save_in_transaction;calls=[0]
        def fail(db,data):
            calls[0]+=1
            if calls[0]==2:raise ValueError('TEST simulated second-row failure')
            return original(db,data)
        with patch.object(m,'save_in_transaction',side_effect=fail):
            with self.assertRaises(ValueError):self.commit(preview)
        self.assertEqual(m.readings(self.path),[])
    def test_test_import_stays_test(self):
        preview=self.preview(source='test_measurement');self.commit(preview)
        self.assertEqual(m.readings(self.path),[]);self.assertEqual(m.readings(self.path,{'include_tests':'true'})[0]['payload']['data']['source'],'test_measurement')
    def test_expired_preview_rejected(self):
        preview=self.preview()
        with self.store.connect() as db:db.execute("UPDATE measurement_imports SET created_at='2020-01-01T00:00:00+00:00'")
        with self.assertRaises(ValueError):self.commit(preview)

    def test_expired_preview_can_be_renewed_without_changing_csv(self):
        first=self.preview()
        with self.store.connect() as db:db.execute("UPDATE measurement_imports SET created_at='2020-01-01T00:00:00+00:00'")
        second=self.preview();self.assertNotEqual(first['preview_id'],second['preview_id']);self.assertEqual(self.commit(second)['inserted'],1)

    def test_test_measurements_do_not_enter_default_global_search(self):
        from nexus.farm_app.operations_records import search
        m.save(self.store,self.reading(source='test_measurement'))
        m.save(self.store,self.reading())
        self.assertEqual(search(self.path,{'kind':'measurement'})['total'],1)
