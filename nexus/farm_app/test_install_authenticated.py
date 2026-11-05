import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from nexus.farm_app import install_authenticated as installer
from nexus.farm_app.store import FarmStore


class AuthenticatedInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        self.project=root/'project';self.release=root/'release'
        package=self.project/'nexus/farm_app';package.mkdir(parents=True)
        (self.project/'nexus/__init__.py').write_text('')
        (package/'__init__.py').write_text('')
        source=Path(__file__).parent
        for name in ('store.py','observations.py','backup.py'):
            shutil.copy2(source/name,package/name)
        self.db=self.project/'nexus-farm.sqlite3'
        store=FarmStore(self.db)
        with store.connect() as db:db.execute("INSERT INTO farms VALUES (1,'Fixture only','Fixture')")
        target=self.release/'nexus/farm_app/new_fixture.py'
        target.parent.mkdir(parents=True)
        target.write_text('VALUE = 1\n')
        self.file='nexus/farm_app/new_fixture.py'
        self.manifest={'release':'nexus-authenticated-core-v1','files':{self.file:hashlib.sha256(target.read_bytes()).hexdigest()}}
        self.write_manifest()

    def write_manifest(self):
        (self.release/'RELEASE.json').write_text(json.dumps(self.manifest))

    def test_check_only_changes_no_database_or_source(self):
        before=self.db.read_bytes()
        result=installer.install(self.release,self.project,check_only=True)
        self.assertFalse(result['changed'])
        self.assertEqual(before,self.db.read_bytes())
        self.assertFalse((self.project/self.file).exists())

    def test_changed_hash_and_unsafe_path_rejected(self):
        (self.release/self.file).write_text('changed')
        with self.assertRaises(ValueError):installer.install(self.release,self.project,check_only=True)
        self.manifest['files']={'../outside.py':'bad'};self.write_manifest()
        with self.assertRaises(ValueError):installer.install(self.release,self.project,check_only=True)

    def test_install_preserves_database_and_checked_backup(self):
        before=self.db.read_bytes()
        result=installer.install(self.release,self.project)
        self.assertTrue(result['changed'])
        self.assertEqual((self.project/self.file).read_text(),'VALUE = 1\n')
        self.assertEqual(self.db.read_bytes(),before)
        self.assertEqual(len(list((self.project/'backups').glob('*.sqlite3'))),1)

    def test_copy_failure_restores_original_source(self):
        target=self.project/self.file;target.write_text('OLD = 1\n')
        with patch.object(installer.os,'replace',side_effect=OSError('fixture copy failure')):
            with self.assertRaises(OSError):installer.install(self.release,self.project)
        self.assertEqual(target.read_text(),'OLD = 1\n')
        self.assertEqual(list(target.parent.glob('*.nexus-install')),[])


if __name__=='__main__':
    unittest.main()
