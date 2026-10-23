# Claude Code team telemetry: architecture and coding spec

## Purpose

Build an opt-in, transparent telemetry system that helps an engineering team understand how Claude Code is used, how its tool workflows behave, where sessions encounter failures, and whether people run validation steps. The system must not collect prompt text, source code, file contents, or raw tool arguments by default. It must not change Claude Code's decisions or block a developer's work.

Treat the metrics as workflow indicators, not individual productivity scores. High activity, low activity, or a particular tool mix is not by itself evidence of success or performance.

## Current scope

This implementation runs locally on one developer's machine against a fake ingestion endpoint on localhost. The collector, spool, uploader, local dashboard and context-size reminders are built. The rollout plan and the open deployment decisions below describe the later team deployment; they have not started and nothing in the local build depends on them.

## Recommendation: Python collector, Claude Code command hooks

Use **Python for the event collector, local queue, uploader, and reporting transforms**. It is a good fit for JSON processing, SQLite, HTTP clients, and data pipelines, and it matches the maintainer's preference. Claude Code runs command hooks, so the collector can be launched by a `python3`/`python` command; shell should only be used for a thin platform launcher if needed.

TypeScript is also viable, especially if the team already distributes Node tooling or wants a typed Node service. It does not offer a clear advantage for this local queue and uploader. Shell alone is a poor fit for robust JSON filtering, SQLite queue management, retries, and cross-platform behavior. Do not use shell to parse arbitrary prompts or tool payloads.

Before rollout, verify that Python 3.10+ is available on all supported developer machines, or package the collector as a small executable. If that is not true, choose the team's already-managed runtime (Node/TypeScript may then be simpler to deploy).

## Architecture

```text
Claude Code lifecycle events
        │
        ▼
async command hooks (no decisions, no tool blocking)
        │ stdin: event JSON
        ▼
Python collector ── redact/allowlist fields ──► local SQLite spool
                                                   │
                                     background uploader batches/retries
                                                   │ HTTPS + auth
                                                   ▼
                                  shared ingestion API / queue
                                                   │
                                                   ▼
                                      warehouse and dashboard
```

The hook process performs only bounded local work: parse stdin, retain allowlisted metadata, insert one row into SQLite, and exit. A separate, long-lived user-level service or scheduled worker drains the queue in batches. The Claude session never waits for a network request. If the ingestion service is unavailable, queued records remain locally until a later successful upload, subject to retention and disk limits.

