"""Run browser acceptance against a fresh, isolated database. Requires Node/Playwright."""
import json
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from nexus.farm_app import authenticated_workspace
from nexus.farm_app.test_protected_inspections import ProtectedInspectionTests


def main():
    fixture = ProtectedInspectionTests()
    try:
        fixture.setUp()
        observation, other_observation = fixture.fixture()
        with ThreadingHTTPServer(('127.0.0.1', 0), authenticated_workspace.make_handler(fixture.path)) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                subprocess.run(
                    ['node', str(Path(__file__).with_name('smoke_inspection_browser.cjs'))],
                    input=json.dumps({
                        'url': f'http://127.0.0.1:{server.server_port}',
                        'database': str(fixture.path), 'python': sys.executable,
                        'observation': observation, 'otherObservation': other_observation,
                        'owner': fixture.ids['owner'],
                    }),
                    text=True, check=True, timeout=150,
                )
            finally:
                server.shutdown()
                thread.join()
    finally:
        fixture.doCleanups()


if __name__ == '__main__':
    main()
