"""One local launcher for the combined NEXUS workspace and operations workbench."""
import json
import io
import sys
import uuid
import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from nexus.farm_app import operations_records as records, operations_exports as exports, work_orders, evidence_studio, page_guides, farm_resources, project_branding, produce_market, request_inputs
from nexus.farm_app.operations_common import RELEASE, readonly, table_names

ROOT=Path(__file__).parent
ASSETS={'form_safety.js':'text/javascript; charset=utf-8','resource_workspace.js':'text/javascript; charset=utf-8','resource_workspace.css':'text/css; charset=utf-8','operations_workbench.css':'text/css; charset=utf-8','operations_workbench.js':'text/javascript; charset=utf-8', 'evidence_studio.js':'text/javascript; charset=utf-8', 'page_guides.js':'text/javascript; charset=utf-8', 'page_guides.css':'text/css; charset=utf-8'}


def bootstrap_optional(store):
    # Empty optional schemas let the combined app open before any voice test run.
    # No audio, transcript, model output or farm evidence is fabricated.
    from nexus.farm_app import voice_drafts, voice_response_review
    voice_drafts.initialize(store)
    with store.connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS natlas_voice_requests (
            id INTEGER PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
            draft_id INTEGER NOT NULL REFERENCES voice_drafts(id), draft_version INTEGER NOT NULL,
            input_sha256 TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(draft_id,draft_version,input_sha256))""")
        db.execute("""CREATE TABLE IF NOT EXISTS natlas_voice_responses (
            id INTEGER PRIMARY KEY,response_id TEXT NOT NULL UNIQUE,
            request_id TEXT NOT NULL REFERENCES natlas_voice_requests(request_id),
            content_sha256 TEXT NOT NULL UNIQUE,imported_at TEXT NOT NULL,
            payload TEXT NOT NULL,local_structure_check TEXT NOT NULL)""")
    voice_response_review.initialize(store.path)
    with store.connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS natlas_voice_observation_links (
            id INTEGER PRIMARY KEY,review_id INTEGER NOT NULL UNIQUE REFERENCES natlas_voice_response_reviews(id),
            draft_id INTEGER NOT NULL UNIQUE REFERENCES voice_drafts(id),
            observation_id INTEGER NOT NULL UNIQUE REFERENCES observations(id),
            task_id INTEGER NOT NULL UNIQUE REFERENCES tasks(id),confirmation_sha256 TEXT NOT NULL,
            confirmed_at TEXT NOT NULL,provenance TEXT NOT NULL)""")


def metadata(store):
    with readonly(store.path) as db:
        tables=table_names(db)
        fields=[dict(r) for r in db.execute('SELECT id,name,crop FROM fields ORDER BY id')]
        observations=[dict(r) for r in db.execute('SELECT id,field_id,note FROM observations ORDER BY id DESC')]
        counts={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('farms','fields','observations','tasks','work_orders','field_inspections') if t in tables}
    return {'release':RELEASE,'fields':fields,'observations':observations,'counts':counts,'kinds':list(records.SPECS),
            'links':{'Record inspection':'/field-inspections','Review evidence':'/review-bundles',
                     'Crop seasons':'/season-overview','Photos':'/photos','Adviser findings':'/advisers',
                     'Produce stock':'/stock','Expenses and sales':'/finance','Human decisions':'/human-decisions'}}


