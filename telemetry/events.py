REQUIRED_EVENTS = (
    "SessionStart",
    "SessionEnd",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PermissionRequest",
    "PermissionDenied",
    "Stop",
    "StopFailure",
    "SubagentStart",
    "SubagentStop",
)
OPTIONAL_EVENTS = ("PostToolBatch",)
HOOK_EVENTS = REQUIRED_EVENTS + OPTIONAL_EVENTS
EXCLUDED_EVENTS = ("MessageDisplay", "PreCompact")

TOOL_EVENTS = frozenset({"PreToolUse", "PostToolUse", "PostToolUseFailure", "PermissionRequest", "PermissionDenied"})
SUBAGENT_EVENTS = frozenset({"SubagentStart", "SubagentStop"})
FAILURE_EVENTS = frozenset({"PostToolUseFailure", "StopFailure"})

OUTCOMES = {
    "PostToolUse": "success",
    "PostToolUseFailure": "failure",
    "PermissionRequest": "requested",
    "PermissionDenied": "denied",
    "Stop": "completed",
    "StopFailure": "failure",
}
