import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from nexus.farm_app import scoped_access as access, local_accounts as accounts, deployment_controls as controls, account_pilot
from nexus.farm_app.store import FarmStore


class ScopedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'farm.db'
        self.store = FarmStore(self.path)
        with self.store.connect() as db:
            db.executemany('INSERT INTO farms VALUES (?,?,?)', [(1,'Allowed','Fixture'),(2,'Forbidden','Fixture')])
            db.executemany('INSERT INTO fields VALUES (?,?,?,?)', [(1,1,'Visible','maize'),(2,2,'Hidden','maize')])
        controls.migrate(self.path, Path(self.temp.name) / 'backups')
        self.owner = accounts.create(self.path, 'owner', 'fixture-owner-password')
        self.viewer = accounts.create(self.path, 'viewer', 'fixture-viewer-password')
        accounts.grant(self.path, self.owner, 1, 'owner')
        accounts.grant(self.path, self.viewer, 1, 'viewer')

    def test_session_hash_and_logout(self):
        token, csrf = access.login(self.path, 'owner', 'fixture-owner-password')
        with self.store.connect() as db:
            row = dict(db.execute('SELECT * FROM nexus_sessions').fetchone())
            self.assertNotIn(token, str(row))
        self.assertEqual(access.read(self.path, token)['username'], 'owner')
        access.logout(self.path, token, csrf)
        with self.assertRaises(access.AccessError):
            access.read(self.path, token)

    def test_farm_scope_and_viewer_write_denial(self):
        token, csrf = access.login(self.path, 'owner', 'fixture-owner-password')
        state = access.read(self.path, token, 1)
        self.assertEqual([f['id'] for f in state['farms']], [1])
        self.assertEqual([f['id'] for f in state['fields']], [1])
        with self.assertRaises(access.AccessError):
            access.read(self.path, token, 2)
        with self.assertRaises(access.AccessError):
            access.note(self.path, token, csrf, 2, 'Fixture')
        access.note(self.path, token, csrf, 1, 'Fixture note')
        viewer, viewer_csrf = access.login(self.path, 'viewer', 'fixture-viewer-password')
        self.assertEqual(len(access.read(self.path, viewer, 1)['notes']), 1)
        with self.assertRaises(access.AccessError):
            access.note(self.path, viewer, viewer_csrf, 1, 'Forbidden')
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM nexus_scoped_notes').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM observations').fetchone()[0], 0)

    def test_csrf_and_disabled_account(self):
        token, csrf = access.login(self.path, 'owner', 'fixture-owner-password')
        with self.assertRaises(access.AccessError):
            access.note(self.path, token, 'wrong', 1, 'Fixture')
        with self.store.connect() as db:
            db.execute('UPDATE nexus_accounts SET disabled=1 WHERE id=?', (self.owner,))
        with self.assertRaises(access.AccessError):
            access.read(self.path, token)

    def test_session_expiry_and_revoked_grant(self):
        token, csrf = access.login(self.path, 'owner', 'fixture-owner-password', now=1000)
        with self.store.connect() as db:
            self.assertEqual(access.identity(db, token, now=1001)['account_id'], self.owner)
            with self.assertRaises(access.AccessError):
                access.identity(db, token, now=2801)
        token, csrf = access.login(self.path, 'owner', 'fixture-owner-password')
        with self.store.connect() as db:
            db.execute('DELETE FROM nexus_farm_memberships WHERE account_id=?', (self.owner,))
        with self.assertRaises(access.AccessError):
            access.note(self.path, token, csrf, 1, 'Fixture')

    def test_failed_login_limit_and_reset(self):
        for _ in range(5):
            with self.assertRaises(access.AccessError) as error:
                access.login(self.path, 'unknown', 'wrong', now=1000)
            self.assertEqual(error.exception.status, 401)
        with self.assertRaises(access.AccessError) as error:
            access.login(self.path, 'unknown', 'wrong', now=1001)
        self.assertEqual(error.exception.status, 429)
        with self.assertRaises(access.AccessError) as error:
            access.login(self.path, 'unknown', 'wrong', now=1901)
        self.assertEqual(error.exception.status, 401)

    def test_http_scope_cookie_origin_and_legacy_routes(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), account_pilot.make_handler(self.path))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            def call(path, data=None, cookie=None, csrf=None, origin=True):
                headers = {'Content-Type':'application/json'}
                if origin: headers['Origin'] = base
                if cookie: headers['Cookie'] = cookie
                if csrf: headers['X-Nexus-CSRF'] = csrf
                return urlopen(Request(base + path, data=json.dumps(data).encode() if data is not None else None, headers=headers))
            with self.assertRaises(HTTPError) as error:
                call('/api/session')
            self.assertEqual(error.exception.code, 401)
            with call('/api/login', {'username':'owner','password':'fixture-owner-password'}) as response:
                cookie = response.headers['Set-Cookie']
                self.assertIn('HttpOnly', cookie)
                self.assertIn('SameSite=Strict', cookie)
                csrf = json.load(response)['csrf']
            cookie = cookie.split(';')[0]
            with call('/api/session?farm_id=1', cookie=cookie) as response:
                self.assertNotIn('Hidden', response.read().decode())
            for path in ('/api/session?farm_id=2', '/api/resources/export', '/api/state', '/photos'):
                with self.assertRaises(HTTPError) as error:
                    call(path, cookie=cookie)
                self.assertIn(error.exception.code, (403,404))
            with self.assertRaises(HTTPError) as error:
                call('/api/note', {'farm_id':1,'note':'Fixture'}, cookie, csrf, origin=False)
            self.assertEqual(error.exception.code, 403)
            with self.assertRaises(HTTPError) as error:
                call('/api/note', {'farm_id':1,'note':'Fixture'}, cookie)
            self.assertEqual(error.exception.code, 403)
            with call('/api/note', {'farm_id':1,'note':'Fixture'}, cookie, csrf) as response:
                self.assertIn('note_id', json.load(response))
            with call('/api/logout', {}, cookie, csrf): pass
            with self.assertRaises(HTTPError) as error:
                call('/api/session', cookie=cookie)
            self.assertEqual(error.exception.code, 401)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
