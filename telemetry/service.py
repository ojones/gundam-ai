import fcntl
import json
import os
import signal
import sys
import threading
from contextlib import closing

from telemetry import config as config_module
from telemetry import credential, spool, uploader

LOCK_NAME = "uploader.lock"


def acquire_lease(config):
    config.spool_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    handle = (config.spool_dir / LOCK_NAME).open("a", encoding="utf-8")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def next_delay(config, outcome, failures):
    if outcome == "retry":
        return uploader.backoff_delay(failures, cap=config.upload_interval_seconds * 10)
    return 0 if outcome in ("ok", "permanent") else config.upload_interval_seconds


def run_loop(config, token, stop):
    failures = 0
    while not stop.is_set():
        outcome = uploader.drain_once(config, token)
        failures = failures + 1 if outcome == "retry" else 0
        stop.wait(next_delay(config, outcome, failures))


def stop_on_signals():
    stop = threading.Event()
    for number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(number, lambda *_: stop.set())
    return stop


def print_health(config):
    with closing(spool.open_spool(config)) as conn:
        print(json.dumps(spool.health(conn)))
    return 0


def main(argv=None, env=None):
    config = config_module.load_config(os.environ if env is None else env)
    if argv == ["--health"]:
        return print_health(config)
    lease = acquire_lease(config)
    if lease is None:
        return 0
    run_loop(config, credential.lookup(), stop_on_signals())
    lease.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
