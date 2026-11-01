import argparse
import sqlite3
import subprocess
import sys
import socket
import time
from urllib.request import urlopen
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from nexus.farm_app import deployment_controls as controls, local_accounts as accounts
from nexus.farm_app.store import FarmStore


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'farm.sqlite3'
        self.store = FarmStore(self.path)
        with self.store.connect() as db:
            db.execute("INSERT INTO farms VALUES (1,'Fixture','Fixture')")
            db.execute("INSERT INTO farms VALUES (2,'Other','Fixture')")

    def migrate(self):
        return controls.migrate(self.path, self.root / 'backups')

    def test_backup_precedes_schema_and_repeat_is_noop(self):
        result = self.migrate()
        self.assertEqual(result['applied'], [1, 2])
        with closing(sqlite3.connect(result['backup'])) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM farms').fetchone()[0], 2)
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='nexus_accounts'").fetchone())
        self.assertEqual(self.migrate(), {'applied': [], 'backup': None})
        self.assertEqual(len(list((self.root / 'backups').glob('*.sqlite3'))), 1)

    def test_failed_backup_saves_no_migration(self):
        with patch.object(controls, 'backup_database', side_effect=OSError('fixture')):
            with self.assertRaises(OSError):
                self.migrate()
        with self.store.connect() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='nexus_schema_migrations'").fetchone())

    def test_schema_failure_rolls_back(self):
        with self.store.connect() as db:
            db.execute('CREATE TABLE nexus_accounts(id INTEGER)')
        with self.assertRaises(sqlite3.Error):
            self.migrate()
        with self.store.connect() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='nexus_schema_migrations'").fetchone())
            self.assertEqual(db.execute('SELECT count(*) FROM farms').fetchone()[0], 2)

    def test_tampered_and_future_versions_rejected(self):
        self.migrate()
        with self.store.connect() as db:
            db.execute("UPDATE nexus_schema_migrations SET checksum='bad'")
        with self.assertRaises(ValueError):
            self.migrate()
        with self.store.connect() as db:
            db.execute('UPDATE nexus_schema_migrations SET version=999 WHERE version=1')
        with self.assertRaises(ValueError):
            self.migrate()

    def test_explicit_directory_and_conflict(self):
        parser = argparse.ArgumentParser()
        args = argparse.Namespace(database=None, data_directory=str(self.root / 'data'), initialize_data_directory=True)
        directory = controls.prepare(args, parser)
        self.assertEqual(Path(args.database), directory / 'nexus-farm.sqlite3')
        args.database = str(self.path)
        with self.assertRaises(SystemExit):
            controls.prepare(args, parser)

    def test_missing_directory_does_not_create_empty_workspace(self):
        args = argparse.Namespace(database=None, data_directory=str(self.root / 'missing'))
        with self.assertRaises(SystemExit):
            controls.prepare(args, argparse.ArgumentParser())
        self.assertFalse((self.root / 'missing').exists())

    def test_passwords_and_farm_scope(self):
        self.migrate()
        account = accounts.create(self.path, 'fixture-owner', 'fixture-password-only')
        with self.store.connect() as db:
            encoded = db.execute('SELECT password_hash FROM nexus_accounts').fetchone()[0]
        self.assertNotIn('fixture-password-only', encoded)
        self.assertTrue(accounts.verify('fixture-password-only', encoded))
        self.assertFalse(accounts.verify('wrong', encoded))
        self.assertFalse(accounts.verify('anything', 'invalid'))
        self.assertFalse(accounts.allowed(self.path, account, 1))
        accounts.grant(self.path, account, 1, 'owner')
        self.assertTrue(accounts.allowed(self.path, account, 1, write=True))
        self.assertFalse(accounts.allowed(self.path, account, 2))
        self.assertFalse(accounts.allowed(self.path, True, 1))
        with self.assertRaises(ValueError):
            accounts.grant(self.path, account, 1, 'viewer')
        other = accounts.create(self.path, 'fixture-viewer', 'another-fixture-password')
        accounts.grant(self.path, other, 1, 'viewer')
        self.assertTrue(accounts.allowed(self.path, other, 1))
        self.assertFalse(accounts.allowed(self.path, other, 1, write=True))
        with self.store.connect() as db:
            db.execute('UPDATE nexus_accounts SET disabled=1 WHERE id=?', (other,))
        self.assertFalse(accounts.allowed(self.path, other, 1))

    def test_real_launcher_anchors_storage_and_applies_migration(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        data = self.root / 'new-data'
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen([sys.executable, '-u', '-m', 'nexus.farm_app.operations', '--port', str(port), '--data-directory', str(data), '--initialize-data-directory', '--apply-migrations'], stdout=log, stderr=log)
            try:
                for attempt in range(100):
                    if process.poll() is not None:
                        log.seek(0)
                        self.fail(log.read().decode(errors='replace'))
                    try:
                        with urlopen(f'http://127.0.0.1:{port}/api/ops/meta', timeout=.5) as response:
                            self.assertEqual(response.status, 200)
                            break
                    except OSError:
                        time.sleep(.05)
                else:
                    self.fail('Launcher did not start')
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        with closing(sqlite3.connect(data / 'nexus-farm.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT version FROM nexus_schema_migrations').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM farms').fetchone()[0], 0)
        self.assertEqual(len(list((data / 'backups').glob('*.sqlite3'))), 1)

    def test_accounts_require_migration_and_validate(self):
        with self.assertRaises(ValueError):
            accounts.create(self.path, 'fixture', 'fixture-password-only')
        self.migrate()
        for username, password in [('Bad Name', 'fixture-password-only'), ('fixture', 'short')]:
            with self.assertRaises(ValueError):
                accounts.create(self.path, username, password)
        accounts.create(self.path, 'fixture', 'fixture-password-only')
        with self.assertRaises(ValueError):
            accounts.create(self.path, 'fixture', 'fixture-password-only')
        with self.assertRaises(ValueError):
            accounts.grant(self.path, 1, 999, 'owner')


if __name__ == '__main__':
    unittest.main()
