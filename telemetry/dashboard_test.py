import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import closing
from datetime import datetime
from pathlib import Path

from telemetry import dashboard, dashboard_data, dashboard_html, fake_ingest


def event(event_id, name, **fields):
    base = {"event_id": event_id, "event_name": name, "occurred_at": "2026-10-21T17:00:00Z", "session_id": "s1", "user_id": "u1", "repo_id": None, "tool_name": None, "tool_use_id": None, "outcome": None, "failure_class": None, "metadata": {}}
    return {**base, **fields}


SAMPLE = [
    event("1", "SessionStart"),
    event("2", "UserPromptSubmit"),
    event("3a", "PreToolUse", tool_name="Bash", tool_use_id="t1", repo_id="r1", occurred_at="2026-10-21T17:00:00Z"),
    event("3", "PostToolUse", tool_name="Bash", tool_use_id="t1", outcome="success", occurred_at="2026-10-21T17:00:04Z"),
    event("4a", "PreToolUse", tool_name="Bash", tool_use_id="t2", repo_id="r1", occurred_at="2026-10-21T17:00:10Z"),
    event("4", "PostToolUseFailure", tool_name="Bash", tool_use_id="t2", outcome="failure", failure_class="timeout", occurred_at="2026-10-21T17:00:12Z"),
    event("4b", "PreToolUse", tool_name="Bash", tool_use_id="t3", repo_id="r1", occurred_at="2026-10-21T17:00:30Z"),
    event("4c", "StopFailure", failure_class="rate_limit"),
    event("4d", "PermissionRequest", tool_name="Edit"),
    event("5", "PermissionDenied", tool_name="Edit", outcome="denied"),
    event("6", "SubagentStart"),
    event("8a", "PreToolUse", tool_name="Skill", tool_use_id="t4", occurred_at="2026-10-21T17:01:00Z"),
    event("8", "PostToolUse", tool_name="Skill", tool_use_id="t4", outcome="success", occurred_at="2026-10-21T17:01:01Z", metadata={"skill_name": "tdd"}),
    event("9", "UserPromptSubmit", metadata={"skill_name": "tdd"}),
    event("7", "UserPromptSubmit", session_id="s2", user_id="u2", occurred_at="2026-10-29T09:00:00Z"),
]


def seeded_store(testcase):
    directory = tempfile.TemporaryDirectory()
    testcase.addCleanup(directory.cleanup)
    path = Path(directory.name) / "store.sqlite"
    with closing(fake_ingest.open_store(path)) as conn:
        fake_ingest.store_events(conn, SAMPLE)
    return path


def collected(testcase):
    with closing(dashboard_data.open_read_only(seeded_store(testcase))) as conn:
        return dashboard_data.collect(conn)


