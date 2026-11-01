from nexus.farm_app import field_inspections
from nexus.farm_app.season_overview import overview_state, render_overview
from nexus.farm_app.observation_seasons import (
    initialize_observation_seasons, state as observation_season_state,
    save as save_observation_season, SEASON_LINK_HTML,
)
import argparse
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from nexus.farm_app.atomic import create_observation_atomic
from nexus.farm_app.audit import (
    audited_state,
    capture_missing_snapshots,
    get_snapshot,
    initialize_audit,
)
from nexus.farm_app.history import HISTORY_HTML, retrieve_history
from nexus.farm_app.scheduling import (
    close_schedule,
    initialize_scheduling,
    save_schedule,
    schedule_state,
)
from nexus.farm_app.seasons import (
    SEASONS_HTML,
    initialize_seasons,
    save_season,
    season_state,
)
from nexus.farm_app.harvests import (
    HARVEST_HTML,
    harvest_state,
    initialize_harvests,
    save_harvest,
)
from nexus.farm_app.finance import (
    FINANCE_HTML,
    finance_state,
    initialize_finance,
    save_transaction,
)
from nexus.farm_app.stock import (
    initialize_stock,
    save_stock,
    stock_state,
)
from nexus.farm_app.photos import (
    initialize_photos,
    photo_state,
    save_photo,
    get_photo,
)
from nexus.farm_app.advisers import (
    initialize_advisers,
    adviser_state,
    save_adviser_review,
)
from nexus.farm_app.store import FarmStore


HTML = Path(__file__).with_name("index.html")
OVERVIEW_HTML = Path(__file__).with_name("overview.html")
STOCK_HTML = Path(__file__).with_name("stock.html")
PHOTOS_HTML = Path(__file__).with_name("photos.html")
ADVISERS_HTML = Path(__file__).with_name("advisers.html")


def query_id(query, key):
    values = query.get(key, [])

    if len(values) != 1:
        raise ValueError(f"Provide one {key}")

    try:
        value = int(values[0])
    except ValueError:
        raise ValueError(f"Invalid {key}") from None

    if value < 1:
        raise ValueError(f"Invalid {key}")

    return value


def workspace_state(store):
    return schedule_state(store, audited_state(store))


