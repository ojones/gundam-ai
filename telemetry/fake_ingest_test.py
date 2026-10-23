import unittest

from telemetry import fake_ingest, schema


def valid_event(**overrides):
    base = {field: None for field in schema.ENVELOPE_FIELDS}
    return {**base, "schema_version": schema.SCHEMA_VERSION, "event_id": "e1", "event_name": "Stop", "occurred_at": "2026-10-21T17:00:00Z", "session_id": "s1", "metadata": {}, **overrides}


class BatchProblemTest(unittest.TestCase):
    def test_a_well_formed_batch_is_accepted(self):
        self.assertIsNone(fake_ingest.batch_problem({"events": [valid_event()]}))

    def test_an_event_missing_a_stored_field_rejects_the_whole_batch(self):
        for field in ("event_id", "event_name", "occurred_at", "session_id"):
            for value in (None, "", 7):
                batch = {"events": [valid_event(), valid_event(**{"event_id": "e2", field: value})]}
                self.assertEqual(fake_ingest.batch_problem(batch), "missing required fields", (field, value))

    def test_unexpected_fields_are_rejected(self):
        self.assertEqual(fake_ingest.batch_problem({"events": [{**valid_event(), "prompt": "x"}]}), "unexpected envelope fields")

    def test_a_skill_name_that_is_not_an_identifier_is_rejected(self):
        for name in ("fix the bug in acme", "a/b", "x" * 129, "", 7):
            batch = {"events": [valid_event(metadata={"skill_name": name})]}
            self.assertEqual(fake_ingest.batch_problem(batch), "invalid skill_name", name)

    def test_an_identifier_skill_name_is_accepted(self):
        batch = {"events": [valid_event(metadata={"skill_name": "mattpocock-skills:handoff"})]}
        self.assertIsNone(fake_ingest.batch_problem(batch))
