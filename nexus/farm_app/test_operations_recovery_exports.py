import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
from nexus.farm_app.store import FarmStore
from nexus.farm_app import operations_recovery as r,operations_exports as e,work_orders
from nexus.farm_app.capture_review import capture_review


class RecoveryExportTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.directory=Path(t.name);self.path=self.directory/'farm.db';self.store=FarmStore(self.path)
        self.store.create('farms',{'name':'TEST','location':'Lokoja'});self.store.create('fields',{'farm_id':1,'name':'South','crop':'maize'})
        self.store.create('observations',{'field_id':1,'note':'TEST <script>alert(1)</script>'});work_orders.initialize(self.store)
    def backup(self):return r.backup(self.path,self.directory/'backups')
    def test_backup_covers_extra_tables(self):
        with self.store.connect() as db:db.execute('CREATE TABLE extra_pilot(id INTEGER PRIMARY KEY,note TEXT)');db.execute("INSERT INTO extra_pilot VALUES(1,'TEST')")
        saved=self.backup();self.assertEqual(saved['table_counts']['extra_pilot'],1);self.assertIn('work_orders',saved['table_counts'])
    def test_manifest_hash_and_size_match_backup(self):
        saved=self.backup();manifest=json.loads(Path(saved['manifest']).read_text())
        self.assertEqual(manifest['sha256'],r.file_hash(saved['backup']));self.assertEqual(r.verify(saved['backup'])['manifest_status'],'matches')
    def test_changed_manifest_is_rejected(self):
        saved=self.backup();p=Path(saved['manifest']);data=json.loads(p.read_text());data['sha256']='bad';p.write_text(json.dumps(data))
        self.assertFalse(r.verify(saved['backup'])['ok'])
    def test_restore_preview_does_not_create_file(self):
        saved=self.backup();target=self.directory/'copy.db';result=r.restore(saved['backup'],target)
        self.assertEqual(result['mode'],'dry_run');self.assertFalse(target.exists())
    def test_restore_new_copy_all_records(self):
        saved=self.backup();target=self.directory/'copy.db';result=r.restore(saved['backup'],target,True)
        self.assertTrue(result['verified']);self.assertEqual(r.inspect(target)['table_counts'],r.inspect(self.path)['table_counts'])
    def test_restore_never_overwrites_existing_database(self):
        saved=self.backup();before=self.path.read_bytes()
        with self.assertRaises(ValueError):r.restore(saved['backup'],self.path,True)
        self.assertEqual(self.path.read_bytes(),before)
    def test_failed_backup_checks_do_not_create_restored_file(self):
        saved=self.backup();p=Path(saved['manifest']);data=json.loads(p.read_text());data['sha256']='bad';p.write_text(json.dumps(data));target=self.directory/'copy.db'
        with self.assertRaises(ValueError):r.restore(saved['backup'],target,True)
        self.assertFalse(target.exists())
    def test_restore_rejects_existing_sqlite_sidecars(self):
        saved=self.backup();target=self.directory/'copy.db';Path(str(target)+'-wal').write_bytes(b'TEST')
        with self.assertRaises(ValueError):r.restore(saved['backup'],target,True)
    def test_missing_source_does_not_create_database(self):
        missing=self.directory/'missing.db'
        with self.assertRaises(ValueError):r.inspect(missing)
        self.assertFalse(missing.exists())
    def test_non_nexus_database_rejected(self):
        import sqlite3
        p=self.directory/'other.db';sqlite3.connect(p).close()
        with self.assertRaises(ValueError):r.inspect(p)
    def test_doctor_detects_frozen_hash_corruption(self):
        capture_review(self.path,1);self.assertTrue(r.doctor(self.path)['ok'])
        with self.store.connect() as db:db.execute("UPDATE decision_review_bundles SET content_sha256='bad'")
        self.assertFalse(r.doctor(self.path)['ok'])
    def test_doctor_detects_foreign_key_errors(self):
        import sqlite3
        db=sqlite3.connect(self.path)
        try:db.execute("INSERT INTO fields(farm_id,name,crop) VALUES(999,'Orphan','maize')");db.commit()
        finally:db.close()
        self.assertFalse(r.doctor(self.path)['ok'])
    def test_doctor_checks_photo_bytes(self):
        from nexus.farm_app.photos import initialize_photos
        initialize_photos(self.store)
        with self.store.connect() as db:db.execute("INSERT INTO observation_photos(observation_id,caption,image_data,sha256,uploaded_at) VALUES(1,'TEST',?,'bad','2026-10-01T00:00:00+00:00')",(b'TEST',))
        self.assertFalse(r.doctor(self.path)['photo_hash_checks'][0]['matches'])
    def test_doctor_is_readonly(self):
        before=self.path.read_bytes();r.doctor(self.path);self.assertEqual(self.path.read_bytes(),before)
    def test_csv_formula_strings_are_prefixed(self):
        raw=e.csv_bytes([{'note':' =HYPERLINK("bad")','count':19}]).decode('utf-8-sig')
        self.assertIn("' =HYPERLINK",raw);self.assertIn('19',raw)
    def test_json_keeps_original_values(self):
        raw,_=e.export(self.path,'records','json',{'kind':'observation'})
        self.assertEqual(json.loads(raw)['records'][0]['title'],'TEST <script>alert(1)</script>')
    def test_print_html_escapes_reported_content(self):
        raw,_=e.export(self.path,'records','html',{'kind':'observation'});html=raw.decode()
        self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>alert',html)
    def test_portable_export_hashes_match_each_file(self):
        raw=e.portable(self.path,'records',{'kind':'observation'})
        with ZipFile(io.BytesIO(raw)) as zipped:
            manifest=json.loads(zipped.read('manifest.json'))
            for name,digest in manifest['files'].items():self.assertEqual(hashlib.sha256(zipped.read(name)).hexdigest(),digest)
            self.assertEqual(manifest['record_count'],1)
    def test_exports_obey_field_filter(self):
        self.assertEqual(e.dataset(self.path,'records',{'field_id':999}),[])
    def test_invalid_export_format_rejected(self):
        with self.assertRaises(ValueError):e.export(self.path,format='exe')
        with self.assertRaises(ValueError):e.dataset(self.path,kind='arbitrary-table')
    def test_export_source_database_unchanged(self):
        before=self.path.read_bytes();e.portable(self.path);self.assertEqual(self.path.read_bytes(),before)


if __name__=='__main__':unittest.main()
