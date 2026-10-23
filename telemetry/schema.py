SCHEMA_VERSION = 1

ENVELOPE_FIELDS = (
    "schema_version",
    "event_id",
    "event_name",
    "occurred_at",
    "session_id",
    "user_id",
    "team_id",
    "repo_id",
    "tool_name",
    "tool_use_id",
    "agent_type",
    "outcome",
    "duration_ms",
    "failure_class",
    "metadata",
)
METADATA_FIELDS = ("prompt_length_bucket", "batch_size", "correlation_quality", "agent_id", "source", "end_reason", "skill_name")

START_SOURCES = ("startup", "resume", "clear", "compact")
END_REASONS = ("clear", "logout", "prompt_input_exit", "other")
CORRELATION_QUALITIES = ("tool_use_id", "none")
FAILURE_CLASSES = ("timeout", "permission", "not_found", "invalid_input", "interrupted", "rate_limit", "overloaded", "auth", "network", "other")

PROMPT_BUCKETS = (("0-199", 0), ("200-999", 200), ("1000+", 1000))


def prompt_length_bucket(length):
    label = PROMPT_BUCKETS[0][0]
    for name, lower in PROMPT_BUCKETS:
        if length >= lower:
            label = name
    return label
