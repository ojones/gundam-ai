# What the telemetry collects

Status: draft. For now everything stays on one machine: the hook writes to a local spool and the uploader sends to a fake server on localhost. The team-wide parts below (policy owner, server-side deletion) are to be decided before any pilot (see the rollout plan in [initial-specs.md](../initial-specs.md)).

## What is collected

Event name, time, a pseudonymous session key, the organization's pseudonymous user, team and repository keys, tool name and tool-use ID, agent type, a coarse outcome, a bounded failure class, and a few allowlisted metadata fields (the field list is `METADATA_FIELDS` in `telemetry/schema.py`), including the name of each skill that runs. A skill name is recorded when Claude invokes a skill, or when a prompt starts with `/name`; every such name is kept, so a built-in command (for example `/clear`), or a private skill whose name mentions a project or client, is recorded too. Skill arguments and the rest of the prompt are not. Never collected: prompt text, source code, file contents or names, commands, tool arguments or output, Claude's responses, environment variables, credentials.

## How to inspect it

Run `sqlite3 "<spool dir>/spool.sqlite" "select payload from events"`. The spool directory is `~/Library/Application Support/claude-telemetry` on macOS. This shows exactly what has not yet been uploaded. What the local fake server holds is in `~/Library/Application Support/claude-telemetry-ingest/ingested-v4.sqlite` (`sqlite3` on that file, table `ingested`).

## How to disable it

Remove the telemetry hooks from your settings and start a new session. For a team rollout the opt-out policy and its owner are to be decided.

## How to request deletion

On this machine, delete the spool directory (`~/Library/Application Support/claude-telemetry`) and the fake server's directory (`~/Library/Application Support/claude-telemetry-ingest`). For a shared server the process is to be decided with the ingestion owner (retention period and deletion path are open decisions).
