import hashlib
import json
import random
import time
import urllib.error
import urllib.request
from contextlib import closing

from telemetry import spool

RETRYABLE_STATUSES = frozenset({408, 425, 429})
NETWORK_ERROR = 599


def classify_status(code):
    if 200 <= code < 300:
        return "ok"
    if code in RETRYABLE_STATUSES or code >= 500:
        return "retry"
    return "permanent"


def backoff_delay(attempt, base=1.0, cap=300.0, rng=random):
    return rng.uniform(0, min(cap, base * 2**attempt))


def idempotency_key(rows):
    return hashlib.sha256("\n".join(sorted(event_id for event_id, _ in rows)).encode("utf-8")).hexdigest()


def build_request(config, rows, token):
    body = json.dumps({"events": [json.loads(payload) for _, payload in rows]}, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}", "Idempotency-Key": idempotency_key(rows)}
    return urllib.request.Request(config.endpoint, data=body, headers=headers, method="POST")


def send_batch(config, rows, token):
    try:
        with urllib.request.urlopen(build_request(config, rows, token), timeout=config.http_timeout_seconds) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except OSError:
        return NETWORK_ERROR


def settle(conn, rows, status):
    event_ids = [event_id for event_id, _ in rows]
    outcome = classify_status(status)
    if outcome == "ok":
        spool.acknowledge(conn, event_ids)
        spool.set_counter(conn, "last_upload_at", int(time.time()))
    elif outcome == "retry":
        spool.release(conn, event_ids)
    else:
        spool.reject(conn, event_ids)
    return outcome


def expire_old(conn, config):
    spool.expire_older_than(conn, time.time() - config.max_queue_age_days * 86400)


def drain_once(config, token):
    if not config.endpoint or not token:
        return "unconfigured"
    with closing(spool.open_spool(config)) as conn:
        expire_old(conn, config)
        rows = spool.claim_batch(conn, config.batch_size)
        return settle(conn, rows, send_batch(config, rows, token)) if rows else "idle"
