import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from nexus.farm_app import workspace_access as core, authenticated_workspace as web, local_accounts as accounts, scoped_access as access, account_admin, deployment_controls as migrations
from nexus.farm_app.store import FarmStore
from nexus.farm_app.audit import initialize_audit


class WorkspacePermissionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'fixture.db'
        self.store=FarmStore(self.path)
        initialize_audit(self.store)
        with self.store.connect() as db:
            db.executemany('INSERT INTO farms VALUES (?,?,?)',[(1,'Visible fixture','Fixture'),(2,'Private other farm','Fixture')])
            db.executemany('INSERT INTO fields VALUES (?,?,?,?)',[(1,1,'Visible plot','maize'),(2,2,'Private plot','maize')])
        migrations.migrate(self.path,Path(self.temp.name)/'backups')
        self.ids={};self.sessions={}
        for name,role,farm in [('owner','owner',1),('editor','editor',1),('viewer','viewer',1),('other','owner',2)]:
            uid=accounts.create(self.path,name,'fixture-'+name+'-password')
            self.ids[name]=uid
            accounts.grant(self.path,uid,farm,role)
            self.sessions[name]=access.login(self.path,name,'fixture-'+name+'-password')

    def change(self,name='owner',**data):
        token,csrf=self.sessions[name]
        return core.change(self.path,token,csrf,data)

    def observation(self,name='owner',farm=1,field=1):
        return self.change(name,operation='observation',farm_id=farm,field_id=field,note='Fixture observation only',category='general')

    def test_scoped_reads_and_cross_farm_fields_tasks(self):
        first=self.observation()
        second=self.observation('other',2,2)
        for name in ('owner','editor','viewer'):
            token,_=self.sessions[name]
            state=core.read(self.path,token,1)
            self.assertEqual([f['id'] for f in state['farms']],[1])
            self.assertEqual([f['id'] for f in state['fields']],[1])
            self.assertEqual([o['id'] for o in state['observations']],[first['observation_id']])
            self.assertEqual([t['id'] for t in state['tasks']],[first['task_id']])
            self.assertNotIn('Private other farm',json.dumps(state))
            with self.assertRaises(access.AccessError):core.read(self.path,token,2)
        self.assertNotEqual(first['task_id'],second['task_id'])

    def test_viewer_write_and_forged_role_denied(self):
        for op,extra in [('field',dict(name='Forbidden',crop='maize')),('observation',dict(field_id=1,note='Forbidden')),('approve',dict(task_id=1,review_confirmed=True))]:
            with self.assertRaises(access.AccessError):
                self.change('viewer',operation=op,farm_id=1,role='owner',**extra)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM observations').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM fields').fetchone()[0],2)

    def test_forged_parent_and_task_ids_cannot_cross_scope(self):
        task=self.observation('other',2,2)['task_id']
        with self.assertRaises(access.AccessError):self.observation('owner',1,2)
        with self.assertRaises(access.AccessError):self.change(operation='approve',farm_id=1,task_id=task,review_confirmed=True)
        with self.assertRaises(access.AccessError):self.change(operation='action',farm_id=1,task_id=task,action_type='inspection',description='Forbidden')
        with self.assertRaises(ValueError):self.change(operation='field',farm_id=True,name='Invalid',crop='maize')

    def test_editor_workflow_preserves_atomic_snapshot_and_rules(self):
        saved=self.observation('editor')
        task=saved['task_id']
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM review_snapshots WHERE task_id=?',(task,)).fetchone()[0],1)
        with self.assertRaises(ValueError):self.change('editor',operation='approve',farm_id=1,task_id=task)
        self.change('editor',operation='approve',farm_id=1,task_id=task,review_confirmed=True)
        self.change('editor',operation='action',farm_id=1,task_id=task,action_type='inspection',description='Fixture inspected; cause unconfirmed')
        self.change('editor',operation='followup',farm_id=1,task_id=task,result='uncertain',evidence='Fixture no independent outcome verification')
        state=core.read(self.path,self.sessions['viewer'][0],1)
        self.assertEqual(state['tasks'][0]['status'],'completed')
        self.assertEqual(len(state['actions']),1)
        self.assertEqual(len(state['followups']),1)
        with self.assertRaises(ValueError):self.change('editor',operation='approve',farm_id=1,task_id=task,review_confirmed=True)

    def test_permission_and_audit_are_one_transaction(self):
        with self.store.connect() as db:
            db.execute("CREATE TRIGGER fixture_failure BEFORE INSERT ON nexus_security_events WHEN NEW.category='workspace_observation' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.observation()
        with self.store.connect() as db:
            for table in ('observations','tasks','review_snapshots'):
                self.assertEqual(db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)

    def test_revoked_disabled_and_expired_sessions_denied(self):
        token,csrf=self.sessions['editor']
        with self.store.connect() as db:db.execute('DELETE FROM nexus_farm_memberships WHERE account_id=?',(self.ids['editor'],))
        with self.assertRaises(access.AccessError):core.change(self.path,token,csrf,dict(operation='field',farm_id=1,name='Forbidden',crop='maize'))
        token,csrf=self.sessions['viewer']
        with self.store.connect() as db:db.execute('UPDATE nexus_accounts SET disabled=1 WHERE id=?',(self.ids['viewer'],))
        with self.assertRaises(access.AccessError):core.read(self.path,token,1)
        with self.store.connect() as db:db.execute('UPDATE nexus_sessions SET expires_at=0 WHERE account_id=?',(self.ids['owner'],))
        with self.assertRaises(access.AccessError):self.observation()

    def test_farm_creation_requires_platform_admin_and_assigns_owner(self):
        with self.assertRaises(access.AccessError):self.change(operation='farm',name='New fixture',location='Fixture')
        account_admin.bootstrap(self.path,self.ids['owner'])
        saved=self.change(operation='farm',name='New fixture',location='Fixture')
        state=core.read(self.path,self.sessions['owner'][0],saved['farm_id'])
        self.assertIn(saved['farm_id'],[f['id'] for f in state['farms']])
        self.assertTrue(state['can_write'])
        result=self.change(operation='field',farm_id=saved['farm_id'],name='New fixture plot',crop='maize')
        self.assertGreater(result['field_id'],2)

    def test_csrf_and_timestamp_denial_save_nothing(self):
        token,_=self.sessions['owner']
        with self.assertRaises(access.AccessError):core.change(self.path,token,'wrong',dict(operation='field',farm_id=1,name='Forbidden',crop='maize'))
        with self.assertRaises(ValueError):self.change(operation='observation',farm_id=1,field_id=1,note='Fixture',observed_at='2099-01-01T00:00:00+00:00')
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM observations').fetchone()[0],0)

    def test_http_login_protected_routes_writes_and_legacy_denials(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),web.make_handler(self.path))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            base=f'http://127.0.0.1:{server.server_port}'
            def call(path,data=None,token=None,csrf=None,origin=True):
                headers={'Content-Type':'application/json'}
                if token:headers['Cookie']='nexus_session='+token
                if csrf:headers['X-Nexus-CSRF']=csrf
                if origin:headers['Origin']=base
                return urlopen(Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers))
            with self.assertRaises(HTTPError) as e:call('/api/workspace')
            self.assertEqual(e.exception.code,401)
            with call('/api/login',dict(username='owner',password='fixture-owner-password')) as r:
                cookie=r.headers['Set-Cookie'];csrf=json.load(r)['csrf'];token=cookie.split(';')[0].split('=',1)[1]
            with call('/workspace',token=token) as r:self.assertIn(b'protected workspace',r.read())
            with call('/workspace.js') as r:self.assertIn('javascript',r.headers['Content-Type'])
            with call('/api/workspace?farm_id=1',token=token) as r:self.assertEqual([f['id'] for f in json.load(r)['fields']],[1])
            data=dict(operation='observation',farm_id=1,field_id=1,note='Fixture HTTP observation')
            for tk,cs,orig in [(token,None,True),(token,csrf,False),(*self.sessions['viewer'],True)]:
                with self.assertRaises(HTTPError) as e:call('/api/workspace',data,tk,cs,orig)
                self.assertEqual(e.exception.code,403)
            with call('/api/workspace',data,token,csrf) as r:self.assertIn('task_id',json.load(r))
            for path in ('/api/state','/api/farms','/api/resources/export','/api/finance','/photos','/api/voice-drafts','/api/review-bundle?bundle_id=1'):
                with self.assertRaises(HTTPError) as e:call(path,token=token)
                self.assertEqual(e.exception.code,404)
            with self.assertRaises(HTTPError) as e:call('/api/workspace?farm_id=2',token=token)
            self.assertEqual(e.exception.code,403)
            with call('/api/logout',{},token,csrf):pass
            with self.assertRaises(HTTPError) as e:call('/api/workspace?farm_id=1',token=token)
            self.assertEqual(e.exception.code,401)
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__':
    unittest.main()
