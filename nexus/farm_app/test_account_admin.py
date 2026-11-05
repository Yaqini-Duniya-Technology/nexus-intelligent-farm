import json
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from unittest.mock import patch
from nexus.farm_app import account_admin as admin, local_accounts as accounts, scoped_access as access, deployment_controls as controls, account_pilot
from nexus.farm_app.store import FarmStore


class AdministrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.path=self.root/'fixture.db';self.store=FarmStore(self.path)
        with self.store.connect() as db:db.execute("INSERT INTO farms VALUES (1,'Fixture','Fixture')")
        controls.migrate(self.path,self.root/'backups')
        self.owner=accounts.create(self.path,'owner','fixture-owner-password');self.viewer=accounts.create(self.path,'viewer','fixture-viewer-password')
        accounts.grant(self.path,self.owner,1,'owner');accounts.grant(self.path,self.viewer,1,'viewer')
        admin.bootstrap(self.path,self.owner)
        self.token,self.csrf=access.login(self.path,'owner','fixture-owner-password')
        self.vtoken,self.vcsrf=access.login(self.path,'viewer','fixture-viewer-password')

    def change(self,**data):return admin.change(self.path,self.token,self.csrf,data)

    def test_admin_scope_secret_redaction_and_search(self):
        with self.assertRaises(access.AccessError):admin.state(self.path,self.vtoken)
        state=admin.state(self.path,self.token,'view','enabled')
        self.assertEqual([a['username'] for a in state['accounts']],['viewer'])
        raw=json.dumps(state)
        for secret in ('password_hash',self.token,self.csrf,'fixture-owner-password'):self.assertNotIn(secret,raw)
        self.assertTrue(state['accounts'][0]['last_sign_in'])
        with self.assertRaises(ValueError):admin.bootstrap(self.path,self.viewer)

    def test_create_assign_revoke_and_disable(self):
        new=self.change(operation='create',username='worker-example',password='fixture-worker-password')['account_id']
        self.change(operation='grant',account_id=new,farm_id=1,role='editor')
        token,csrf=access.login(self.path,'worker-example','fixture-worker-password')
        access.note(self.path,token,csrf,1,'Fixture note')
        self.change(operation='remove',account_id=new,farm_id=1)
        with self.assertRaises(access.AccessError):access.read(self.path,token,1)
        self.change(operation='grant',account_id=new,farm_id=1,role='viewer')
        self.change(operation='status',account_id=new,disabled=True)
        with self.assertRaises(access.AccessError):access.read(self.path,token)
        self.change(operation='status',account_id=new,disabled=False)
        with self.assertRaises(access.AccessError):access.read(self.path,token)

    def test_last_owner_and_admin_protected(self):
        for data in [dict(operation='remove',account_id=self.owner,farm_id=1),dict(operation='grant',account_id=self.owner,farm_id=1,role='viewer'),dict(operation='status',account_id=self.owner,disabled=True)]:
            with self.assertRaises(ValueError):self.change(**data)
        self.change(operation='grant',account_id=self.viewer,farm_id=1,role='owner')
        with self.assertRaises(ValueError):self.change(operation='status',account_id=self.owner,disabled=True)

    def test_viewer_and_csrf_cannot_administer(self):
        for token,csrf in [(self.vtoken,self.vcsrf),(self.token,''),(self.token,'wrong')]:
            with self.assertRaises(access.AccessError):admin.change(self.path,token,csrf,dict(operation='create',username='forbidden',password='fixture-new-password'))
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM nexus_accounts').fetchone()[0],2)

    def test_reset_single_use_and_session_revocation(self):
        output=self.root/'private-reset.txt'
        admin.issue_reset(self.path,self.owner,self.viewer,'Fixture identity check performed',output)
        token=output.read_text().strip()
        state=admin.state(self.path,self.token)
        self.assertNotIn(token,json.dumps(state));self.assertNotIn('Fixture identity check performed',json.dumps(state))
        admin.redeem(self.path,token,'fixture-new-password')
        with self.assertRaises(access.AccessError):access.read(self.path,self.vtoken)
        with self.assertRaises(access.AccessError):access.login(self.path,'viewer','fixture-viewer-password')
        fresh,_=access.login(self.path,'viewer','fixture-new-password');self.assertEqual(access.read(self.path,fresh)['username'],'viewer')
        with self.assertRaises(access.AccessError):admin.redeem(self.path,token,'fixture-other-password')
        kinds=[e['category'] for e in admin.state(self.path,self.token)['events']]
        self.assertIn('password_reset_issued',kinds);self.assertIn('password_reset_completed',kinds)

    def test_reset_denials_expiration_no_overwrite(self):
        output=self.root/'private-reset.txt'
        with self.assertRaises(access.AccessError):admin.issue_reset(self.path,self.viewer,self.owner,'Fixture verified identity',output)
        self.assertFalse(output.exists())
        admin.issue_reset(self.path,self.owner,self.viewer,'Fixture verified identity',output)
        old=output.read_bytes()
        with self.assertRaises(FileExistsError):admin.issue_reset(self.path,self.owner,self.viewer,'Fixture verified identity',output)
        self.assertEqual(output.read_bytes(),old)
        with self.store.connect() as db:db.execute('UPDATE nexus_password_resets SET expires_at=0')
        with self.assertRaises(access.AccessError):admin.redeem(self.path,old.decode().strip(),'fixture-new-password')

    def test_audit_is_append_only_and_atomic(self):
        with self.store.connect() as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM nexus_security_events')
            with self.assertRaises(sqlite3.IntegrityError):db.execute("UPDATE nexus_security_events SET summary='changed'")
            db.execute("CREATE TRIGGER fixture_audit_failure BEFORE INSERT ON nexus_security_events WHEN NEW.category='account_create' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.change(operation='create',username='rollback',password='fixture-new-password')
        with self.store.connect() as db:self.assertIsNone(db.execute("SELECT 1 FROM nexus_accounts WHERE username='rollback'").fetchone())

    def test_migration_restoration_keeps_legacy_and_prior_ledger(self):
        # The checked backup predates migration 3 and retains original farm records.
        backup=sorted((self.root/'backups').glob('*.sqlite3'))[0]
        restored=self.root/'restored.db'
        with closing(sqlite3.connect(backup)) as source,closing(sqlite3.connect(restored)) as target:source.backup(target)
        with closing(sqlite3.connect(restored)) as db:
            self.assertEqual(db.execute('SELECT name FROM farms').fetchone()[0],'Fixture')
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='nexus_platform_admins'").fetchone())
        self.assertEqual(controls.migrate(restored,self.root/'restored-backups')['applied'],[1,2,3])

    def test_upgrade_existing_v2_preserves_accounts_sessions_and_backup(self):
        path=self.root/'old-v2.db';store=FarmStore(path)
        with store.connect() as db:db.execute("INSERT INTO farms VALUES (1,'Legacy fixture','Fixture')")
        with patch.object(controls,'MIGRATIONS',controls.MIGRATIONS[:2]):controls.migrate(path,self.root/'old-backups')
        encoded=accounts.password_hash('fixture-legacy-password')
        with store.connect() as db:
            db.execute("INSERT INTO nexus_accounts VALUES (1,'legacy',?,0,'2026-01-01T00:00:00+00:00')",(encoded,))
            db.execute("INSERT INTO nexus_sessions VALUES ('fixture-hash',1,'fixture-csrf',1,1,2)")
        result=controls.migrate(path,self.root/'old-backups')
        self.assertEqual(result['applied'],[3])
        with store.connect() as db:
            self.assertEqual(db.execute('SELECT password_hash FROM nexus_accounts').fetchone()[0],encoded)
            self.assertEqual(db.execute('SELECT count(*) FROM nexus_sessions').fetchone()[0],1)
        with closing(sqlite3.connect(result['backup'])) as db:
            self.assertEqual(db.execute('SELECT max(version) FROM nexus_schema_migrations').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT password_hash FROM nexus_accounts').fetchone()[0],encoded)

    def test_admin_http_and_recovery(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),account_pilot.make_handler(self.path));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            base=f'http://127.0.0.1:{server.server_port}'
            def call(path,data=None,token=None,csrf=None):
                headers={'Origin':base,'Content-Type':'application/json'}
                if token:headers['Cookie']='nexus_session='+token
                if csrf:headers['X-Nexus-CSRF']=csrf
                return urlopen(Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers))
            for token in (None,self.vtoken):
                with self.assertRaises(HTTPError) as error:call('/admin',token=token)
                self.assertIn(error.exception.code,(401,403))
            with call('/admin',token=self.token) as r:self.assertIn(b'NEXUS account administration',r.read())
            with call('/api/admin',token=self.token) as r:self.assertNotIn(b'password_hash',r.read())
            with self.assertRaises(HTTPError) as error:call('/api/admin',dict(operation='status',account_id=self.viewer,disabled=True),self.vtoken,self.vcsrf)
            self.assertEqual(error.exception.code,403)
            with call('/api/admin',dict(operation='status',account_id=self.viewer,disabled=True),self.token,self.csrf):pass
            with self.assertRaises(HTTPError):call('/api/session',token=self.vtoken)
            with call('/api/admin',dict(operation='status',account_id=self.viewer,disabled=False),self.token,self.csrf):pass
            fresh,_=access.login(self.path,'viewer','fixture-viewer-password')
            output=self.root/'http-reset.txt'
            admin.issue_reset(self.path,self.owner,self.viewer,'Fixture independent verification',output)
            with call('/api/reset',dict(token=output.read_text().strip(),password='fixture-recovered-password')) as r:self.assertIn('Password changed',json.load(r)['message'])
            with self.assertRaises(HTTPError):call('/api/session',token=fresh)
            self.assertIn('administration_denied',[e['category'] for e in admin.state(self.path,self.token)['events']])
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
