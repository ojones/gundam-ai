# Invariants

The "must" rules of the collector, each with an ID. `telemetry/invariants_test.py` has one test per row, named `test_invNN_...`, and `telemetry/spec_sync_test.py` checks that this table and the test file list exactly the same IDs. A row marked `pending` has a skipped test; when you implement it, remove the skip and change the row to `implemented` in the same change (a test fails if the two disagree). The Spec column names the section of [initial-specs.md](../initial-specs.md) that the rule comes from, and the AC column names the acceptance criterion it helps satisfy (numbered in order from the "Acceptance criteria" section of the spec; a test checks that every criterion is covered).

| ID | Rule | Spec | AC | Status |
|---|---|---|---|---|
| INV-01 | An event is built from an explicit allowlist: content placed in prompt, tool input, tool output, cwd, transcript path or environment fields never appears in the built event. | Important event-model details | AC-03 | implemented |
| INV-02 | A built event has exactly the envelope fields, and its metadata keys are inside the metadata allowlist. | Event schema | AC-03 | implemented |
| INV-03 | The hook prints nothing to stdout and returns 0 for valid, malformed, oversize and failing-storage input. | Collector behavior | AC-02 | implemented |
| INV-04 | The managed settings the package generates register only async command hooks and contain no decision controls. | Claude Code settings | AC-01 | implemented |
| INV-05 | Delivering the same `event_id` twice leaves one queued row. | Event schema | AC-04 | implemented |
| INV-06 | The spool is bounded: once the database file reaches its limit new events are dropped and counted. | Architecture | AC-04 | implemented |
| INV-07 | Oversize hook input is dropped and counted without extracting anything from it. | Performance and reliability targets | AC-04 | implemented |
| INV-08 | The spool directory is readable by the owner only. | Architecture | AC-03 | implemented |
| INV-09 | A prompt is recorded only as a coarse length bucket (`0-199`, `200-999`, `1000+`). | Event schema | AC-03 | implemented |
| INV-10 | A failure is recorded only as one of a bounded set of classes; error text is never stored. | Event schema | AC-03 | implemented |
| INV-11 | Nothing the hook process imports can open a network connection. | Architecture | AC-02 | implemented |
| INV-12 | `user_id`, `team_id` and `repo_id` come only from configuration; with none supplied they are null, never derived from a username or path. | Collector behavior | AC-03 | implemented |
| INV-13 | A spool at an older schema version is migrated to the latest on open, keeping its rows. | Acceptance criteria | AC-04 | implemented |
| INV-14 | A claimed row is not claimed again until its lease expires, and an acknowledged row is deleted. | Collector behavior (uploader) | AC-04 | implemented |
| INV-15 | Rows older than the maximum queue age are deleted and counted as expired. | Collector behavior (uploader) | AC-04 | implemented |
| INV-16 | HTTP statuses classify as ok, retry or permanent, and the backoff delay is jittered and capped. | Collector behavior (uploader) | AC-04 | implemented |
| INV-17 | When the database is locked by another process the hook drops the event and still returns 0. | Collector behavior | AC-02 | implemented |
| INV-18 | The uploader deletes rows only after a success response, retries retryable errors, and gives up on permanent errors. | Collector behavior (uploader) | AC-04 | implemented |
| INV-19 | At most one uploader drains the spool at a time. | Collector behavior (uploader) | AC-04 | implemented |
| INV-20 | Health (last upload, queue depth, dropped, expired) is available locally without a network listener. | Collector behavior (uploader) | AC-04 | implemented |
| INV-21 | A sample event can be followed from hook input through the queue and a fake ingestion endpoint to an aggregate. | Acceptance criteria | AC-05 | implemented |
| INV-22 | The privacy notice says what is collected, how to inspect it, how to disable it and how to request deletion. | Dashboard and data access | AC-06 | implemented |
| INV-23 | Dashboards label proxy metrics as proxies and publish no composite productivity score. | Metric definitions | AC-07 | pending |