def make_handler(base,store):
    work_orders.initialize(store)
    evidence_studio.initialize(store)
    farm_resources.initialize(store)
    class Handler(base):
        def host_valid(self):
            try:
                parsed=urlparse('http://'+self.headers.get('Host',''))
                return parsed.hostname in ('127.0.0.1','localhost','::1') and parsed.port==self.server.server_port and parsed.username is None and parsed.password is None and not parsed.path and not parsed.query and not parsed.fragment
            except ValueError:return False

        def trace_id(self):
            if not getattr(self,'_nexus_trace',None):self._nexus_trace=uuid.uuid4().hex
            return self._nexus_trace

        def log_message(self,format,*args):
            # Log route/status only, never query strings, request bodies or headers.
            code=args[1] if len(args)>1 and str(args[1]).isdigit() else '-'
            sys.stderr.write('NEXUS '+getattr(self,'command','?')+' '+urlparse(getattr(self,'path','/')).path[:200].__repr__()+' '+str(code)+' trace='+self.trace_id()+'\n')

        def respond(self,status,body,content_type='application/json; charset=utf-8'):
            raw=body if isinstance(body,bytes) else json.dumps(body,ensure_ascii=False,allow_nan=False).encode()
            if status==200 and content_type.startswith('text/html'):
                raw=page_guides.inject(project_branding.inject(raw,self.path),self.path)
            self.send_response(status)
            self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(raw)))
            self.send_header('X-Nexus-Request-ID',self.trace_id())
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('X-Frame-Options','DENY')
            self.send_header('Referrer-Policy','no-referrer')
            self.end_headers();self.wfile.write(raw)

        def download(self,raw,content_type,filename):
            self.send_response(200);self.send_header('Content-Type',content_type)
            self.send_header('Content-Disposition','attachment; filename="'+filename+'"')
            self.send_header('Content-Length',str(len(raw)));self.send_header('X-Nexus-Request-ID',self.trace_id());self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY')
            self.send_header('Referrer-Policy','no-referrer');self.end_headers();self.wfile.write(raw)

        def do_GET(self):
            if not self.host_valid():return self.respond(403,{'error':'Use the local NEXUS host and port'})
            parsed=urlparse(self.path);path=parsed.path;query={k:v[-1] for k,v in parse_qs(parsed.query,keep_blank_values=True).items()}
            try:
                if path=='/market':return self.respond(200,(ROOT/'market_workspace.html').read_bytes(),'text/html; charset=utf-8')
                if path=='/api/market/offer':return self.download(*produce_market.offer_sheet(store,int(query.get('offer_id','0')),query.get('format','html')))
                if path=='/api/market/statement':return self.download(*produce_market.statement(store,int(query.get('order_id','0')),query.get('format','html')))
                if path=='/resources':return self.respond(200,(ROOT/'resource_workspace.html').read_bytes(),'text/html; charset=utf-8')
                if path=='/api/resources/meta':return self.respond(200,farm_resources.metadata())
                if path=='/api/resources/state':return self.respond(200,farm_resources.state(store,query))
                if path=='/api/resources/export':return self.download(*farm_resources.export(store,query))
                if path=='/api/resources/calendar':return self.download(*farm_resources.calendar(store,query))
                if path=='/help-centre':return self.respond(200,page_guides.centre(query),'text/html; charset=utf-8')
                if path=='/api/help/catalog':return self.respond(200,page_guides.catalog())
                if path=='/api/help/context':return self.respond(200,{'topics':page_guides.context(query.get('path','/'),query.get('view',''))})
                if path=='/api/help/search':return self.respond(200,{'topics':page_guides.search(query.get('q',''),query.get('category',''))})
                if path=='/api/help/topic':return self.respond(200,page_guides.topic_by_id(query.get('id','')))
                if path=='/api/help/download':return self.download(page_guides.standalone(query.get('topic','')),'text/html; charset=utf-8','nexus-user-guide.html')
                if path=='/evidence-studio':
                    return self.respond(200,(ROOT/'evidence_studio.html').read_bytes(),'text/html; charset=utf-8')
                if path.startswith('/api/studio/'):
                    result=evidence_studio.get(store,path.removeprefix('/api/studio/'),query)
                    if isinstance(result,tuple):return self.download(*result)
                    return self.respond(200,result)
                if path in ('/workbench','/help'):
                    if path=='/help':
                        self.send_response(302);self.send_header('X-Nexus-Request-ID',self.trace_id());self.send_header('Location','/help-centre');self.send_header('Content-Length','0');self.end_headers();return
                    return self.respond(200,(ROOT/'operations_workbench.html').read_bytes(),'text/html; charset=utf-8')
                if path.startswith('/ops-assets/'):
                    name=path.rsplit('/',1)[-1]
                    if name not in ASSETS:return self.respond(404,{'error':'Asset not found'})
                    return self.respond(200,(ROOT/name).read_bytes(),ASSETS[name])
                if not path.startswith('/api/ops/'):return super().do_GET()
                endpoint=path.removeprefix('/api/ops/')
                if endpoint=='meta':return self.respond(200,metadata(store))
                if endpoint=='health':
                    from nexus.farm_app.operations_recovery import doctor
                    return self.respond(200,doctor(store.path))
                if endpoint in ('search','timeline'):
                    if endpoint=='timeline' and not query.get('field_id') and not query.get('observation_id'):
                        raise ValueError('Choose a field or observation for a timeline')
                    return self.respond(200,records.search(store.path,query))
                if endpoint=='record':return self.respond(200,records.detail(store.path,query.get('kind'),query.get('id')))
                if endpoint=='inspections':return self.respond(200,records.inspection_ledger(store.path,query))
                if endpoint=='compare':return self.respond(200,records.compare_inspections(store.path,query.get('ids','').split(',')))
                if endpoint=='reviews':return self.respond(200,records.review_queue(store.path,query))
                if endpoint=='calendar':return self.download(records.calendar(store.path),'text/calendar; charset=utf-8','nexus-review-dates.ics')
                if endpoint=='work':return self.respond(200,work_orders.state(store))
                if endpoint=='export':
                    kind=query.pop('dataset','records');format=query.pop('format','csv')
                    if format=='zip':raw,typ=exports.portable(store.path,kind,query),'application/zip'
                    else:raw,typ=exports.export(store.path,kind,format,query)
                    return self.download(raw,typ,'nexus-'+kind+'.'+format)
                return self.respond(404,{'error':'Operations route not found'})
            except (ValueError,TypeError,KeyError) as error:return self.respond(400,{'error':str(error)})
            except (sqlite3.Error,OSError):return self.respond(500,{'error':'Could not read local records. Check the database and server terminal.'})

        def do_POST(self):
            if not self.host_valid():return self.respond(403,{'error':'Use the local NEXUS host and port'})
            if self.headers.get('Origin')!='http://'+self.headers.get('Host',''):
                return self.respond(403,{'error':'Same-origin browser request required'})
            try:raw=request_inputs.read_request(self)
            except request_inputs.RequestError as error:
                self.close_connection=True
                return self.respond(error.status,{'error':str(error)})
            original=self.rfile
            self.rfile=io.BytesIO(raw)
            try:return self.dispatch_post()
            finally:self.rfile=original

        def dispatch_post(self):
            if not self.host_valid():return self.respond(403,{'error':'Use the local NEXUS host and port'})
            path=urlparse(self.path).path
            if path.startswith('/api/resources/'):
                if self.headers.get('Origin')!='http://'+self.headers.get('Host',''):return self.respond(403,{'error':'Cross-origin request rejected'})
                if path!='/api/resources/save':return self.respond(404,{'error':'Resource route not found'})
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=65536:raise ValueError('Invalid resource request size')
                    data=json.loads(self.rfile.read(size).decode('utf-8'))
                    if not isinstance(data,dict):raise ValueError('Expected a JSON object')
                    return self.respond(200,farm_resources.save(store,data))
                except (ValueError,KeyError,TypeError) as error:return self.respond(400,{'error':str(error)})
                except sqlite3.Error:return self.respond(500,{'error':'Could not save resource record. Refresh and check the server terminal.'})
            if path.startswith('/api/studio/'):
                if self.headers.get('Origin')!='http://'+self.headers.get('Host',''):
                    return self.respond(403,{'error':'Cross-origin request rejected'})
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=262144:raise ValueError('Invalid studio request size')
                    data=json.loads(self.rfile.read(size).decode('utf-8'))
                    if not isinstance(data,dict):raise ValueError('Expected a JSON object')
                    return self.respond(200,evidence_studio.post(store,path.removeprefix('/api/studio/'),data))
                except (ValueError,KeyError,TypeError) as error:return self.respond(400,{'error':str(error)})
                except (sqlite3.Error,OSError):return self.respond(500,{'error':'Could not save studio records. Check the server terminal.'})
            if not path.startswith('/api/ops/'):return super().do_POST()
            if self.headers.get('Origin')!='http://'+self.headers.get('Host',''):
                return self.respond(403,{'error':'Cross-origin request rejected'})
            if path not in ('/api/ops/work','/api/ops/work-events'):
                return self.respond(404,{'error':'Operations route not found'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=65536:raise ValueError('Invalid request size')
                data=json.loads(self.rfile.read(size).decode('utf-8'))
                if not isinstance(data,dict):raise ValueError('Expected a JSON object')
                saved=work_orders.create(store,data) if path.endswith('/work') else work_orders.change(store,data)
                return self.respond(200,saved)
            except (ValueError,TypeError,KeyError) as error:return self.respond(400,{'error':str(error)})
            except sqlite3.Error:return self.respond(500,{'error':'Could not save work order. Refresh and check the server terminal.'})
    return Handler


def main():
    from nexus.farm_app import server, voice_clarifications
    original=server.main
    def start():
        previous=server.make_handler
        def combined(store):
            bootstrap_optional(store)
            return make_handler(previous(store),store)
        server.make_handler=combined
        try:return original()
        finally:server.make_handler=previous
    server.main=start
    try:
        print(RELEASE+'\nOperations workbench: /workbench\nOffline help: /help',flush=True)
        voice_clarifications.main()
    finally:server.main=original


if __name__=='__main__':main()
