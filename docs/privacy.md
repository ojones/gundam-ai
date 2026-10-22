# What the telemetry collects

Status: draft, to be finished with the team before any pilot (see the rollout plan in [initial-specs.md](../initial-specs.md)).

## What is collected

Event name, time, a pseudonymous session key, the organization's pseudonymous user, team and repository keys, tool name and tool-use ID, agent type, a coarse outcome, a bounded failure class, and a few allowlisted metadata fields (the field list is `METADATA_FIELDS` in `telemetry/schema.py`). Never collected: prompt text, source code, file contents or names, commands, tool arguments or output, Claude's responses, environment variables, credentials.

## How to inspect it

Run `sqlite3 "<spool dir>/spool.sqlite" "select payload from events"`. The spool directory is `~/Library/Application Support/claude-telemetry` on macOS. This shows exactly what has not yet been uploaded.

## How to disable it

Remove the telemetry hooks from the managed settings, or follow the team policy for opting out. Owner of the policy: to be decided.

## How to request deletion

Documented process: to be decided with the ingestion owner (retention period and deletion path are open decisions).
