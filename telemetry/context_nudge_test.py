import io
import json
import unittest
from pathlib import Path

from telemetry import context_nudge, context_size
from telemetry.support import SECRET, temp_config


def assistant(tokens, sidechain=False):
    usage = {"input_tokens": 2, "cache_read_input_tokens": tokens - 12, "cache_creation_input_tokens": 10, "output_tokens": 999}
    return {"type": "assistant", "isSidechain": sidechain, "message": {"content": SECRET, "usage": usage}}


class ContextNudgeTest(unittest.TestCase):
    def setUp(self):
        self.config = temp_config(self)
        self.config.spool_dir.mkdir()
        self.transcript = self.config.spool_dir / "transcript.jsonl"
        self.env = {"TELEMETRY_SPOOL_DIR": str(self.config.spool_dir)}

    def write(self, *entries):
        self.transcript.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8")

    def call(self, mode, session):
        raw = {"session_id": session, "transcript_path": str(self.transcript), "prompt": SECRET}
        return context_nudge.run(mode, io.BytesIO(json.dumps(raw).encode()), self.env)

    def prompt(self, session="sess-1"):
        self.call("record", session)
        return self.call("deliver", session)

    def test_thresholds_start_at_100k_and_step_by_50k(self):
        levels = [context_size.threshold_for(n) for n in (99_999, 100_000, 149_999, 150_000, 230_000)]
        self.assertEqual(levels, [0, 100_000, 100_000, 150_000, 200_000])

    def test_below_the_first_threshold_nothing_is_said(self):
        self.write(assistant(99_999))
        self.assertIsNone(self.prompt())

    def test_each_threshold_is_announced_once(self):
        self.write(assistant(101_000))
        self.assertIn("101k", json.loads(self.prompt())["hookSpecificOutput"]["additionalContext"])
        self.assertIsNone(self.prompt())
        self.write(assistant(149_000))
        self.assertIsNone(self.prompt())
        self.write(assistant(151_000))
        self.assertIsNotNone(self.prompt())

    def test_the_response_asks_claude_to_suggest_the_handoff_skill(self):
        self.write(assistant(120_000))
        output = json.loads(self.prompt())["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "UserPromptSubmit")
        self.assertIn("/mattpocock-skills:handoff", output["additionalContext"])

    def test_sessions_are_counted_separately(self):
        self.write(assistant(120_000))
        self.assertIsNotNone(self.prompt("a"))
        self.assertIsNotNone(self.prompt("b"))

    def test_shrinking_context_lets_the_threshold_fire_again(self):
        self.write(assistant(160_000))
        self.prompt()
        self.write(assistant(30_000))
        self.assertIsNone(self.prompt())
        self.write(assistant(110_000))
        self.assertIsNotNone(self.prompt())

    def test_subagent_messages_are_ignored(self):
        self.write(assistant(10_000), assistant(300_000, sidechain=True))
        self.assertIsNone(self.prompt())

    def test_a_partial_first_line_in_a_large_transcript_is_skipped(self):
        filler = {"type": "user", "message": {"content": "x" * 400_000}}
        self.write(filler, assistant(120_000))
        self.assertIsNotNone(self.prompt())

    def test_missing_or_unusable_input_says_nothing(self):
        self.assertIsNone(self.prompt())
        self.write({"type": "user"}, assistant(0))
        self.assertIsNone(self.prompt())
        self.assertIsNone(context_nudge.run("deliver", io.BytesIO(b"not json"), self.env))
        self.assertIsNone(context_nudge.run("record", io.BytesIO(b"not json"), self.env))

    def test_recording_prints_nothing_and_delivery_waits_for_the_next_prompt(self):
        self.write(assistant(120_000))
        self.assertIsNone(self.call("record", "sess-1"))
        self.assertIsNotNone(self.call("deliver", "sess-1"))
        self.assertIsNone(self.call("deliver", "sess-1"))

    def test_delivery_never_reads_the_transcript(self):
        self.write(assistant(120_000))
        self.call("record", "sess-1")
        self.transcript.unlink()
        self.assertIsNotNone(self.call("deliver", "sess-1"))

    def test_only_the_threshold_is_stored(self):
        self.write(assistant(120_000))
        self.prompt()
        folder = Path(self.config.spool_dir, "context-nudge", "sess-1")
        stored = {path.name: path.read_text(encoding="utf-8") for path in folder.iterdir()}
        self.assertEqual(stored, {"seen": "100000"})


if __name__ == "__main__":
    unittest.main()