def make_handler(store):
    class Handler(BaseHTTPRequestHandler):
        def respond(
            self,
            status,
            body,
            content_type="application/json; charset=utf-8",
        ):
            raw = (
                body
                if isinstance(body, bytes)
                else json.dumps(body).encode("utf-8")
            )

            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)

            try:
                if path == "/":
                    self.respond(
                        200,
                        HTML.read_bytes(),
                        "text/html; charset=utf-8",
                    )

                elif path == "/overview":
                    self.respond(
                        200,
                        OVERVIEW_HTML.read_bytes(),
                        "text/html; charset=utf-8",
                    )

                elif path == "/advisers":
                    self.respond(
                        200,
                        ADVISERS_HTML.read_bytes(),
                        "text/html; charset=utf-8",
                    )

                elif path == "/api/adviser-reviews":
                    self.respond(200, adviser_state(store))

                elif path == "/photos":
                    self.respond(
                        200,
                        PHOTOS_HTML.read_bytes(),
                        "text/html; charset=utf-8",
                    )

                elif path == "/api/photos":
                    self.respond(200, photo_state(store))

                elif path == "/api/photo":
                    self.respond(
                        200,
                        get_photo(
                            store,
                            query_id(query, "photo_id"),
                        ),
                        "image/jpeg",
                    )

                elif path == "/stock":
                    self.respond(
                        200,
                        STOCK_HTML.read_bytes(),
                        "text/html; charset=utf-8",
                    )

                elif path == "/api/stock":
                    self.respond(200, stock_state(store))

                elif path == "/history":
                    self.respond(
                        200,
                        HISTORY_HTML.encode("utf-8"),
                        "text/html; charset=utf-8",
                    )

                elif path == "/field-inspections":
                    self.respond(200, field_inspections.HTML.encode("utf-8"), "text/html; charset=utf-8")

                elif path == "/api/field-inspections":
                    self.respond(200, field_inspections.state(store))

                elif path == "/season-overview":
                    self.respond(200, render_overview(overview_state(store)).encode("utf-8"), "text/html; charset=utf-8")

                elif path == "/api/season-overview":
                    self.respond(200, overview_state(store))

                elif path == "/observation-seasons":
                    self.respond(200, SEASON_LINK_HTML.encode("utf-8"), "text/html; charset=utf-8")

                elif path == "/api/observation-seasons":
                    self.respond(200, observation_season_state(store))

                elif path == "/seasons":
                    self.respond(
                        200,
                        SEASONS_HTML.encode("utf-8"),
                        "text/html; charset=utf-8",
                    )

                elif path == "/api/seasons":
                    self.respond(200, season_state(store))

                elif path == "/harvests":
                    self.respond(
                        200,
                        HARVEST_HTML.encode("utf-8"),
                        "text/html; charset=utf-8",
                    )

                elif path == "/api/harvests":
                    self.respond(200, harvest_state(store))

                elif path == "/finance":
                    self.respond(
                        200,
                        FINANCE_HTML.encode("utf-8"),
                        "text/html; charset=utf-8",
                    )

                elif path == "/api/finance":
                    self.respond(200, finance_state(store))

                elif path == "/api/state":
                    self.respond(200, workspace_state(store))

                elif path == "/api/history":
                    self.respond(
                        200,
                        retrieve_history(
                            store.snapshot(),
                            query_id(query, "observation_id"),
                        ),
                    )

                elif path == "/api/review-snapshot":
                    self.respond(
                        200,
                        get_snapshot(
                            store,
                            query_id(query, "task_id"),
                        ),
                    )

                else:
                    self.respond(404, {"error": "Not found"})

            except ValueError as error:
                self.respond(400, {"error": str(error)})

            except sqlite3.Error:
                self.respond(
                    500,
                    {"error": "Could not read the local database."},
                )

        def do_POST(self):
            origin = self.headers.get("Origin")

            if origin and origin != (
                "http://" + self.headers.get("Host", "")
            ):
                self.respond(
                    403,
                    {"error": "Cross-origin request rejected"},
                )
                return

            mutation_committed = False

            try:
                path = urlparse(self.path).path
                size = int(
                    self.headers.get("Content-Length", "0")
                )

                if path == "/api/photos":
                    limit = 3000000
                elif path in ("/api/adviser-reviews", "/api/field-inspections"):
                    limit = 65536
                else:
                    limit = 16384

                if not 0 < size <= limit:
                    raise ValueError("Invalid request size")

                data = json.loads(
                    self.rfile.read(size).decode("utf-8")
                )

                if not isinstance(data, dict):
                    raise ValueError("Expected a JSON object")

                if path == "/api/adviser-reviews":
                    save_adviser_review(store, data)

                elif path == "/api/photos":
                    save_photo(store, data)

                elif path == "/api/stock":
                    save_stock(store, data)

                elif path == "/api/finance":
                    save_transaction(store, data)

                elif path == "/api/harvests":
                    save_harvest(store, data)

                elif path == "/api/field-inspections":
                    self.respond(200, field_inspections.save(store, data))
                    return

                elif path == "/api/observation-seasons":
                    self.respond(200, save_observation_season(store, data))
                    return

                elif path == "/api/seasons":
                    save_season(store, data)

                elif path == "/api/observations":
                    create_observation_atomic(store, data)

                elif path == "/api/followup-schedules":
                    save_schedule(store, data)

                elif path == "/api/followup-schedules/close":
                    close_schedule(store, data)

                elif path in (
                    "/api/tasks",
                    "/api/task-actions",
                    "/api/followups",
                ):
                    task_id = data.get("id")

                    if (
                        isinstance(task_id, bool)
                        or not isinstance(task_id, int)
                        or task_id < 1
                    ):
                        raise ValueError("Invalid task ID")

                    if path == "/api/task-actions":
                        store.record_action(task_id, data)

                    elif path == "/api/followups":
                        store.record_followup(task_id, data)

                    else:
                        store.transition(
                            task_id,
                            data.get("action"),
                            data.get("outcome"),
                        )

                elif path in ("/api/farms", "/api/fields"):
                    store.create(
                        path.rsplit("/", 1)[-1],
                        data,
                    )

                else:
                    self.respond(404, {"error": "Not found"})
                    return

                mutation_committed = True

                if path == "/api/adviser-reviews":
                    result = adviser_state(store)

                elif path == "/api/photos":
                    result = photo_state(store)

                elif path == "/api/stock":
                    result = stock_state(store)

                elif path == "/api/finance":
                    result = finance_state(store)

                elif path == "/api/harvests":
                    result = harvest_state(store)

                elif path == "/api/seasons":
                    result = season_state(store)

                else:
                    result = workspace_state(store)

                self.respond(200, result)

            except UnicodeDecodeError:
                self.respond(
                    400,
                    {"error": "Request must contain UTF-8 JSON"},
                )

            except ValueError as error:
                message = (
                    str(error)
                    if not mutation_committed
                    else (
                        "Your change was saved, but the dashboard "
                        "could not load. Refresh before retrying."
                    )
                )

                self.respond(
                    500 if mutation_committed else 400,
                    {"error": message},
                )

            except sqlite3.Error as error:
                if mutation_committed:
                    message = (
                        "Your change was saved, but the dashboard "
                        "could not load. Refresh before retrying."
                    )

                elif isinstance(error, sqlite3.IntegrityError):
                    message = (
                        "Invalid record relationship or duplicate "
                        "action or schedule. Refresh and check "
                        "existing records."
                    )

                else:
                    message = (
                        "The database operation failed. "
                        "The change was not saved."
                    )

                status = (
                    500
                    if mutation_committed
                    or not isinstance(error, sqlite3.IntegrityError)
                    else 400
                )

                self.respond(status, {"error": message})

    return Handler


def main():
    parser = argparse.ArgumentParser(
        description="NEXUS local farmer workflow"
    )

    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--database",
        default="nexus-farm.sqlite3",
    )
    args = parser.parse_args()

    store = FarmStore(args.database)

    initialize_audit(store)
    initialize_scheduling(store)
    initialize_seasons(store)
    initialize_observation_seasons(store)
    field_inspections.initialize(store)
    initialize_harvests(store)
    initialize_finance(store)
    initialize_stock(store)
    initialize_photos(store)
    initialize_advisers(store)

    capture_missing_snapshots(
        store,
        "legacy_reconstruction",
    )

    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port),
        make_handler(store),
    )

    base = f"http://127.0.0.1:{args.port}"

    print(f"NEXUS workspace: {base}", flush=True)
    print(f"NEXUS field history: {base}/history", flush=True)
    print(f"NEXUS field inspections: {base}/field-inspections", flush=True)
    print(f"NEXUS crop seasons: {base}/seasons", flush=True)
    print(f"NEXUS harvests: {base}/harvests", flush=True)
    print(f"NEXUS expenses and sales: {base}/finance", flush=True)
    print(f"NEXUS farm dashboard: {base}/overview", flush=True)
    print(f"NEXUS produce stock: {base}/stock", flush=True)
    print(f"NEXUS photo evidence: {base}/photos", flush=True)
    print(f"NEXUS adviser reviews: {base}/advisers", flush=True)
    print("Press Ctrl+C to stop.", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping NEXUS.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()