The local spool should live in a user data/cache directory (for example, the platform's standard application data directory), not in the repository. Use SQLite WAL mode, short transactions, a bounded database size, and a cleanup policy. Do not create an unbounded JSONL file. Protect the spool with user-only filesystem permissions where supported.

The uploader should use HTTPS, a short connection/read timeout, exponential backoff with jitter, a maximum batch size, and an idempotency key per event. Authentication should come from the organization's standard secret or device identity mechanism; never place credentials in committed settings or hook arguments. The ingestion API should authenticate the client, validate schema/version, rate-limit, and reject unexpected fields.

## Hook event coverage

Register a shared telemetry command for the following events in managed Claude Code settings where possible. Mark every telemetry command hook `"async": true`; do not configure telemetry on any decision-making path.

| Event | Captures | Metrics supported |
| --- | --- | --- |
| `SessionStart` | session ID, start time, start source, project/repository key | active users, sessions, session starts/resumes |
| `SessionEnd` | session ID, end time, end reason | session duration, termination reasons |
| `UserPromptSubmit` | prompt length bucket only; never prompt text | prompts per session, prompts per session-length bucket |
| `PreToolUse` | tool name, tool-use ID, timestamp, agent ID/type when present | tool starts, workflow sequence, subagent tool activity |
| `PostToolUse` | tool name, tool-use ID, timestamp, normalized success event | successful tool calls, tool duration when paired with start |
| `PostToolUseFailure` | tool name, tool-use ID, timestamp, normalized failure class | tool failures, retry patterns |
| `PermissionRequest` / `PermissionDenied` | tool name, decision/result category, timestamp | permission requests, denials, approval friction |
| `Stop` / `StopFailure` | turn completion or normalized API failure category | completed turns, API failures, session outcome signals |
| `SubagentStart` / `SubagentStop` | agent type, agent ID, timestamp | subagent adoption, duration, outcome counts |
| `PostToolBatch` (optional) | batch size and normalized statuses only | parallel tool-call patterns |

Avoid `MessageDisplay` and `PreCompact` initially. They add little to the first dashboard and increase the chance of collecting message content or unnecessary high-volume events. Add other events only for a named metric and after privacy review.

### Important event-model details

- Claude Code hook inputs contain sensitive fields such as prompts, tool input, and tool output. The collector must build a new event from an explicit allowlist; it must never forward the input JSON wholesale.
- Use `session_id` and `tool_use_id` to correlate events. Where tool IDs are unavailable, use a local generated event ID and mark correlation quality.
- Record UTC wall-clock timestamps for storage. Use a monotonic clock for local start/end duration calculations when events share a host. Do not calculate durations from unsynchronized machines.
- Hook invocations can be duplicated, missing, reordered, or canceled when a non-interactive Claude process exits. Make ingestion idempotent and metrics tolerant of incomplete event pairs.
- `Stop` means Claude finished a response, not that the engineering task succeeded. `PostToolUse` on a test command does not necessarily prove tests passed unless a trustworthy result is explicitly parsed. Prefer CI status as the authoritative validation outcome.

## Event schema

All events use a versioned, minimal envelope. Example fields:

```json
{
  "schema_version": 1,
  "event_id": "uuid",
  "event_name": "PostToolUse",
  "occurred_at": "2026-10-21T17:00:00Z",
  "session_id": "pseudonymous-session-key",
  "user_id": "organization-managed-pseudonymous-user-key",
  "team_id": "engineering",
  "repo_id": "organization-approved-repository-key",
  "tool_name": "Bash",
  "tool_use_id": "tool-call-id",
  "agent_type": null,
  "outcome": "success",
  "duration_ms": null,
  "failure_class": null,
  "metadata": {"prompt_length_bucket": null, "skill_name": null}
}
```

Requirements:

- `event_id` is unique and stable across upload retries.
- User identity is a pseudonymous stable key supplied by the organization, not an email or display name. Keep identity mapping outside the telemetry store and restrict access to it.
- Repository identity should be a configured repository slug or keyed hash. Do not send arbitrary paths, remote URLs, branch names, or file paths by default.
- `metadata` has a strict allowlist. Prompt length should be coarse buckets (for example, `0-199`, `200-999`, `1000+`), not exact text or a recoverable representation.
- `skill_name` records which skill ran, as an identifier only (letters, digits and `_ . : -`, at most 128 characters; a plugin prefix such as `plugin:skill` is kept). It is set on tool events where `tool_name` is `Skill` (the name Claude invoked) and on `UserPromptSubmit` when the prompt begins with `/name` followed by whitespace or the end of the prompt (a skill or command the developer typed). Skill arguments, the rest of the prompt and any other tool input are never collected. Every skill name is recorded; a name that is not a skill (a built-in command, or a private skill whose name reveals a project) is recorded like any other, which the privacy notice states.
- Normalize failures to bounded categories; do not store stack traces, shell stderr, tool result text, or API error bodies.
- Never collect environment variables, authentication data, raw commands, file names, code diffs, prompt text, or Claude's response text in the baseline deployment.

## Metric definitions

### Adoption and activity

- Active users per day/week: distinct pseudonymous users with at least one `SessionStart`.
- Sessions per user and repository: count of unique session IDs.
- Session duration: `SessionEnd` minus `SessionStart`; report median and percentiles, excluding incomplete sessions or showing them separately. Show the distribution in coarse length buckets (under 5 minutes, 5 to 15, 15 to 30, 30 to 60, 1 to 2 hours, over 2 hours).
- Time of day: `UserPromptSubmit` counts by hour of day and by day of week, derived from `occurred_at` and shown in the time zone of the machine that renders the dashboard. This adds no event field. It describes when the team works, not how well; label it a proxy, never target it, and do not break it down per person.
- Prompts per session: count `UserPromptSubmit` events; report a distribution, not a target.

### Workflow patterns

- Tool calls by tool name and repository: count `PreToolUse`, deduplicated by tool-use ID.
- Tool success/failure rate: join `PostToolUse` and `PostToolUseFailure` to tool-use IDs; show unmatched starts separately.
- Tool duration: pair start/completion timestamps where supported; present medians and percentiles.
- Skill usage: count of invocations per `skill_name`, separately for skills Claude invoked (`PostToolUse` or `PostToolUseFailure` with `tool_name` `Skill`, so a skill that fails still counts) and skills the developer typed (`UserPromptSubmit`), so a skill reached both ways is not silently counted once. Show totals only, not per user.
- Subagent usage: sessions with `SubagentStart`, starts per session, and duration/outcome where pairing is possible.
- Validation activity: count eligible test/lint/type-check commands only if tool inputs can be mapped to a safe, fixed command category without retaining raw commands. Display as “validation command observed,” not “tests passed,” unless independently verified by CI.

### Reliability and friction

- API failure rate by normalized `StopFailure` category.
- Tool failure rate by tool category and normalized error class.
- Permission request and denial rates, with trends over time.
- Retry indicator: repeated attempts at the same tool category in a session within a short time window. Label this as a heuristic; do not infer user error.

### Efficiency indicators

- Tool calls, failures, and retries per completed turn/session.
- Time from session start to first tool call and from first tool call to session end.
- Validation-command frequency and CI pass/fail outcomes when joined from CI.

Do not publish a composite “engineer productivity” score. Compare team or repository trends over time, and segment by task type only when the team has an explicit, non-sensitive taxonomy.

## Collector behavior

Implement a Python package with these components:

```text
telemetry/
├── hook.py          # stdin parsing, allowlist/redaction, SQLite enqueue
├── queue.py         # schema, migrations, dedupe, retention, bounded storage
├── uploader.py      # batching, auth, retries, acknowledgements
├── service.py       # user-level background service entry point
├── config.py        # environment/config validation; no secrets in repo
├── context_size.py  # context-size reading and thresholds shared by the two below
├── context_nudge.py # optional context-size nudge hooks (not telemetry)
├── statusline.py    # optional status line segment showing context size
└── tests/
```

`hook.py` must:

1. Read one JSON object from stdin with a strict size limit.
2. Validate the event name and required identifiers.
3. Extract only approved fields into the schema; discard all other input.
4. Hash/pseudonymize IDs locally only if the organization supplies a managed key and stable identity source. Never invent identity from a username or path.
5. Insert into SQLite with a short busy timeout and commit.
6. Exit promptly with no stdout output and no decision JSON. Telemetry errors go to a bounded local diagnostic log with redacted messages; they must not be fed back to Claude.
7. Never block, deny, approve, or alter a prompt/tool call.

If SQLite is locked or unavailable, the hook should drop the event, increment a local dropped-event counter if possible, and exit. Do not wait for network or retry synchronously in the hook. The uploader retries queued events; dropped counts make telemetry loss visible.

`uploader.py` must:

- Claim a bounded batch transactionally, send it with an idempotency key, and delete/mark acknowledged rows only after a successful response.
- Retry retryable network errors and server errors with exponential backoff and jitter; do not retry permanent schema/authentication errors indefinitely.
- Apply a maximum queue age and maximum disk size; report counts of expired/dropped events without including payloads.
- Support clean shutdown and avoid duplicate concurrent uploaders with a lock/lease.
- Expose health (last successful upload, queue depth, dropped/expired count) locally, without a public unauthenticated listener.

## Claude Code settings

Managed settings should point to a single telemetry command and register it only for the selected events. Use async command hooks so the session does not wait. Keep paths and command syntax compatible with each supported OS; if necessary, ship a small Python executable or per-platform launcher.

Conceptual pattern (the exact event groups and command path will be finalized for the deployment):

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /managed/path/telemetry/hook.py",
            "async": true
          }
        ]
      }
    ]
  }
}
```

Use equivalent groups for other events. Do not add telemetry to `PreToolUse` unless needed to pair start times; if used, keep it async and metadata-only. Do not use async output to inject context: the collector should emit no response fields.

## Context-size nudge

Two optional ways to remind a developer to hand off a long session. Neither is part of the telemetry pipeline: they record no event, reach no spool or network, and are never registered in managed telemetry settings. They exist so engineers keep working without being blocked, so neither may add noticeable latency to a prompt.

Shared rules:

- Context size is the sum of `input_tokens`, `cache_read_input_tokens` and `cache_creation_input_tokens` of the most recent main-thread assistant message. Only these numbers are read; no transcript content is kept, logged or forwarded.
- The first threshold is 100000 tokens, then one more each time the size passes another 50000 (150000, 200000, and so on). A reminder may arrive up to one turn late.
- Any failure (missing transcript, unreadable usage, unwritable state) produces no output and exit status 0.

Status line segment (`statusline.py`):

- Reads `context_window.total_input_tokens` from the status line input, so it parses no transcript and keeps no state.
- Shows the size in thousands of tokens, dimmed below 100000, amber from 100000 and red from 150000, with a short hint to consider a handoff once past 100000. It is passive: it never talks to Claude.

Hooks (`context_nudge.py`):

- An async `Stop` command (`record`) reads the transcript tail once per turn, off the prompt path. When the size passes a threshold not yet announced in this session it leaves a small pending file; it never writes output.
- A synchronous `UserPromptSubmit` command (`deliver`) only checks for that pending file. If present it removes it and returns `additionalContext` asking Claude to tell the developer, in one sentence, the approximate token count and that they can run the handoff skill to continue in a fresh session. Otherwise it exits at once. This is the one place the "no response fields" rule for telemetry commands does not apply, and it must stay a different command from the telemetry collector. It never blocks or alters the prompt.
- The highest announced threshold is kept per session in the user data directory. If the context shrinks (for example after compaction) the stored threshold drops with it, so growth past a threshold fires again.

## Dashboard and data access

Start with aggregate views:

1. Adoption trend: active users, sessions, and prompts by week; session length distribution and prompts by hour of day and day of week.
2. Workflow mix: tool calls by category, skill invocations by skill name, subagent use, and validation-command observed rate.
3. Reliability: tool/API failure rates, permission denials, unmatched/incomplete sessions.
4. Efficiency indicators: session and tool-duration distributions, calls/retries per session.
5. CI join: validation outcomes from the CI system, keyed by repository and commit/PR reference if the organization approves that linkage.

Use minimum group-size thresholds for team comparisons. Restrict row-level event access to telemetry operators; provide managers aggregate views by default. Set a documented retention period and deletion process. Make the collection purpose, fields, access, and retention visible to engineers before enabling collection.

## Performance and reliability targets

- The Claude session waits for no telemetry work because each collector command is asynchronous.
- Collector work is local-only and bounded; target p95 under 100 ms, with no network request from hook processes.
- Hook input has a configurable maximum size; oversize input is discarded after extracting no content.
- Queue storage is bounded and local failure never affects Claude Code actions.
- Dashboard data is eventually consistent; do not promise real-time visibility.
- Track event delivery rate and loss indicators so apparent workflow trends are not mistaken for missing telemetry.

## Rollout plan

Status: step 1 (local prototype) is done; steps 2 to 5 have not started.

1. **Local prototype:** use a disposable local SQLite queue and a fake ingestion endpoint; inspect emitted records to confirm that sensitive fields are absent.
2. **Pilot:** enable for a small volunteer group, publish the metric definitions and privacy notice, and measure hook process overhead, queue growth, and delivery success.
3. **Tune:** reduce event volume, revise buckets, fix platform issues, and verify that uploads survive sleep, network loss, and session shutdown.
4. **Team deployment:** distribute through managed settings and the organization's standard endpoint/auth mechanism. Version the collector and schema together.
5. **Review:** periodically audit captured fields, dashboard access, retention, and whether each metric is still useful.

## Acceptance criteria for implementation

- Hook config uses async command hooks for telemetry events and contains no decision controls.
- The Claude tool/prompt flow continues if the collector, local database, network, or ingestion service fails.
- Unit tests prove prompt text, tool arguments, tool output, paths, and secrets never enter stored or uploaded events.
- Tests cover malformed/oversize JSON, duplicate delivery, SQLite lock/failure, queue limits, retries, permanent HTTP errors, and schema migrations.
- A sample event can be followed end-to-end from hook input through local queue, ingestion, and aggregate dashboard.
- Engineers can inspect what is collected, disable telemetry according to team policy, and request deletion through a documented process.
- Published dashboards label proxies accurately and do not claim that session activity alone measures productivity or code quality.

## Open deployment decisions

Status: all undecided. The local build codes against a fake endpoint and keeps these choices behind `config.py`.

The implementation can be written independently of these choices, but connecting it to a real team requires:

- Shared ingestion endpoint or managed queue and its owner.
- Identity source and pseudonymization/key management.
- Repository identifier policy.
- Supported operating systems and Python distribution method.
- Storage/warehouse and dashboard platform.
- Retention duration, access roles, and minimum aggregation threshold.
- Whether CI outcomes will be joined, and which stable repository/PR keys may be used.
