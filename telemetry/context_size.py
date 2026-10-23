import json
import os

FIRST_THRESHOLD = 100_000
THRESHOLD_STEP = 50_000
TAIL_BYTES = 262_144
USAGE_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def threshold_for(tokens):
    if tokens < FIRST_THRESHOLD:
        return 0
    return FIRST_THRESHOLD + (tokens - FIRST_THRESHOLD) // THRESHOLD_STEP * THRESHOLD_STEP


def usage_total(usage):
    return sum(usage.get(key, 0) for key in USAGE_KEYS if isinstance(usage.get(key), int))


def entry_tokens(entry):
    if entry.get("type") != "assistant" or entry.get("isSidechain"):
        return None
    usage = (entry.get("message") or {}).get("usage")
    total = usage_total(usage) if isinstance(usage, dict) else 0
    return total or None


def tail_lines(path):
    with path.open("rb") as stream:
        size = stream.seek(0, os.SEEK_END)
        stream.seek(max(0, size - TAIL_BYTES))
        lines = stream.read().decode("utf-8", errors="replace").splitlines()
    return lines[1:] if size > TAIL_BYTES else lines


def parse_object(text):
    try:
        value = json.loads(text)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def context_tokens(path):
    for line in reversed(tail_lines(path)):
        tokens = entry_tokens(parse_object(line))
        if tokens:
            return tokens
    return None
