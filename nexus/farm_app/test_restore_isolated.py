"""Recovery proof using disposable data and the actual authenticated launcher."""
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from nexus.farm_app import test_protected_inspections as fixtures
from nexus.farm_app.backup import backup_database
from nexus.farm_app.restore_isolated import restore
from nexus.farm_app.workspace_access import read_inspections


def launch_args(database, port):
    return [sys.executable, '-u', '-m', 'nexus.farm_app.operations', '--authenticated',
            '--database', str(database), '--port', str(port)]


class IsolatedRestoreTests(unittest.TestCase):
    def test_restored_launcher_preserves_exact_history_and_access(self):
        fixture = fixtures.ProtectedInspectionTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        oid, other = fixture.fixture()
        token, _ = fixture.sessions['owner']
        initial = fixture.data(oid, intent='new', target_revision=None, submission_id=str(uuid4()))
        first = fixture.change(**initial)
        original = read_inspections(fixture.path, token, 1, oid)['history'][0]
        correction = fixture.data(oid, intent='correct', supersedes_id=first['id'],
                                  target_revision=original['content_sha256'], submission_id=str(uuid4()),
                                  plants_affected=0, reason='Demo correction')
        second = fixture.change(**correction)
        history = read_inspections(fixture.path, token, 1, oid)['history']
        backup, _ = backup_database(fixture.path, Path(fixture.temp.name) / 'recovery-backups')
        original_sha = hashlib.sha256(fixture.path.read_bytes()).digest()
        backup_sha = hashlib.sha256(backup.read_bytes()).digest()
        isolated = Path(fixture.temp.name) / 'restored'
        database, counts = restore(backup, isolated)
        self.assertEqual(counts, {'farms':2,'fields':2,'observations':2,'field_inspections':2})
        with self.assertRaises(FileExistsError):
            restore(backup, isolated)
        self.assertTrue(database.is_file())
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1',0))
            port = reserve.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        with tempfile.TemporaryFile(mode='w+b') as log:
            process = subprocess.Popen(launch_args(database, port), stdout=log, stderr=log)
            try:
                deadline = time.monotonic()+15
                while True:
                    try:
                        with urlopen(base+'/', timeout=.5) as response:
                            self.assertEqual(response.status,200)
                            break
                    except (OSError, URLError):
                        if process.poll() is not None or time.monotonic()>=deadline:
                            log.seek(0)
                            self.fail(log.read().decode(errors='replace'))
                        time.sleep(.05)

                def request(path, cookie=None, data=None, csrf=None):
                    headers = {'Origin':base, 'Content-Type':'application/json'}
                    if cookie:
                        headers['Cookie']=cookie
                    if csrf:
                        headers['X-Nexus-CSRF']=csrf
                    return urlopen(Request(base+path, headers=headers,
                                           data=json.dumps(data).encode() if data is not None else None), timeout=5)

                def sign_in(name):
                    with request('/api/login', data={'username':name,'password':'fixture-'+name+'-password'}) as response:
                        return response.headers['Set-Cookie'].split(';',1)[0], json.load(response)['csrf']

                def denied(path, status, cookie, data=None, csrf=None):
                    with self.assertRaises(HTTPError) as caught:
                        request(path,cookie,data,csrf)
                    self.assertEqual(caught.exception.code,status)
                    caught.exception.close()

                route = f'/api/field-inspections?farm_id=1&observation_id={oid}'
                denied(route,401,'nexus_session='+token)
                owner, csrf = sign_in('owner')
                viewer, _ = sign_in('viewer')
                for cookie, can_write in ((owner, True), (viewer, False)):
                    with request('/field-inspections',cookie) as response:
                        self.assertIn(b'Saved inspection history',response.read())
                    with request(route,cookie) as response:
                        restored = json.load(response)
                    self.assertEqual(restored['history'],history)
                    self.assertEqual(restored['can_write'],can_write)
                with request('/api/workspace?farm_id=1',owner) as response:
                    workspace=json.load(response)
                self.assertEqual([(f['id'],f['role']) for f in workspace['farms']],[(1,'owner')])
                self.assertEqual([field['id'] for field in workspace['fields']],[1])
                self.assertEqual([row['id'] for row in workspace['observations']],[oid])
                denied(f'/api/field-inspections?farm_id=1&observation_id={other}',403,owner)
                denied('/api/finance',404,owner)
                with request('/api/field-inspections',owner,correction,csrf) as response:
                    self.assertEqual(json.load(response),{'id':second['id'],'reused':True})
                with request(route,owner) as response:
                    self.assertEqual(json.load(response)['history'],history)
                if os.environ.get('NEXUS_RESTORE_BROWSER') == '1':
                    subprocess.run(
                        ['node', str(Path(__file__).with_name('smoke_inspection_browser.cjs'))],
                        input=json.dumps({'url':base,'observation':oid,'restoredHistory':history}),
                        text=True, check=True, timeout=90,
                    )
                occupied = subprocess.run(launch_args(database,port), capture_output=True, text=True, timeout=10)
                self.assertNotEqual(occupied.returncode,0)
                self.assertIn('already in use or reserved',occupied.stderr)
                self.assertIn('Get-NetTCPConnection',occupied.stderr)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        self.assertEqual(hashlib.sha256(fixture.path.read_bytes()).digest(),original_sha)
        self.assertEqual(hashlib.sha256(backup.read_bytes()).digest(),backup_sha)

    def test_incompatible_backup_and_wrong_startup_database_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            unrelated=root/'unrelated.sqlite3'
            with closing(sqlite3.connect(unrelated)) as db:
                db.execute('CREATE TABLE something (id INTEGER)')
            dest=root/'restored'
            with self.assertRaisesRegex(ValueError,'access migrations'):
                restore(unrelated,dest)
            self.assertFalse(dest.exists())
            missing=root/'missing.sqlite3'
            result=subprocess.run(launch_args(missing,8080), capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('database not found',result.stderr)
            self.assertFalse(missing.exists())
            wrong=subprocess.run(launch_args(unrelated,8080), capture_output=True, text=True, timeout=10)
            self.assertNotEqual(wrong.returncode,0)
            self.assertIn('Check the selected database and access migrations',wrong.stderr)
