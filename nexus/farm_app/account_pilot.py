"""Narrow authenticated local pilot. Does not expose legacy workspace routes."""
import argparse
import json
import sqlite3
from contextlib import closing
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from nexus.farm_app import scoped_access as access, local_accounts, request_inputs


def make_handler(database):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # No credentials, tokens, notes or query strings in the request log.

        def respond(self, status, body, cookie=None):
            raw = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8' if isinstance(body, bytes) else 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if cookie:
                self.send_header('Set-Cookie', cookie)
            self.end_headers()
            self.wfile.write(raw)

        def valid_host(self):
            hosts = self.headers.get_all('Host', [])
            return len(hosts) == 1 and hosts[0] in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

        def token(self):
            try:
                if len(self.headers.get_all('Cookie', [])) != 1:
                    return ''
                cookie = SimpleCookie()
                cookie.load(self.headers.get('Cookie', ''))
                return cookie['nexus_session'].value if 'nexus_session' in cookie else ''
            except CookieError:
                return ''

        def do_GET(self):
            if not self.valid_host():
                return self.respond(403, {'error': 'Use the local host and port'})
            parsed = urlparse(self.path)
            if parsed.path == '/':
                return self.respond(200, Path(__file__).with_name('account_pilot.html').read_bytes())
            if parsed.path == '/pilot.js':
                raw = Path(__file__).with_name('account_pilot.js').read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/javascript; charset=utf-8')
                self.send_header('Content-Length', str(len(raw)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                return self.wfile.write(raw)
            if parsed.path != '/api/session':
                return self.respond(404, {'error': 'Route unavailable in the scoped pilot'})
            try:
                query = parse_qs(parsed.query, keep_blank_values=True)
                if set(query) - {'farm_id'} or any(len(v) != 1 for v in query.values()):
                    raise ValueError('Use one farm ID')
                farm_id = int(query['farm_id'][0]) if 'farm_id' in query else None
                return self.respond(200, access.read(database, self.token(), farm_id))
            except access.AccessError as error:
                return self.respond(error.status, {'error': str(error)})
            except (ValueError, sqlite3.Error):
                return self.respond(400, {'error': 'Could not read this selection'})

        def do_POST(self):
            if not self.valid_host() or self.headers.get_all('Origin', []) != ['http://' + self.headers.get('Host', '')]:
                return self.respond(403, {'error': 'Matching local Origin required'})
            path = urlparse(self.path).path
            if path not in ('/api/login', '/api/logout', '/api/note'):
                return self.respond(404, {'error': 'Route unavailable in the scoped pilot'})
            try:
                data = request_inputs.parse_object(request_inputs.read_request(self))
                if path == '/api/login':
                    token, csrf = access.login(database, data.get('username'), data.get('password'))
                    return self.respond(200, {'csrf': csrf}, 'nexus_session=' + token + '; Path=/; HttpOnly; SameSite=Strict; Max-Age=28800')
                csrf = self.headers.get('X-Nexus-CSRF')
                if path == '/api/logout':
                    access.logout(database, self.token(), csrf)
                    return self.respond(200, {'signed_out': True}, 'nexus_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0')
                result = access.note(database, self.token(), csrf, data.get('farm_id'), data.get('note'))
                return self.respond(200, {'note_id': result})
            except access.AccessError as error:
                return self.respond(error.status, {'error': str(error)})
            except request_inputs.RequestError as error:
                self.close_connection = True
                return self.respond(error.status, {'error': str(error)})
            except (ValueError, sqlite3.Error):
                return self.respond(400, {'error': 'Could not save. Refresh and check the selected farm and note.'})
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--port', type=int, default=8081)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Use a port between 1 and 65535')
    try:
        with closing(local_accounts.connect(args.database)):
            pass
    except (ValueError, sqlite3.Error) as error:
        parser.exit(1, f'Pilot cannot start: {error}\n')
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(args.database))
    print(f'NEXUS scoped account pilot: http://127.0.0.1:{args.port}\nLocal testing only. Full workspace routes are unavailable.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