class DashboardDataTest(unittest.TestCase):
    def test_adoption_counts_users_sessions_and_prompts_by_week(self):
        weeks = {w["week"]: w for w in collected(self)["adoption"]}
        self.assertEqual(weeks["2026-W43"], {"week": "2026-W43", "users": 1, "sessions": 1, "prompts": 2})
        self.assertEqual(len(weeks), 2)

    def test_workflow_counts_completed_tools_and_subagents(self):
        workflow = collected(self)["workflow"]
        self.assertEqual((workflow["tools"], workflow["repos"]), ({"Bash": 3, "Skill": 1}, {"(none)": 1, "r1": 3}))
        self.assertEqual((workflow["subagents"], workflow["subagent_sessions"], workflow["unmatched_starts"]), (1, 1, 1))

    def test_tool_calls_are_deduplicated_by_tool_use_id(self):
        again = [event("d1", "PreToolUse", tool_name="Bash", tool_use_id="same"), event("d2", "PreToolUse", tool_name="Bash", tool_use_id="same")]
        with closing(fake_ingest.open_store(":memory:")) as conn:
            fake_ingest.store_events(conn, again)
            self.assertEqual(dashboard_data.tool_calls_by(conn, "tool_name"), {"Bash": 1})

    def test_tool_duration_pairs_start_and_finish_and_retries_follow_a_failure(self):
        workflow = collected(self)["workflow"]
        self.assertEqual(workflow["durations"], {"median": 2.0, "p90": 4.0})
        self.assertEqual(workflow["retries"], 1)

    def test_a_failed_skill_still_counts_as_an_invocation(self):
        failed = event("f1", "PostToolUseFailure", tool_name="Skill", outcome="failure", metadata={"skill_name": "broken"})
        with closing(fake_ingest.open_store(":memory:")) as conn:
            fake_ingest.store_events(conn, [failed])
            self.assertEqual(dashboard_data.skills(conn)["invoked"], {"broken": 1})

    def test_weeks_follow_iso_numbering_across_the_year_boundary(self):
        days = {"2026-12-31": "2026-W53", "2027-01-01": "2026-W53", "2027-01-03": "2026-W53", "2027-01-04": "2027-W01", "2026-10-25": "2026-W43"}
        with closing(fake_ingest.open_store(":memory:")) as conn:
            fake_ingest.store_events(conn, [event(day, "SessionStart", occurred_at=f"{day}T12:00:00Z") for day in days])
            self.assertEqual({w["week"] for w in dashboard_data.adoption(conn)}, set(days.values()))

    def test_skills_are_counted_by_name_and_by_how_they_were_reached(self):
        self.assertEqual(collected(self)["skills"], {"invoked": {"tdd": 1}, "typed": {"tdd": 1}})

    def test_reliability_reports_failures_denials_and_unfinished_sessions(self):
        data = collected(self)["reliability"]
        self.assertEqual(data["failure_rates"], {"Bash": {"failed": 1, "total": 2}, "Skill": {"failed": 0, "total": 1}})
        self.assertEqual((data["failure_classes"], data["api_failures"]), ({"timeout": 1}, {"rate_limit": 1}))
        self.assertEqual((data["requests"], data["denials"], data["incomplete_sessions"]), (1, 1, 1))

    def test_efficiency_buckets_sessions_by_tool_calls_and_prompts_including_empty_ones(self):
        data = collected(self)["efficiency"]
        self.assertEqual((data["tool_calls"]["0"], data["tool_calls"]["1-5"]), (1, 1))
        self.assertEqual((data["prompts"]["0"], data["prompts"]["1-5"]), (0, 2))

    def test_sessions_are_bucketed_by_length_and_incomplete_ones_are_left_out(self):
        sessions = [event("a", "SessionStart", session_id="a", occurred_at="2026-10-21T10:00:00Z"), event("b", "SessionEnd", session_id="a", occurred_at="2026-10-21T10:20:00Z"), event("c", "SessionStart", session_id="c", occurred_at="2026-10-21T10:00:00Z")]
        with closing(fake_ingest.open_store(":memory:")) as conn:
            fake_ingest.store_events(conn, sessions)
            lengths = dashboard_data.session_lengths(conn)
        self.assertEqual((lengths["buckets"]["15-30 min"], sum(lengths["buckets"].values()), lengths["median"]), (1, 1, 20))

    def test_a_resumed_session_reusing_its_id_counts_each_stretch(self):
        stamps = [("SessionStart", "10:00"), ("SessionEnd", "10:10"), ("SessionStart", "12:00"), ("SessionEnd", "12:20")]
        resumed = [event(str(n), name, occurred_at=f"2026-10-21T{hour}:00Z") for n, (name, hour) in enumerate(stamps)]
        with closing(fake_ingest.open_store(":memory:")) as conn:
            fake_ingest.store_events(conn, resumed)
            self.assertEqual(dashboard_data.session_minutes(conn), [10.0, 20.0])

    def test_active_users_count_only_session_starts(self):
        quiet = [event("q1", "UserPromptSubmit", user_id="ghost")]
        with closing(fake_ingest.open_store(":memory:")) as conn:
            fake_ingest.store_events(conn, quiet)
            self.assertEqual(dashboard_data.adoption(conn)[0]["users"], 0)

    def test_prompts_are_counted_by_local_hour_and_weekday(self):
        local = datetime.fromisoformat("2026-10-21T17:00:00+00:00").astimezone()
        with closing(fake_ingest.open_store(":memory:")) as conn:
            fake_ingest.store_events(conn, [event("p", "UserPromptSubmit")])
            data = dashboard_data.rhythm(conn)
        self.assertEqual((data["hours"][f"{local.hour:02d}:00"], sum(data["hours"].values())), (1, 1))
        self.assertEqual(data["weekdays"][local.strftime("%a")], 1)

    def test_the_store_is_opened_read_only(self):
        with closing(dashboard_data.open_read_only(seeded_store(self))) as conn:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM ingested")


class DashboardHtmlTest(unittest.TestCase):
    def test_values_are_escaped(self):
        data = collected(self)
        data["workflow"]["tools"] = {"<script>alert(1)</script>": 1}
        self.assertNotIn("<script>alert", dashboard_html.render(data))

    def test_an_empty_store_renders(self):
        with closing(fake_ingest.open_store(":memory:")) as conn:
            data = dashboard_data.collect(conn)
        self.assertIn("no events yet", dashboard_html.render(data))


class DashboardServerTest(unittest.TestCase):
    def serve(self, store_path):
        server = dashboard.make_server(store_path, port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_port}/"

    def test_the_page_is_served_on_the_loopback_interface(self):
        with urllib.request.urlopen(self.serve(seeded_store(self))) as response:
            self.assertIn("Adoption by week", response.read().decode("utf-8"))

    def test_an_unreadable_store_is_a_503_not_a_dropped_connection(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        broken = Path(directory.name) / "broken.sqlite"
        broken.write_bytes(b"this is not a database" * 100)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.serve(broken))
        self.assertEqual(caught.exception.code, 503)

    def test_a_missing_store_is_a_503_not_a_crash(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.serve(Path(tempfile.gettempdir()) / "absent-store.sqlite"))
        self.assertEqual(caught.exception.code, 503)
