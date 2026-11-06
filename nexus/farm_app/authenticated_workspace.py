"""Protected main-workspace entry point: core records only; no legacy delegation."""
import argparse
import json
import sqlite3
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from nexus.farm_app import account_pilot, local_accounts, request_inputs, scoped_access as access, workspace_access as workflows
from nexus.farm_app.audit import initialize_audit
from nexus.farm_app.store import FarmStore


def make_handler(database):
    parent = account_pilot.make_handler(database)
    class Handler(parent):
        def do_GET(self):
            if not self.valid_host():
                return self.respond(403, {'error':'Use the local host and port'})
            parsed = urlparse(self.path)
            if parsed.path == '/':
                raw = Path(__file__).with_name('account_pilot.html').read_text(encoding='utf-8')
                raw = raw.replace('NEXUS account pilot','NEXUS authenticated workspace')
                raw = raw.replace('Local permission testing: farm records and separate notes. Full workspace workflows are unavailable here. Do not publish this pilot.', 'Protected core workflows are available through Open workspace after sign-in. Other full-workspace sections are still being integrated. Keep this development server local.')
                raw = raw.replace('<button id="logout">','<a href="/workspace">Open workspace</a><button id="logout">')
                return self.respond(200,raw.encode())
            if parsed.path in ('/workspace.js','/inspections.js'):
                raw = Path(__file__).with_name('authenticated_inspections.js' if parsed.path=='/inspections.js' else 'authenticated_workspace.js').read_bytes()
                self.send_response(200)
                self.send_header('Content-Type','text/javascript; charset=utf-8')
                self.send_header('Content-Length',str(len(raw)))
                self.send_header('Cache-Control','no-store')
                self.send_header('X-Content-Type-Options','nosniff')
                self.end_headers()
                return self.wfile.write(raw)
            if parsed.path not in ('/workspace','/api/workspace','/field-inspections','/api/field-inspections'):
                # This parent is an explicit account-pilot allowlist, not legacy Operations.
                return super().do_GET()
            try:
                query = parse_qs(parsed.query, keep_blank_values=True)
                if set(query)-({'farm_id','observation_id'} if parsed.path=='/api/field-inspections' else {'farm_id'}) or any(len(v)!=1 for v in query.values()):
                    raise ValueError('Use one farm selection')
                farm = int(query['farm_id'][0]) if 'farm_id' in query else None
                if parsed.path=='/api/field-inspections':
                    oid = int(query['observation_id'][0]) if 'observation_id' in query else None
                    return self.respond(200,workflows.read_inspections(database,self.token(),farm,oid))
                result = workflows.read(database,self.token(),farm)
                if parsed.path=='/field-inspections':
                    return self.respond(200,Path(__file__).with_name('authenticated_inspections.html').read_bytes())
                if parsed.path == '/workspace':
                    return self.respond(200,Path(__file__).with_name('authenticated_workspace.html').read_bytes())
                return self.respond(200,result)
            except access.AccessError as error:
                if error.status==401 and parsed.path in ('/workspace','/field-inspections'):
                    self.send_response(302)
                    self.send_header('Location','/')
                    self.send_header('Cache-Control','no-store')
                    self.send_header('Content-Length','0')
                    self.end_headers()
                    return
                return self.respond(error.status,{'error':str(error)})
            except (ValueError,TypeError,sqlite3.Error):
                return self.respond(400,{'error':'Could not read the selected farm records'})

        def do_POST(self):
            if urlparse(self.path).path not in ('/api/workspace','/api/field-inspections'):
                return super().do_POST()
            if not self.valid_host() or self.headers.get_all('Origin',[])!=['http://'+self.headers.get('Host','')]:
                return self.respond(403,{'error':'Matching local Origin required'})
            try:
                raw = request_inputs.read_request(self)
                data = request_inputs.parse_object(raw)
                if urlparse(self.path).path=='/api/field-inspections':
                    if data.get('operation','inspection')!='inspection':
                        raise ValueError('Inspection operation required')
                    data['operation']='inspection'
                if len(self.headers.get_all('X-Nexus-CSRF',[]))!=1:
                    raise access.AccessError('Refresh before saving')
                return self.respond(200,workflows.change(database,self.token(),self.headers.get('X-Nexus-CSRF'),data))
            except access.AccessError as error:
                return self.respond(error.status,{'error':str(error)})
            except request_inputs.RequestError as error:
                self.close_connection=True
                return self.respond(error.status,{'error':str(error)})
            except (ValueError,TypeError) as error:
                return self.respond(400,{'error':str(error)})
            except sqlite3.Error:
                return self.respond(400,{'error':'Could not save. Refresh saved records before retrying.'})
    return Handler


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True)
    parser.add_argument('--port',type=int,default=8080)
    args=parser.parse_args()
    if not 1<=args.port<=65535:
        parser.error('Use a port between 1 and 65535')
    try:
        with closing(local_accounts.connect(args.database)):
            pass
        initialize_audit(FarmStore(args.database))
    except (ValueError,sqlite3.Error) as error:
        parser.exit(1,f'Authenticated workspace cannot start: {error}\n')
    server=ThreadingHTTPServer(('127.0.0.1',args.port),make_handler(args.database))
    print(f'Release: nexus-baseline-inspections-v1 | Database: {Path(args.database).resolve()}',flush=True)
    print(f'NEXUS authenticated core workspace: http://127.0.0.1:{args.port}\nUnsupported legacy routes are unavailable. Keep local.',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__=='__main__':
    main()
