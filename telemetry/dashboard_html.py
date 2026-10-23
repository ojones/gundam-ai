from html import escape

STYLE = """body{font:15px system-ui,sans-serif;max-width:56rem;margin:2rem auto;padding:0 1rem;color:#1a1a1a;background:#fff}
@media(prefers-color-scheme:dark){body{color:#e8e8e8;background:#161616}}
h2{margin:2rem 0 .25rem}.proxy{margin:0 0 .75rem;opacity:.7;font-size:.9em}
table{border-collapse:collapse;width:100%}td,th{padding:.2rem .5rem;text-align:left}
.bar{display:inline-block;height:.8rem;background:#4a7fd4;vertical-align:middle}"""
NOTES = {
    "adoption": "Proxy: counts of activity, not of value delivered. Eventually consistent.",
    "workflow": "Proxy: which tools ran, not how well the work went. Retry-like repeats are a heuristic (the same tool again within 60 seconds of a failure) and do not imply user error. Durations pair start and finish times from one store, so treat them as approximate.",
    "skills": "Proxy: how often a skill ran, not whether it helped. Totals only; the same skill reached both ways appears in both lists.",
    "rhythm": "Proxy: when sessions happen and how long they last describe working patterns, not effort or quality. Times use the time zone of the machine showing this page.",
    "reliability": "Proxy: failures as reported by hooks. A session without an end may simply still be running, so that count is an upper bound.",
    "efficiency": "Proxy: tool calls per session reflect task shape as much as efficiency.",
}


def cell(value):
    return f"<td>{escape(str(value))}</td>"


def row(*values):
    return "<tr>" + "".join(map(cell, values)) + "</tr>"


def bar(count, peak):
    width = round(200 * count / peak) if peak else 0
    return f'<td><span class="bar" style="width:{width}px"></span></td>'


def bars(counts):
    peak = max(counts.values(), default=0)
    body = "".join(f"<tr>{cell(name)}{cell(count)}{bar(count, peak)}</tr>" for name, count in counts.items())
    return f"<table>{body}</table>"


def section(key, title, body):
    return f'<section id="{key}"><h2>{escape(title)}</h2><p class="proxy">{escape(NOTES[key])}</p>{body}</section>'


def adoption_table(weeks):
    head = "<tr><th>Week</th><th>Active users</th><th>Sessions</th><th>Prompts</th></tr>"
    body = "".join(row(w["week"], w["users"], w["sessions"], w["prompts"]) for w in weeks)
    return f"<table>{head}{body}</table>"


def failure_table(rates):
    head = "<tr><th>Tool</th><th>Failed</th><th>Total</th><th>Rate</th></tr>"
    body = "".join(row(tool, r["failed"], r["total"], f"{r['failed'] / r['total']:.0%}") for tool, r in rates.items())
    return f"<table>{head}{body}</table>"


def reliability_body(data):
    counts = {"Permission requests": data["requests"], "Permission denials": data["denials"], "Sessions without an end": data["incomplete_sessions"]}
    parts = [failure_table(data["failure_rates"]), "<h3>Tool failure classes</h3>", bars(data["failure_classes"]), "<h3>API failures (StopFailure)</h3>", bars(data["api_failures"])]
    return "".join(parts) + "<h3>Friction</h3>" + bars(counts)


def spread_line(label, spread, unit):
    if spread["median"] is None:
        return f"<p>{escape(label)}: none yet</p>"
    return f"<p>{escape(label)}: median {spread['median']:.0f} {unit}, 90th percentile {spread['p90']:.0f} {unit}</p>"


def workflow_body(data):
    counts = {"Subagent starts": data["subagents"], "Sessions with a subagent": data["subagent_sessions"], "Starts with no finish": data["unmatched_starts"], "Retry-like repeats (heuristic)": data["retries"]}
    parts = ["<h3>Tool calls by tool</h3>", bars(data["tools"]), "<h3>Tool calls by repository</h3>", bars(data["repos"])]
    return "".join(parts) + spread_line("Tool duration", data["durations"], "s") + bars(counts)


def efficiency_body(data):
    return "<h3>Sessions by number of tool calls</h3>" + bars(data["tool_calls"]) + "<h3>Sessions by number of prompts</h3>" + bars(data["prompts"])


def skills_body(data):
    return "<h3>Typed by the developer (/name)</h3>" + bars(data["typed"]) + "<h3>Invoked by Claude</h3>" + bars(data["invoked"])


def rhythm_body(data):
    lengths = data["lengths"]
    parts = ["<h3>Session length</h3>", bars(lengths["buckets"]), spread_line("Completed sessions", lengths, "min")]
    return "".join(parts) + "<h3>Prompts by hour</h3>" + bars(data["hours"]) + "<h3>Prompts by day of week</h3>" + bars(data["weekdays"])


def summary(totals):
    span = f"{totals['first']} to {totals['last']}" if totals["events"] else "no events yet"
    return f"<p>{totals['events']} events in {totals['sessions']} sessions ({escape(span)}). Aggregates only; no composite metric is computed.</p>"


def render(data):
    parts = [
        summary(data["totals"]),
        section("adoption", "Adoption by week", adoption_table(data["adoption"])),
        section("workflow", "Workflow mix", workflow_body(data["workflow"])),
        section("rhythm", "Session length and time of day", rhythm_body(data["rhythm"])),
        section("skills", "Skills", skills_body(data["skills"])),
        section("reliability", "Reliability", reliability_body(data["reliability"])),
        section("efficiency", "Efficiency indicators", efficiency_body(data["efficiency"])),
    ]
    return f"<!doctype html><meta charset=utf-8><title>Claude Code telemetry</title><style>{STYLE}</style><h1>Claude Code telemetry</h1>{''.join(parts)}"
