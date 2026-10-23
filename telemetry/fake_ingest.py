import json
import sqlite3
import sys
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from telemetry import allowlist, credential, schema

DEFAULT_PORT = 8080
MAX_BODY_BYTES = 5_000_000
STORED_FIELDS = ("event_id", "event_name", "occurred_at", "session_id", "user_id", "repo_id", "tool_name", "tool_use_id", "outcome", "failure_class")
COLUMNS = STORED_FIELDS + ("skill_name",)
REQUIRED_FIELDS = COLUMNS[:4]
INGEST_FILE = "ingested-v4.sqlite"


def table_sql():
    required = [f"{name} TEXT NOT NULL" for name in REQUIRED_FIELDS]
    optional = [f"{name} TEXT" for name in COLUMNS[len(REQUIRED_FIELDS):]]
    return f"CREATE TABLE IF NOT EXISTS ingested ({', '.join(required + optional)}, PRIMARY KEY (event_id))"


def open_store(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute(table_sql())
    return conn


def required_problem(event):
    if not all(isinstance(event[field], str) and event[field] for field in REQUIRED_FIELDS):
        return "missing required fields"
    return None


def metadata_problem(metadata):
    if not isinstance(metadata, dict) or not set(metadata) <= set(schema.METADATA_FIELDS):
        return "unexpected metadata fields"
    skill = metadata.get("skill_name")
    if skill is not None and not (isinstance(skill, str) and allowlist.IDENTIFIER.fullmatch(skill)):
        return "invalid skill_name"
    return None


def event_problem(event):
    if not isinstance(event, dict) or set(event) != set(schema.ENVELOPE_FIELDS):
        return "unexpected envelope fields"
    if required_problem(event):
        return required_problem(event)
    if event["schema_version"] != schema.SCHEMA_VERSION:
        return "unsupported schema_version"
    return metadata_problem(event["metadata"])


def batch_problem(body):
    events = body.get("events") if isinstance(body, dict) else None
    if not isinstance(events, list) or not events:
        return "events must be a non-empty list"
    return next(filter(None, map(event_problem, events)), None)


def stored_row(event):
    return tuple(event[field] for field in STORED_FIELDS) + (event["metadata"].get("skill_name"),)


def store_events(conn, events):
    rows = [stored_row(e) for e in events]
    conn.executemany(f"INSERT OR IGNORE INTO ingested VALUES ({', '.join('?' * len(COLUMNS))})", rows)


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
