"""Isolated security regressions; no actual database or farmer credentials."""
import json
import sqlite3
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from nexus.farm_app import test_workspace_access as fixtures
from nexus.farm_app import workspace_access as core, scoped_access as access, authenticated_workspace as web


class ProtectedInspectionTests(unittest.TestCase):
    setUp = fixtures.WorkspacePermissionTests.setUp
    change = fixtures.WorkspacePermissionTests.change
    observation = fixtures.WorkspacePermissionTests.observation

    def fixture(self):
        observed=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
        first=self.change(operation='observation',farm_id=1,field_id=1,note='DEMO sample',observed_at=observed)
        second=self.change('other',operation='observation',farm_id=2,field_id=2,note='PRIVATE OTHER',observed_at=observed)
        return first['observation_id'],second['observation_id']

    def data(self,oid=1,**changes):
        state=core.read_inspections(self.path,self.sessions['owner'][0],1,oid)
        o=state['observations'][0]
        return dict(dict(operation='inspection',farm_id=1,observation_id=oid,observation_hash=o['selection_hash'],
            base_id=state['history'][0]['id'] if state['history'] else None,supersedes_id=None,
            performed_at=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat(),reporter='DEMO reporter',
            area='DEMO south',sampling_method='Selection not established',observation_definition='DEMO visible small cobs',
            findings='DEMO sample only; no diagnosis',reason='Initial fixture',plants_checked=10,plants_affected=2),**changes)

    def test_owner_editor_save_viewer_reads_and_history_survives(self):
        oid,_=self.fixture(); data=self.data(oid)
        first=self.change('editor',**data)
        self.assertEqual(self.change('editor',**data),{'id':first['id'],'reused':True})
        before=core.read_inspections(self.path,self.sessions['viewer'][0],1)['history'][0]
        corrected=self.change(**self.data(oid,supersedes_id=first['id'],plants_affected=1,reason='DEMO recount'))
        state=core.read_inspections(self.path,self.sessions['viewer'][0],1)
        self.assertFalse(state['can_write']);self.assertEqual(state['history'][1],before)
        self.assertNotEqual(first['id'],corrected['id'])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM task_actions').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT status FROM tasks WHERE observation_id=?',(oid,)).fetchone()[0],'pending')
            self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())

    def test_cross_farm_read_write_and_correction_denied(self):
        oid,other=self.fixture();data=self.data(oid)
        for farm,obs in [(2,None),(1,other)]:
            with self.assertRaises(access.AccessError):core.read_inspections(self.path,self.sessions['owner'][0],farm,obs)
        with self.assertRaises(access.AccessError):self.change(**dict(data,observation_id=other))
        self.assertNotIn('PRIVATE OTHER',json.dumps(core.read_inspections(self.path,self.sessions['viewer'][0],1)))
        with self.assertRaises(access.AccessError):self.change('viewer',**dict(data,role='owner'))
        first=self.change(**data)
        with self.assertRaises(ValueError):self.change(**self.data(oid,supersedes_id=999,reason='Invalid target'))
        with self.assertRaises(ValueError):self.change(**self.data(oid,supersedes_id=True))

    def test_revoked_disabled_expired_and_csrf_denied(self):
        oid,_=self.fixture();data=self.data(oid)
        with self.assertRaises(access.AccessError):core.change(self.path,self.sessions['owner'][0],'wrong',data)
        with self.store.connect() as db:db.execute("UPDATE nexus_farm_memberships SET role='viewer' WHERE account_id=?",(self.ids['editor'],))
        with self.assertRaises(access.AccessError):self.change('editor',**data)
        with self.store.connect() as db:db.execute('DELETE FROM nexus_farm_memberships WHERE account_id=?',(self.ids['viewer'],))
        with self.assertRaises(access.AccessError):core.read_inspections(self.path,self.sessions['viewer'][0],1)
        with self.store.connect() as db:db.execute('UPDATE nexus_accounts SET disabled=1 WHERE id=?',(self.ids['owner'],))
        with self.assertRaises(access.AccessError):self.change(**data)
        with self.store.connect() as db:db.execute('UPDATE nexus_sessions SET expires_at=0 WHERE account_id=?',(self.ids['other'],))
        with self.assertRaises(access.AccessError):core.read_inspections(self.path,self.sessions['other'][0],2)

    def test_stale_and_count_validation_do_not_insert(self):
        oid,_=self.fixture();stale=self.data(oid);first=self.change(**stale)
        with self.assertRaises(ValueError):self.change(**dict(stale,reason='Stale second form'))
        for extra in [dict(plants_checked=True),dict(plants_affected=11),dict(cobs_checked=5,newly_forming_cobs=1,mature_small_cobs=1,uncertain_cobs=1),dict(observation_hash='bad')]:
            with self.subTest(extra=extra),self.assertRaises(ValueError):self.change(**self.data(oid,**extra))
        self.assertEqual(len(core.read_inspections(self.path,self.sessions['owner'][0],1)['history']),1)

    def test_audit_failure_rolls_back_inspection(self):
        oid,_=self.fixture();data=self.data(oid)
        with self.store.connect() as db:db.execute("CREATE TRIGGER fixture_inspection_failure BEFORE INSERT ON nexus_security_events WHEN NEW.category='workspace_inspection' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.change(**data)
        self.assertEqual(core.read_inspections(self.path,self.sessions['owner'][0],1)['history'],[])

    def test_http_boundaries_and_page(self):
        oid,other=self.fixture();data=self.data(oid)
        server=ThreadingHTTPServer(('127.0.0.1',0),web.make_handler(self.path));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            base=f'http://127.0.0.1:{server.server_port}'
            def call(path,who='owner',data=None,csrf=True,origin=True):
                token,cs=self.sessions[who];headers={'Cookie':'nexus_session='+token,'Content-Type':'application/json'}
                if csrf:headers['X-Nexus-CSRF']=cs
                if origin:headers['Origin']=base
                return urlopen(Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers))
            with call('/field-inspections') as r:self.assertIn(b'Help',r.read())
            with call('/api/field-inspections?farm_id=1') as r:self.assertEqual(len(json.load(r)['observations']),1)
            for path,who,body,cs,origin,status in [('/api/field-inspections?farm_id=2','owner',None,True,True,403),('/api/field-inspections?farm_id=1&observation_id='+str(other),'owner',None,True,True,403),('/api/field-inspections','viewer',data,True,True,403),('/api/field-inspections','owner',data,False,True,403),('/api/field-inspections','owner',data,True,False,403),('/api/field-inspections?farm_id=1&farm_id=2','owner',None,True,True,400)]:
                with self.subTest(path=path,who=who),self.assertRaises(HTTPError) as e:call(path,who,body,cs,origin)
                self.assertEqual(e.exception.code,status);e.exception.close()
            with call('/api/field-inspections',data=data) as r:self.assertIn('id',json.load(r))
        finally:server.shutdown();server.server_close();thread.join()
