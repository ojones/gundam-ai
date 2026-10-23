import unittest

from telemetry import allowlist
from telemetry.config import Config
from telemetry.support import NOW, raw_event

CONFIG = Config(spool_dir="unused", user_id="u1", team_id="t1", repo_id="r1")


def build(raw):
    return allowlist.build_event(raw, CONFIG, NOW, "event-1")


class BuildEvent(unittest.TestCase):
    def test_a_tool_event_carries_the_tool_name_and_id_and_exact_correlation(self):
        event = build(raw_event("PostToolUse", tool_name="Bash", tool_use_id="toolu_1"))
        self.assertEqual((event["tool_name"], event["tool_use_id"], event["outcome"]), ("Bash", "toolu_1", "success"))
        self.assertEqual(event["metadata"], {"correlation_quality": "tool_use_id"})

    def test_a_tool_event_without_an_id_is_marked_uncorrelated(self):
        event = build(raw_event("PreToolUse", tool_name="Read"))
        self.assertEqual((event["tool_use_id"], event["metadata"]["correlation_quality"]), (None, "none"))

    def test_an_unknown_event_or_missing_session_is_rejected(self):
        with self.assertRaises(allowlist.RejectedInput):
            build(raw_event("MessageDisplay"))
        with self.assertRaises(allowlist.RejectedInput):
            build({"hook_event_name": "Stop"})

    def test_a_session_start_source_is_bounded(self):
        self.assertEqual(build(raw_event("SessionStart", source="resume"))["metadata"], {"source": "resume"})
        self.assertNotIn("source", build(raw_event("SessionStart", source="surprise"))["metadata"])

    def test_a_session_end_reason_outside_the_set_becomes_other(self):
        self.assertEqual(build(raw_event("SessionEnd", reason="free text"))["metadata"], {"end_reason": "other"})

    def test_a_failure_event_gets_a_bounded_class(self):
        event = build(raw_event("PostToolUseFailure", tool_name="Bash", tool_use_id="t", error="Command timed out"))
        self.assertEqual((event["outcome"], event["failure_class"]), ("failure", "timeout"))

    def test_a_non_failure_event_has_no_failure_class(self):
        self.assertIsNone(build(raw_event("Stop"))["failure_class"])

    def test_a_subagent_event_carries_type_and_id(self):
        event = build(raw_event("SubagentStart", agent_type="Explore", agent_id="a-1"))
        self.assertEqual((event["agent_type"], event["metadata"]), ("Explore", {"agent_id": "a-1"}))

    def test_a_batch_records_only_its_size(self):
        self.assertEqual(build(raw_event("PostToolBatch", tool_calls=[{}, {}, {}]))["metadata"], {"batch_size": 3})

    def test_an_identifier_with_odd_characters_is_not_kept(self):
        self.assertIsNone(build(raw_event("PreToolUse", tool_name="rm -rf /; echo", tool_use_id="x"))["tool_name"])
    def test_real_bash_failure_texts_get_their_class(self):
        cases = {
            "Exit code 1\nls: /nonexistent: No such file or directory": "not_found",
            "Exit code 1\ncat: /etc/sudoers: Permission denied": "permission",
            "Exit code 6\ncurl: (6) Could not resolve host: nohost.example": "network",
            "Exit code 7\n  % Total    % Received % Xferd": "other",
        }
        for error, expected in cases.items():
            event = build(raw_event("PostToolUseFailure", tool_name="Bash", tool_use_id="t", error=error))
            self.assertEqual(event["failure_class"], expected, error)

    def test_words_that_merely_contain_a_keyword_are_not_classified(self):
        for error in ("generate the report", "author field missing", "iterate over items"):
            event = build(raw_event("PostToolUseFailure", tool_name="Bash", tool_use_id="t", error=error))
            self.assertEqual(event["failure_class"], "other", error)

    def test_a_real_payload_shape_keeps_only_allowlisted_fields(self):
        payload = raw_event("PostToolUse", tool_name="Bash", tool_use_id="toolu_01", tool_input={"command": "ls"}, tool_response={"stdout": "x"}, duration_ms=12, prompt_id="p", effort={"level": "high"}, permission_mode="default", scratchpad_dir="/tmp/s")
        self.assertEqual(set(build(payload)["metadata"]), {"correlation_quality"})


if __name__ == "__main__":
    unittest.main()
