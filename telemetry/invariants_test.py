import ast
import contextlib
import io
import json
import random
import sqlite3
import stat
import unittest
from contextlib import closing
from pathlib import Path

from telemetry import allowlist, events, fake_ingest, hook, managed_settings, schema, service, spool, uploader
from telemetry.config import Config, load_config
from telemetry.support import NOW, SECRET, open_spool, raw_event, sensitive_fields, start_fake_ingest, temp_config

PACKAGE = Path(__file__).resolve().parent
HOOK_PATH_MODULES = ("hook", "allowlist", "spool", "config", "schema", "events", "diagnostics")
NETWORK_MODULES = ("socket", "ssl", "http", "urllib.request", "requests", "httpx", "urllib3", "aiohttp", "ftplib", "smtplib")
FORBIDDEN_SETTINGS_KEYS = {"decision", "continue", "permissionDecision", "hookSpecificOutput", "additionalContext"}


def build(raw, config=None):
    return allowlist.build_event(raw, config or Config(spool_dir=PACKAGE), NOW, "event-1")


def run_hook(testcase, data, config):
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        stream = io.BytesIO(data)
        result = hook.run(stream, {"TELEMETRY_SPOOL_DIR": str(config.spool_dir), **extra_env(config)})
    return result, stdout.getvalue()


def extra_env(config):
    return {"TELEMETRY_MAX_INPUT_BYTES": str(config.max_input_bytes), "TELEMETRY_MAX_DB_BYTES": str(config.max_db_bytes), "TELEMETRY_BUSY_TIMEOUT_MS": str(config.busy_timeout_ms)}


def stored_payloads(config):
    with closing(spool.open_spool(config)) as conn:
        return [json.loads(payload) for (payload,) in conn.execute("SELECT payload FROM events")]


def counter_value(config, name):
    with closing(spool.open_spool(config)) as conn:
        return spool.counter(conn, name)


