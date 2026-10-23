import sqlite3
import sys
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from telemetry import dashboard_data, dashboard_html, fake_ingest

DEFAULT_PORT = 8081


def page(store_path):
    with closing(dashboard_data.open_read_only(store_path)) as conn:
        return dashboard_html.render(dashboard_data.collect(conn)).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/":
            return self.respond(404, b"not found")
        if not self.server.store_path.exists():
            return self.respond(503, b"no data yet: run `make ingest` and `make uploader`")
        return self.serve_page()

    def serve_page(self):
        try:
            body = page(self.server.store_path)
        except sqlite3.DatabaseError:
            return self.respond(503, b"the store cannot be read right now")
        return self.respond(200, body)

    def log_message(self, format, *args):
        return None


def make_server(store_path, port=DEFAULT_PORT):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.store_path = store_path
    return server


def main():
    server = make_server(fake_ingest.default_store_path())
    print(f"dashboard on http://127.0.0.1:{server.server_port}/")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
