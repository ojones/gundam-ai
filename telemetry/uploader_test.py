import json
import unittest
from contextlib import closing

from telemetry import fake_ingest, spool, uploader
from telemetry.config import Config
from telemetry.support import open_spool, start_fake_ingest, temp_config


def event(event_id, **overrides):
    base = {key: None for key in ("schema_version", "event_id", "event_name", "occurred_at", "session_id", "user_id", "team_id", "repo_id", "tool_name", "tool_use_id", "agent_type", "outcome", "duration_ms", "failure_class")}
    return {**base, "schema_version": 1, "event_id": event_id, "event_name": "Stop", "occurred_at": "2026-10-21T17:00:00Z", "session_id": "s1", "metadata": {}, **overrides}


def enqueue(conn, config, *events):
    for item in events:
        spool.enqueue(conn, config, item["event_id"], json.dumps(item))


def ingested_ids(store_path):
    with closing(fake_ingest.open_store(store_path)) as conn:
        return sorted(row[0] for row in conn.execute("SELECT event_id FROM ingested"))


class UploaderTest(unittest.TestCase):
    def configured(self, endpoint, **overrides):
        base = temp_config(self)
        return Config(spool_dir=base.spool_dir, endpoint=endpoint, http_timeout_seconds=2, **overrides)

    def test_unconfigured_leaves_rows_queued(self):
        config = temp_config(self)
        conn = open_spool(self, config)
        enqueue(conn, config, event("e1"))
        self.assertEqual(uploader.drain_once(config, "t"), "unconfigured")
        self.assertEqual(spool.queue_depth(conn), 1)

    def test_success_deletes_rows_and_records_the_upload(self):
        store_path, endpoint = start_fake_ingest(self)
        config = self.configured(endpoint)
        conn = open_spool(self, config)
        enqueue(conn, config, event("e1"), event("e2"))
        self.assertEqual(uploader.drain_once(config, "test-token"), "ok")
        self.assertEqual((spool.queue_depth(conn), ingested_ids(store_path)), (0, ["e1", "e2"]))
        self.assertGreater(spool.counter(conn, "last_upload_at"), 0)

    def test_an_empty_queue_is_idle(self):
        _, endpoint = start_fake_ingest(self)
        self.assertEqual(uploader.drain_once(self.configured(endpoint), "test-token"), "idle")

    def test_a_retryable_error_keeps_rows_claimable(self):
        config = self.configured("http://127.0.0.1:9/v1/events")
        conn = open_spool(self, config)
        enqueue(conn, config, event("e1"))
        self.assertEqual(uploader.drain_once(config, "t"), "retry")
        self.assertEqual(len(spool.claim_batch(conn, 10)), 1)

    def test_a_permanent_error_discards_rows_and_counts_them(self):
        store_path, endpoint = start_fake_ingest(self)
        config = self.configured(endpoint)
        conn = open_spool(self, config)
        enqueue(conn, config, event("e1"))
        self.assertEqual(uploader.drain_once(config, "wrong-token"), "permanent")
        self.assertEqual((spool.queue_depth(conn), spool.counter(conn, "rejected"), ingested_ids(store_path)), (0, 1, []))

    def test_resending_a_batch_is_idempotent(self):
        store_path, endpoint = start_fake_ingest(self)
        config = self.configured(endpoint)
        conn = open_spool(self, config)
        enqueue(conn, config, event("e1"))
        rows = [("e1", json.dumps(event("e1")))]
        self.assertEqual([uploader.send_batch(config, rows, "test-token") for _ in range(2)], [200, 200])
        self.assertEqual(ingested_ids(store_path), ["e1"])

    def test_the_idempotency_key_is_stable_for_the_same_events(self):
        rows = [("b", "{}"), ("a", "{}")]
        self.assertEqual(uploader.idempotency_key(rows), uploader.idempotency_key(list(reversed(rows))))

    def test_the_fake_endpoint_rejects_unexpected_fields(self):
        _, endpoint = start_fake_ingest(self)
        config = self.configured(endpoint)
        rows = [("e1", json.dumps({**event("e1"), "prompt": "leak"}))]
        self.assertEqual(uploader.send_batch(config, rows, "test-token"), 400)


if __name__ == "__main__":
    unittest.main()
