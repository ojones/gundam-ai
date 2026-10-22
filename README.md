# gundam-ai

Opt-in, transparent Claude Code team telemetry. It records workflow metadata (which events happened, which tools ran, whether they failed) and never prompt text, code, file names, commands, tool output or Claude's responses.

Developers: start with [CLAUDE.md](CLAUDE.md). The spec is [initial-specs.md](initial-specs.md), the architecture decisions are in [docs/decisions.md](docs/decisions.md), and what is collected is in [docs/privacy.md](docs/privacy.md).

## Status

Capture and upload work locally: hooks feed a SQLite spool, an uploader sends batches to a fake ingestion server on `localhost:8080`. **Nothing leaves your machine.** Cloud infrastructure is a later step (DEC-14).

Run the local stack: `make token` once, then `make ingest` and `make uploader` in two terminals (or `make install-local` to run both under launchd). `make health` shows queue depth and upload status; `make aggregate` shows what the fake server ingested.

## Use it in a live session

Requires Python 3.10+ and a checkout of this repo. No packages to install.

### 1. Add the hooks

Print the settings block, pointing the command at your checkout:

```sh
python3 -c "
import json
from telemetry.managed_settings import managed_settings
print(json.dumps(managed_settings('PYTHONPATH=$PWD python3 -m telemetry.hook'), indent=2))"
```

Merge the `hooks` entries into `~/.claude/settings.json` (user-wide) or a project's `.claude/settings.json`. If you already have hooks for the same events, add this command to the existing list instead of replacing it. Every entry is `"async": true`, so Claude never waits for telemetry and the hook cannot approve, deny or change anything.

Start a new Claude Code session afterwards; hooks are read at session start. Run `/hooks` inside the session to confirm they are registered.

### 2. Optional settings

Set these in the environment Claude Code starts from (your shell profile, or the `env` key of settings.json):

| Variable | Meaning | Default |
|---|---|---|
| `TELEMETRY_SPOOL_DIR` | Where the spool lives | `~/Library/Application Support/claude-telemetry` |
| `TELEMETRY_USER_ID`, `TELEMETRY_TEAM_ID`, `TELEMETRY_REPO_ID` | Pseudonymous keys supplied by your organization. Without them the fields are null; nothing is guessed from your username or paths | unset |
| `TELEMETRY_MAX_DB_BYTES` | Spool size cap; new events are dropped past it | 50 MB |
| `TELEMETRY_MAX_INPUT_BYTES` | Hook input size cap; larger input is dropped unread | 1 MiB |

### 3. See what is being collected

Everything waiting to be uploaded is in the spool, as plain JSON:

```sh
SPOOL="$HOME/Library/Application Support/claude-telemetry/spool.sqlite"
sqlite3 "$SPOOL" "select payload from events order by id desc limit 5"
sqlite3 "$SPOOL" "select event_name, count(*) from (select json_extract(payload,'$.event_name') as event_name from events) group by 1"
```

### 4. Check health

```sh
sqlite3 "$SPOOL" "select count(*) as queued from events; select name, value from counters"
```

`counters` shows telemetry loss: `dropped_invalid`, `dropped_oversize`, `dropped_full`, `dropped_error` and `expired`. Hook errors, if any, are in `diagnostics.log` beside the spool; each line has a time, a code and an error class name, never a message or payload. Empty output after a session means the hooks are not registered or the command path is wrong. Run the command by hand to check:

```sh
echo '{"hook_event_name":"Stop","session_id":"test"}' | PYTHONPATH=/path/to/gundam-ai python3 -m telemetry.hook; echo $?
```

It should print nothing and exit 0.

### 5. Turn it off or clear it

- Stop collecting: remove the telemetry hooks from settings.json and start a new session.
- Delete what is stored locally: remove the spool directory.
- Server-side deletion: the process is not decided yet (see docs/privacy.md).

## What to expect

- The hook adds no waiting to your session. If the spool is locked, full or broken, the event is dropped and counted; your session carries on.
- `Stop` means Claude finished a response, not that your task succeeded. The metrics are workflow indicators, not a measure of individual productivity.

## Developing

```sh
make check    # ruff + unit tests + spec/doc sync tests
```
