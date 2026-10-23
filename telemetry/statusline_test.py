import io
import json
import unittest

from telemetry import statusline


def render(payload):
    return statusline.render(payload)


class StatuslineTest(unittest.TestCase):
    def test_the_size_is_shown_in_thousands(self):
        self.assertIn("ctx 42k", render({"context_window": {"total_input_tokens": 42_500}}))

    def test_colour_and_hint_follow_the_thresholds(self):
        low, mid, high = (render({"context_window": {"total_input_tokens": n}}) for n in (99_999, 100_000, 150_000))
        self.assertTrue(low.startswith(statusline.DIM) and "handoff" not in low)
        self.assertTrue(mid.startswith(statusline.AMBER) and "handoff" in mid)
        self.assertTrue(high.startswith(statusline.RED) and "handoff" in high)

    def test_missing_or_odd_input_renders_nothing(self):
        for payload in ({}, {"context_window": None}, {"context_window": {"total_input_tokens": 0}}, {"context_window": {"total_input_tokens": "9"}}):
            self.assertEqual(render(payload), "")

    def test_main_survives_garbage_input(self):
        self.assertEqual(statusline.main(io.StringIO("not json")), 0)
        self.assertEqual(statusline.main(io.StringIO(json.dumps({"context_window": {"total_input_tokens": 120_000}}))), 0)


if __name__ == "__main__":
    unittest.main()