def imported_modules(name):
    tree = ast.parse((PACKAGE / f"{name}.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def network_imports(name):
    return {m for m in imported_modules(name) if any(m == n or m.startswith(n + ".") for n in NETWORK_MODULES)}


def all_keys(value):
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in all_keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in all_keys(item)}
    return set()


class Invariants(unittest.TestCase):
    def test_inv01_content_fields_never_reach_the_event(self):
        for name in events.HOOK_EVENTS:
            raw = raw_event(name, tool_name="Bash", tool_use_id="t1", **sensitive_fields())
            self.assertNotIn(SECRET, json.dumps(build(raw)), name)

    def test_inv02_the_event_has_exactly_the_envelope_fields(self):
        for name in events.HOOK_EVENTS:
            event = build(raw_event(name, prompt="x", tool_calls=[{}], source="startup", reason="clear", agent_id="a", tool_name="T"))
            self.assertEqual(tuple(event), schema.ENVELOPE_FIELDS, name)
            self.assertLessEqual(set(event["metadata"]), set(schema.METADATA_FIELDS), name)

    def test_inv03_the_hook_prints_nothing_and_succeeds_on_any_input(self):
        config = temp_config(self)
        valid = json.dumps(raw_event("Stop")).encode()
        for data in (valid, b"not json", b"[1,2]", b"", b"x" * (config.max_input_bytes + 1)):
            result, stdout = run_hook(self, data, config)
            self.assertEqual(stdout, "")
            self.assertIn(result, ("queued", "dropped"))

    def test_inv04_generated_settings_are_async_and_make_no_decisions(self):
        generated = managed_settings.managed_settings(include_optional=True)
        self.assertEqual(set(generated["hooks"]), set(events.HOOK_EVENTS))
        hooks = [h for groups in generated["hooks"].values() for group in groups for h in group["hooks"]]
        self.assertTrue(all(h["type"] == "command" and h["async"] is True for h in hooks))
        self.assertEqual(all_keys(generated) & FORBIDDEN_SETTINGS_KEYS, set())

    def test_inv05_redelivery_of_an_event_id_queues_one_row(self):
        config = temp_config(self)
        conn = open_spool(self, config)
        self.assertTrue(spool.enqueue(conn, config, "e1", "{}"))
        self.assertFalse(spool.enqueue(conn, config, "e1", "{}"))
        self.assertEqual(spool.queue_depth(conn), 1)

    def test_inv06_a_full_spool_drops_and_counts(self):
        config = temp_config(self, max_db_bytes=1)
        conn = open_spool(self, config)
        self.assertFalse(spool.enqueue(conn, config, "e1", "{}"))
        self.assertEqual((spool.queue_depth(conn), spool.counter(conn, "dropped_full")), (0, 1))

    def test_inv07_oversize_input_is_dropped_and_counted(self):
        config = temp_config(self, max_input_bytes=100)
        result, _ = run_hook(self, json.dumps(raw_event("Stop", prompt="x" * 500)).encode(), config)
        self.assertEqual((result, stored_payloads(config), counter_value(config, "dropped_oversize")), ("dropped", [], 1))

    @unittest.skipIf(not hasattr(stat, "S_IMODE"), "posix permissions")
    def test_inv08_the_spool_directory_is_owner_only(self):
        config = temp_config(self)
        open_spool(self, config)
        self.assertEqual(stat.S_IMODE(config.spool_dir.stat().st_mode), 0o700)

    def test_inv09_a_prompt_is_only_a_coarse_bucket(self):
        lengths = {0: "0-199", 199: "0-199", 200: "200-999", 999: "200-999", 1000: "1000+", 50_000: "1000+"}
        for length, bucket in lengths.items():
            event = build(raw_event("UserPromptSubmit", prompt="x" * length))
            self.assertEqual(event["metadata"], {"prompt_length_bucket": bucket})

    def test_inv10_a_failure_is_a_bounded_class_without_error_text(self):
        for error in ("Connection reset", "weird " + SECRET, None, 42):
            event = build(raw_event("StopFailure", error=error))
            self.assertIn(event["failure_class"], schema.FAILURE_CLASSES)
            self.assertNotIn(SECRET, json.dumps(event))

    def test_inv11_the_hook_path_imports_no_network_library(self):
        for name in HOOK_PATH_MODULES:
            self.assertEqual(network_imports(name), set(), name)

    def test_inv12_identity_comes_only_from_configuration(self):
        self.assertEqual([build(raw_event("Stop"))[key] for key in ("user_id", "team_id", "repo_id")], [None] * 3)
        config = load_config({"TELEMETRY_SPOOL_DIR": "/x", "TELEMETRY_USER_ID": "pseud-1", "USER": "alice"})
        self.assertEqual(build(raw_event("Stop"), config)["user_id"], "pseud-1")

    def test_inv13_an_older_spool_is_migrated_keeping_its_rows(self):
        config = temp_config(self)
        config.spool_dir.mkdir(parents=True)
        old = sqlite3.connect(config.spool_path)
        old.executescript(spool.MIGRATIONS[0])
        old.execute("INSERT INTO events(event_id, payload, created_at) VALUES ('e1', '{}', 0)")
        old.execute("PRAGMA user_version = 1")
        old.commit()
        old.close()
        conn = open_spool(self, config)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], len(spool.MIGRATIONS))
        self.assertEqual(spool.queue_depth(conn), 1)

    def test_inv14_claimed_rows_stay_hidden_until_the_lease_ends_and_acks_delete(self):
        config = temp_config(self)
        conn = open_spool(self, config)
        spool.enqueue(conn, config, "e1", "{}", now=0)
        self.assertEqual(len(spool.claim_batch(conn, 10, now=100)), 1)
        self.assertEqual(spool.claim_batch(conn, 10, now=101), [])
        self.assertEqual(len(spool.claim_batch(conn, 10, now=100 + spool.LEASE_SECONDS)), 1)
        spool.acknowledge(conn, ["e1"])
        self.assertEqual(spool.queue_depth(conn), 0)

    def test_inv15_rows_past_the_maximum_age_expire_and_are_counted(self):
        config = temp_config(self)
        conn = open_spool(self, config)
        spool.enqueue(conn, config, "old", "{}", now=1)
        spool.enqueue(conn, config, "new", "{}", now=1000)
        self.assertEqual(spool.expire_older_than(conn, 500), 1)
        self.assertEqual((spool.queue_depth(conn), spool.counter(conn, "expired")), (1, 1))

    def test_inv16_statuses_classify_and_backoff_is_jittered_and_capped(self):
        self.assertEqual([uploader.classify_status(c) for c in (200, 204, 429, 503, 400, 401, 422)], ["ok", "ok", "retry", "retry", "permanent", "permanent", "permanent"])
        delays = {uploader.backoff_delay(20, base=1, cap=60, rng=random.Random(seed)) for seed in range(20)}
        self.assertGreater(len(delays), 1)
        self.assertLessEqual(max(delays), 60)

    def test_inv17_a_locked_database_drops_the_event_and_the_hook_still_succeeds(self):
        config = temp_config(self, busy_timeout_ms=10)
        holder = open_spool(self, config)
        holder.execute("BEGIN EXCLUSIVE")
        result, stdout = run_hook(self, json.dumps(raw_event("Stop")).encode(), config)
        holder.execute("ROLLBACK")
        self.assertEqual((result, stdout, stored_payloads(config)), ("dropped", "", []))

    def test_inv18_the_uploader_acknowledges_only_after_success(self):
        _, endpoint = start_fake_ingest(self)
        config = Config(spool_dir=temp_config(self).spool_dir, endpoint=endpoint, http_timeout_seconds=2)
        conn = open_spool(self, config)
        spool.enqueue(conn, config, "e1", "{}")
        self.assertEqual(uploader.drain_once(config, "wrong-token"), "permanent")
        self.assertEqual(spool.queue_depth(conn), 0)
        spool.enqueue(conn, config, "e2", "{}")
        self.assertEqual(uploader.drain_once(Config(spool_dir=config.spool_dir, endpoint="http://127.0.0.1:9/", http_timeout_seconds=1), "t"), "retry")
        self.assertEqual(spool.queue_depth(conn), 1)

    def test_inv19_only_one_uploader_drains_at_a_time(self):
        config = temp_config(self)
        lease = service.acquire_lease(config)
        self.addCleanup(lease.close)
        self.assertIsNone(service.acquire_lease(config))

    def test_inv20_health_is_local_and_has_no_listener(self):
        config = temp_config(self)
        conn = open_spool(self, config)
        self.assertEqual(set(spool.health(conn)), {"queue_depth", "dropped", "expired", "rejected", "last_upload_at"})
        self.assertEqual(network_imports("service"), set())

    def test_inv21_a_sample_event_flows_end_to_end(self):
        store_path, endpoint = start_fake_ingest(self)
        config = Config(spool_dir=temp_config(self).spool_dir, endpoint=endpoint, http_timeout_seconds=2)
        self.assertEqual(hook.process(json.dumps(raw_event("PostToolUse", tool_name="Bash", tool_use_id="tu-1", **sensitive_fields())).encode(), config), "queued")
        self.assertEqual(uploader.drain_once(config, "test-token"), "ok")
        with closing(fake_ingest.open_store(store_path)) as conn:
            self.assertEqual(fake_ingest.aggregate(conn)["tools"], {"Bash:success": 1})
            self.assertNotIn(SECRET, json.dumps(conn.execute("SELECT * FROM ingested").fetchall()))

    def test_inv22_the_privacy_notice_covers_collect_inspect_disable_delete(self):
        text = (PACKAGE.parent / "docs" / "privacy.md").read_text(encoding="utf-8")
        for heading in ("## What is collected", "## How to inspect it", "## How to disable it", "## How to request deletion"):
            self.assertIn(heading, text)

    @unittest.skip("pending: dashboard")
    def test_inv23_dashboards_label_proxies(self):
        raise NotImplementedError


if __name__ == "__main__":
    unittest.main()
