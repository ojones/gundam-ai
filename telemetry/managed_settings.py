import json

from telemetry import events

DEFAULT_COMMAND = "python3 -m telemetry.hook"


def hook_group(command):
    return [{"matcher": "*", "hooks": [{"type": "command", "command": command, "async": True}]}]


def managed_settings(command=DEFAULT_COMMAND, include_optional=False):
    names = events.HOOK_EVENTS if include_optional else events.REQUIRED_EVENTS
    return {"hooks": {name: hook_group(command) for name in names}}


if __name__ == "__main__":
    print(json.dumps(managed_settings(), indent=2))
