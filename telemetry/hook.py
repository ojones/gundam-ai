import json
import os
import sqlite3
import sys
import uuid
from contextlib import closing
from datetime import datetime, timezone

from telemetry import allowlist, diagnostics, spool
from telemetry import config as config_module


def read_bounded(stream, limit):
    data = stream.read(limit + 1)
    return data if len(data) <= limit else None


def parse_object(data):
    try:
        raw = json.loads(data)
    except ValueError:
        return None
    return raw if isinstance(raw, dict) else None


def record_drop(config, reason, error=None):
    diagnostics.record(config.spool_dir, f"drop_{reason}", error)
    with closing(spool.open_spool(config)) as conn:
        spool.bump_counter(conn, f"dropped_{reason}")


def store(config, event):
    with closing(spool.open_spool(config)) as conn:
        spool.enqueue(conn, config, event["event_id"], json.dumps(event, separators=(",", ":")))


def process(data, config, now=None):
    if data is None:
        record_drop(config, "oversize")
        return "dropped"
    raw = parse_object(data)
    if raw is None:
        record_drop(config, "invalid")
        return "dropped"
    try:
        event = allowlist.build_event(raw, config, now or datetime.now(timezone.utc), str(uuid.uuid4()))
    except allowlist.RejectedInput as error:
        record_drop(config, "invalid", error)
        return "dropped"
    store(config, event)
    return "queued"


def run(stream, env):
    config = config_module.load_config(env)
    try:
        return process(read_bounded(stream, config.max_input_bytes), config)
    except sqlite3.Error as error:
        diagnostics.record(config.spool_dir, "sqlite_unavailable", error)
        return "dropped"


def main():
    try:
        run(sys.stdin.buffer, os.environ)
    except Exception:  # noqa: BLE001
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
