"""Smoke-test combined routes against a fresh temporary database, never user data."""
import socket,subprocess,sys,tempfile,time
from pathlib import Path
from urllib.request import urlopen
ROUTES=['/','/overview','/workbench','/help','/help-centre','/help-centre?topic=reliable-saving','/resources','/resources?kind=supply','/market','/market?kind=sales_order','/evidence-studio','/voice','/voice-pipeline','/voice-extraction-review','/voice-reviewed-confirmation','/voice-clarifications','/decision-cycles','/decision-report','/decision-reviews','/decision-events','/human-decisions','/review-bundles','/field-context','/weather','/field-inspections','/seasons','/observation-seasons','/season-overview','/history','/harvests','/stock','/finance','/photos','/advisers','/api/ops/meta','/api/ops/health','/api/ops/search','/api/ops/work','/api/resources/meta','/api/resources/state?limit=1&offset=0','/api/resources/state?area=market','/api/resources/export?format=json','/api/studio/meta','/api/studio/measurements','/api/studio/template','/api/studio/cases','/api/studio/notes','/api/studio/views','/api/studio/case-queue','/api/studio/links','/api/studio/finance','/api/studio/quality','/api/studio/backups','/api/help/catalog','/api/help/context?path=/market&view=sales_order','/api/help/search?q=cob','/api/help/topic?id=reliable-saving','/api/help/download?topic=reliable-saving','/ops-assets/resource_workspace.js','/ops-assets/form_safety.js','/ops-assets/page_guides.js','/ops-assets/page_guides.css','/ops-assets/resource_workspace.css','/ops-assets/evidence_studio.js','/ops-assets/operations_workbench.js']

def main():
    with tempfile.TemporaryDirectory() as folder:
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        with tempfile.TemporaryFile() as log:
            process=subprocess.Popen([sys.executable,'-u','-m','nexus.farm_app.operations','--port',str(port),'--database',str(Path(folder)/'smoke.sqlite3')],stdout=log,stderr=log)
            try:
                for attempt in range(200):
                    if process.poll() is not None:
                        log.seek(0);raise RuntimeError('Temporary server stopped: '+log.read().decode(errors='replace')[-3000:])
                    try:
                        with urlopen(f'http://127.0.0.1:{port}/api/ops/meta',timeout=.5):break
                    except OSError:time.sleep(.05)
                else:raise RuntimeError('Temporary server did not become ready')
                for path in ROUTES:
                    with urlopen(f'http://127.0.0.1:{port}'+path,timeout=10) as response:
                        raw=response.read()
                        if response.status!=200 or len(raw)!=int(response.headers['Content-Length']):raise RuntimeError('Route response failed: '+path)
                        if not response.headers.get('X-Nexus-Request-ID'):raise RuntimeError('Missing trace header: '+path)
                print('Combined workspace smoke passed: '+str(len(ROUTES))+' routes against an isolated temporary database.')
            finally:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait()
if __name__=='__main__':main()
