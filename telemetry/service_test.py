import io
import json
import unittest
from contextlib import redirect_stdout

from telemetry import service, spool
from telemetry.support import open_spool, temp_config


class ServiceTest(unittest.TestCase):
    def test_a_second_lease_is_refused_until_the_first_is_released(self):
        config = temp_config(self)
        first = service.acquire_lease(config)
        self.assertIsNotNone(first)
        self.assertIsNone(service.acquire_lease(config))
        first.close()
        second = service.acquire_lease(config)
        self.assertIsNotNone(second)
        second.close()

    def test_health_prints_queue_and_counters_without_payloads(self):
        config = temp_config(self)
        conn = open_spool(self, config)
        spool.enqueue(conn, config, "e1", '{"secret": "x"}')
        spool.bump_counter(conn, "dropped_full", 2)
        out = io.StringIO()
        with redirect_stdout(out):
            service.main(["--health"], {"TELEMETRY_SPOOL_DIR": str(config.spool_dir)})
        self.assertEqual(json.loads(out.getvalue()), {"queue_depth": 1, "dropped": 2, "expired": 0, "rejected": 0, "last_upload_at": 0})

    def test_next_delay_backs_off_only_on_retry(self):
        config = temp_config(self)
        self.assertEqual((service.next_delay(config, "ok", 0), service.next_delay(config, "idle", 0)), (0, config.upload_interval_seconds))
        self.assertLessEqual(service.next_delay(config, "retry", 3), config.upload_interval_seconds * 10)


if __name__ == "__main__":
    unittest.main()
