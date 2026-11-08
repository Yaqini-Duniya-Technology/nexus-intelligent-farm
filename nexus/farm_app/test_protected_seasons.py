"""Protected crop-season permissions and historical context."""
import json
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import unittest

from nexus.farm_app import authenticated_workspace, harvests, scoped_access
from nexus.farm_app import test_protected_inspections as fixtures
from nexus.farm_app.workspace_access import read_seasons


class ProtectedSeasonTests(unittest.TestCase):
    setUp = fixtures.ProtectedInspectionTests.setUp
    change = fixtures.ProtectedInspectionTests.change
    fixture = fixtures.ProtectedInspectionTests.fixture

    def season(self, **changes):
        return dict(dict(operation='season',farm_id=1,field_id=1,name='Demo wet season',
                         variety='Demo maize',area_ha=.5,planting_date='2026-06-01',
                         expected_harvest_date='2026-10-01'), **changes)

    def state(self, who='owner', farm=1):
        return read_seasons(self.path,self.sessions[who][0],farm)

    def context(self, oid, season=None, **changes):
        state=self.state()
        return dict(dict(operation='season_context',farm_id=1,observation_id=oid,
            observation_hash=next(o['selection_hash'] for o in state['observations'] if o['id']==oid),
            season_id=season['id'] if season else None,
            season_hash=season['selection_hash'] if season else None,
            base_id=next((h['id'] for h in state['history'] if h['observation_id']==oid),None),
            reporter='Demo reporter',basis='Demo field record',reason='Initial context',growth_stage='unknown'),**changes)

    def test_existing_database_and_link_states(self):
        oid,_=self.fixture()
        self.assertEqual(self.state('viewer')['history'],[])
        with self.store.connect() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='crop_seasons'").fetchone())
        sid=self.change('editor',**self.season())['id']
        unknown=self.context(oid)
        self.change(**unknown)
        self.assertTrue(self.change(**unknown)['reused'])
        state=self.state()
        self.assertEqual(state['history'][0]['status'],'unknown')
        season=state['seasons'][0]
        self.change(**self.context(oid,season,reason='Link after checking'))
        edit=self.season(id=sid,selection_hash=season['selection_hash'],name='Corrected season name')
        self.change(**edit)
        with self.assertRaisesRegex(ValueError,'Season changed'):
            self.change(**edit)
        state=self.state('viewer')
        self.assertFalse(state['can_write'])
        self.assertEqual(state['history'][0]['status'],'linked')
        self.assertEqual(state['history'][0]['season']['name'],'Demo wet season')
        self.assertEqual(state['seasons'][0]['name'],'Corrected season name')
        self.assertEqual(state['revisions'][0]['before']['name'],'Demo wet season')
        self.assertEqual(len(state['revisions']),2)
        harvests.initialize_harvests(self.store)
        with self.store.connect() as db:
            db.execute("INSERT INTO harvests VALUES(1,?,'2026-10-01',0,.5,'private note','2026-10-01')",(sid,))
        self.assertEqual(self.state('viewer')['harvests'][0]['quantity_kg'],0)
        self.assertNotIn('private note',json.dumps(self.state('viewer')['harvests']))

    def test_scope_immutability_and_invalid_dates(self):
        oid,other=self.fixture()
        foreign=self.change('other',**self.season(farm_id=2,field_id=2,name='Secret farm crop'))['id']
        own=self.change(**self.season())['id']
        another=self.change(operation='field',farm_id=1,name='Another plot',crop='maize')['field_id']
        self.assertNotIn('Secret farm crop',json.dumps(self.state('viewer')))
        for data in (self.season(field_id=2),self.season(id=foreign),
                     self.context(oid,season_id=foreign),self.context(oid,observation_id=other)):
            with self.assertRaises(scoped_access.AccessError):
                self.change(**data)
        for data in (self.season(id=own,field_id=another),self.season(expected_harvest_date='2026-05-01'),
                     self.season(area_ha=0),self.context(oid,season_hash='forged')):
            with self.assertRaises(ValueError):
                self.change(**data)
        with self.assertRaises(scoped_access.AccessError):
            self.state('viewer',2)
        # A legacy field move invalidates the link; the captured details stay hidden.
        self.change(**self.context(oid,self.state()['seasons'][0]))
        with self.store.connect() as db:
            db.execute('UPDATE crop_seasons SET field_id=2 WHERE id=?',(own,))
        redacted=self.state('viewer')['history'][0]
        self.assertEqual(redacted['status'],'unavailable')
        self.assertNotIn('season',redacted)
        self.assertNotIn('basis',redacted)

    def test_http_rechecks_permissions_and_keeps_legacy_closed(self):
        oid,_=self.fixture()
        server=ThreadingHTTPServer(('127.0.0.1',0),authenticated_workspace.make_handler(self.path))
        thread=Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            base=f'http://127.0.0.1:{server.server_port}'

            def call(path,who='owner',data=None,csrf=True,origin=True):
                token,secret=self.sessions[who]
                headers={'Cookie':'nexus_session='+token,'Content-Type':'application/json'}
                if csrf:headers['X-Nexus-CSRF']=secret
                if origin:headers['Origin']=base
                return urlopen(Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers=headers),timeout=5)

            def denied(code,*args,**kw):
                with self.assertRaises(HTTPError) as error:
                    call(*args,**kw)
                self.assertEqual(error.exception.code,code)
                error.exception.close()

            path='/api/protected-seasons'
            with call('/protected-seasons','viewer') as response:
                self.assertIn(b'Protected crop seasons',response.read())
            with call(path,data=self.season()) as response:
                self.assertGreater(json.load(response)['id'],0)
            with call(path+'?farm_id=1','viewer') as response:
                self.assertFalse(json.load(response)['can_write'])
            denied(403,path,'viewer',self.season())
            denied(403,path,data=self.season(),csrf=False)
            denied(403,path,data=self.season(),origin=False)
            denied(403,path+'?farm_id=2')
            denied(404,'/api/harvests')
            denied(404,'/api/seasons')
            denied(404,'/api/observation-seasons')
            context=self.context(oid)
            with self.store.connect() as db:
                db.execute('DELETE FROM nexus_farm_memberships WHERE account_id=?',(self.ids['editor'],))
            denied(403,path,'editor',context)
            denied(403,path+'?farm_id=1','editor')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
