import json
import sqlite3
import sys
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from telemetry import credential, schema

DEFAULT_PORT = 8080
MAX_BODY_BYTES = 5_000_000
INGEST_FILE = "ingested.sqlite"


def open_store(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("CREATE TABLE IF NOT EXISTS ingested (event_id TEXT PRIMARY KEY, event_name TEXT NOT NULL, outcome TEXT, tool_name TEXT, failure_class TEXT, session_id TEXT NOT NULL)")
    return conn


def event_problem(event):
    if not isinstance(event, dict) or set(event) != set(schema.ENVELOPE_FIELDS):
        return "unexpected envelope fields"
    if event["schema_version"] != schema.SCHEMA_VERSION:
        return "unsupported schema_version"
    if not isinstance(event["metadata"], dict) or not set(event["metadata"]) <= set(schema.METADATA_FIELDS):
        return "unexpected metadata fields"
    return None


def batch_problem(body):
    events = body.get("events") if isinstance(body, dict) else None
    if not isinstance(events, list) or not events:
        return "events must be a non-empty list"
    return next(filter(None, map(event_problem, events)), None)


def store_events(conn, events):
    rows = [(e["event_id"], e["event_name"], e["outcome"], e["tool_name"], e["failure_class"], e["session_id"]) for e in events]
    conn.executemany("INSERT OR IGNORE INTO ingested VALUES (?, ?, ?, ?, ?, ?)", rows)


def aggregate(conn):
    events = dict(conn.execute("SELECT event_name, COUNT(*) FROM ingested GROUP BY 1"))
    tools = {f"{name}:{outcome}": count for name, outcome, count in conn.execute("SELECT tool_name, outcome, COUNT(*) FROM ingested WHERE tool_name IS NOT NULL GROUP BY 1, 2")}
    sessions = conn.execute("SELECT COUNT(DISTINCT session_id) FROM ingested").fetchone()[0]
    return {"events": events, "tools": tools, "sessions": sessions}


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, message):
        body = json.dumps({"message": message}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= MAX_BODY_BYTES:
            return None
        try:
            return json.loads(self.rfile.read(length))
        except ValueError:
            return None

    def accept(self, body):
        with closing(open_store(self.server.store_path)) as conn:
            store_events(conn, body["events"])
        return self.reply(200, "ok")

    def do_POST(self):
        if self.headers.get("Authorization") != f"Bearer {self.server.token}":
            return self.reply(401, "unauthorized")
        body = self.read_body()
        problem = batch_problem(body)
        return self.reply(400, problem) if problem else self.accept(body)

    def log_message(self, format, *args):
        return None


def make_server(store_path, token, port=DEFAULT_PORT):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.store_path = store_path
    server.token = token
    return server


def default_store_path():
    return Path.home() / "Library" / "Application Support" / "claude-telemetry-ingest" / INGEST_FILE


def main(argv):
    if argv == ["--aggregate"]:
        print(json.dumps(aggregate(open_store(default_store_path())), indent=2))
        return 0
    token = credential.lookup()
    if not token:
        print("no token in the Keychain: run `make token`", file=sys.stderr)
        return 1
    make_server(default_store_path(), token).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
