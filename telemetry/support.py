import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from telemetry import fake_ingest, spool
from telemetry.config import Config

NOW = datetime(2026, 10, 21, 17, 0, 0, tzinfo=timezone.utc)
SECRET = "SENTINEL-do-not-leak"


def temp_config(testcase, **overrides):
    directory = tempfile.TemporaryDirectory()
    testcase.addCleanup(directory.cleanup)
    return Config(spool_dir=Path(directory.name) / "spool", **overrides)


def open_spool(testcase, config):
    conn = spool.open_spool(config)
    testcase.addCleanup(conn.close)
    return conn


def raw_event(name, **fields):
    base = {"hook_event_name": name, "session_id": "sess-1", "cwd": f"/home/{SECRET}", "transcript_path": f"/tmp/{SECRET}.jsonl"}
    return {**base, **fields}


def sensitive_fields():
    return {
        "prompt": f"please fix {SECRET}",
        "tool_input": {"command": f"curl {SECRET}", "file_path": f"/src/{SECRET}.py"},
        "tool_response": {"output": SECRET},
        "error": f"permission denied: {SECRET}",
        "env": {"API_KEY": SECRET},
    }


def start_fake_ingest(testcase, token="test-token"):
    directory = tempfile.TemporaryDirectory()
    testcase.addCleanup(directory.cleanup)
    store_path = Path(directory.name) / "ingested.sqlite"
    server = fake_ingest.make_server(store_path, token, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    testcase.addCleanup(server.server_close)
    testcase.addCleanup(server.shutdown)
    return store_path, f"http://127.0.0.1:{server.server_port}/v1/events"
