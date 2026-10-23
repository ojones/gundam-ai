import json
import os
import sys
from pathlib import Path

from telemetry import allowlist, context_size
from telemetry import config as config_module

MAX_INPUT_BYTES = 1_048_576
HANDOFF_SKILL = "/mattpocock-skills:handoff"
STATE_DIR = "context-nudge"
SEEN = "seen"
PENDING = "pending"


def read_number(path):
    if not path.is_file():
        return 0
    text = path.read_text(encoding="utf-8").strip()
    return int(text) if text.isdigit() else 0


def write_number(path, number):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(number), encoding="utf-8")


def message_for(tokens):
    return (
        f"The context is now about {tokens // 1000}k tokens. Before answering, tell the user in one sentence "
        f"that the session is getting long and that they can run {HANDOFF_SKILL} to continue in a fresh session."
    )


def session_dir(raw, state_dir):
    session_id = allowlist.identifier(raw, "session_id")
    return state_dir / session_id if session_id else None


def transcript_tokens(raw):
    transcript = raw.get("transcript_path")
    if not isinstance(transcript, str) or not Path(transcript).is_file():
        return None
    return context_size.context_tokens(Path(transcript))


def record(raw, state_dir):
    folder, tokens = session_dir(raw, state_dir), transcript_tokens(raw)
    if folder is None or tokens is None:
        return
    level, seen = context_size.threshold_for(tokens), read_number(folder / SEEN)
    if level != seen:
        write_number(folder / SEEN, level)
    if level > seen:
        write_number(folder / PENDING, tokens)


def deliver(raw, state_dir):
    folder = session_dir(raw, state_dir)
    if folder is None or not (folder / PENDING).is_file():
        return None
    tokens = read_number(folder / PENDING)
    (folder / PENDING).unlink()
    return message_for(tokens) if tokens else None


def response(message):
    return json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": message}})


def run(mode, stream, env):
    raw = context_size.parse_object(stream.read(MAX_INPUT_BYTES).decode("utf-8", errors="replace"))
    state_dir = config_module.load_config(env).spool_dir / STATE_DIR
    if mode == "record":
        return record(raw, state_dir)
    message = deliver(raw, state_dir)
    return response(message) if message else None


def main(argv):
    try:
        output = run(argv[0] if argv else "", sys.stdin.buffer, os.environ)
    except Exception:  # noqa: BLE001
        return 0
    if output:
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
