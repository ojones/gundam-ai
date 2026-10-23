import re

from telemetry import events, schema


class RejectedInput(ValueError):
    pass


IDENTIFIER = re.compile(r"[A-Za-z0-9_.:\-]{1,128}")
FAILURE_PATTERNS = tuple(
    (re.compile(pattern), label)
    for pattern, label in (
        (r"timed out|timeout", "timeout"),
        (r"permission|not permitted|operation not allowed", "permission"),
        (r"not found|no such file", "not_found"),
        (r"interrupt", "interrupted"),
        (r"invalid", "invalid_input"),
        (r"\brate.?limit|too many requests", "rate_limit"),
        (r"overload", "overloaded"),
        (r"\bauth(?:entication|orization)?\b|unauthorized", "auth"),
        (r"network|connection|could not resolve host", "network"),
    )
)


def identifier(raw, key, required=False):
    value = raw.get(key)
    if isinstance(value, str) and IDENTIFIER.fullmatch(value):
        return value
    if required:
        raise RejectedInput(key)
    return None


def bounded(value, allowed):
    return value if value in allowed else "other" if "other" in allowed else None


def classify_failure(raw):
    text = raw.get("error")
    haystack = text.lower() if isinstance(text, str) else ""
    return next((label for pattern, label in FAILURE_PATTERNS if pattern.search(haystack)), "other")


def event_name(raw):
    name = raw.get("hook_event_name")
    if name not in events.HOOK_EVENTS:
        raise RejectedInput("hook_event_name")
    return name


def prompt_metadata(raw):
    prompt = raw.get("prompt")
    return {"prompt_length_bucket": schema.prompt_length_bucket(len(prompt))} if isinstance(prompt, str) else {}


def batch_metadata(raw):
    calls = raw.get("tool_calls")
    return {"batch_size": len(calls)} if isinstance(calls, list) else {}


def tool_metadata(raw):
    quality = "tool_use_id" if identifier(raw, "tool_use_id") else "none"
    return {"correlation_quality": quality}


def session_metadata(name, raw):
    if name == "SessionStart":
        return {"source": bounded(raw.get("source"), schema.START_SOURCES)}
    return {"end_reason": bounded(raw.get("reason"), schema.END_REASONS)}


def metadata_for(name, raw):
    if name in events.TOOL_EVENTS:
        return tool_metadata(raw)
    if name in events.SUBAGENT_EVENTS:
        return {"agent_id": identifier(raw, "agent_id")}
    if name in ("SessionStart", "SessionEnd"):
        return session_metadata(name, raw)
    extractors = {"UserPromptSubmit": prompt_metadata, "PostToolBatch": batch_metadata}
    return extractors[name](raw) if name in extractors else {}


def build_event(raw, config, now, event_id):
    name = event_name(raw)
    scoped = name in events.TOOL_EVENTS or name in events.SUBAGENT_EVENTS
    return {
        "schema_version": schema.SCHEMA_VERSION,
        "event_id": event_id,
        "event_name": name,
        "occurred_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session_id": identifier(raw, "session_id", required=True),
        "user_id": config.user_id,
        "team_id": config.team_id,
        "repo_id": config.repo_id,
        "tool_name": identifier(raw, "tool_name") if name in events.TOOL_EVENTS else None,
        "tool_use_id": identifier(raw, "tool_use_id") if name in events.TOOL_EVENTS else None,
        "agent_type": identifier(raw, "agent_type") if scoped else None,
        "outcome": events.OUTCOMES.get(name),
        "duration_ms": None,
        "failure_class": classify_failure(raw) if name in events.FAILURE_EVENTS else None,
        "metadata": {key: value for key, value in metadata_for(name, raw).items() if value is not None},
    }
