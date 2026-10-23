import math
import sqlite3
import statistics
from pathlib import Path

FINISHED = "('PostToolUse', 'PostToolUseFailure')"
TOP_TOOLS = 30
TOP_SKILLS = 50
RETRY_SECONDS = 60
COUNT_BUCKETS = (("0", 1), ("1-5", 6), ("6-20", 21), ("21-50", 51), ("51+", None))
THURSDAY = "date(occurred_at, '-3 days', 'weekday 4')"
LENGTH_BUCKETS = (("under 5 min", 5), ("5-15 min", 15), ("15-30 min", 30), ("30-60 min", 60), ("1-2 hours", 120), ("over 2 hours", None))
WEEKDAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
WEEK = f"strftime('%Y', {THURSDAY}) || '-W' || printf('%02d', (CAST(strftime('%j', {THURSDAY}) AS INTEGER) - 1) / 7 + 1)"


def open_read_only(path):
    return sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)


def rows(conn, sql):
    return conn.execute(sql).fetchall()


def adoption(conn):
    sql = f"""SELECT {WEEK}, COUNT(DISTINCT CASE WHEN event_name = 'SessionStart' THEN user_id END), COUNT(DISTINCT session_id),
        SUM(event_name = 'UserPromptSubmit') FROM ingested WHERE date(occurred_at) IS NOT NULL GROUP BY 1 ORDER BY 1"""
    return [{"week": week, "users": users, "sessions": sessions, "prompts": prompts} for week, users, sessions, prompts in rows(conn, sql)]


def count(conn, sql):
    return conn.execute(sql).fetchone()[0]


def tool_calls_by(conn, column):
    sql = f"""SELECT COALESCE({column}, '(none)'), COUNT(DISTINCT COALESCE(tool_use_id, event_id)) FROM ingested
        WHERE event_name = 'PreToolUse' GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {TOP_TOOLS}"""
    return dict(rows(conn, sql))


def unmatched_starts(conn):
    return count(conn, f"""SELECT COUNT(DISTINCT tool_use_id) FROM ingested WHERE event_name = 'PreToolUse' AND tool_use_id IS NOT NULL
        AND tool_use_id NOT IN (SELECT tool_use_id FROM ingested WHERE event_name IN {FINISHED} AND tool_use_id IS NOT NULL)""")


def tool_seconds(conn):
    sql = f"""SELECT (julianday(f.occurred_at) - julianday(s.occurred_at)) * 86400 FROM ingested s
        JOIN ingested f ON f.tool_use_id = s.tool_use_id AND f.event_name IN {FINISHED} WHERE s.event_name = 'PreToolUse'"""
    return sorted(round(seconds, 2) for (seconds,) in rows(conn, sql) if seconds is not None and seconds >= 0)


def spread(values):
    if not values:
        return {"median": None, "p90": None}
    return {"median": statistics.median(values), "p90": values[math.ceil(0.9 * len(values)) - 1]}


def retries(conn):
    sql = f"""SELECT COUNT(DISTINCT f.event_id) FROM ingested f JOIN ingested n ON n.session_id = f.session_id
        AND n.tool_name = f.tool_name AND n.event_name = 'PreToolUse' AND n.occurred_at > f.occurred_at
        AND (julianday(n.occurred_at) - julianday(f.occurred_at)) * 86400 <= {RETRY_SECONDS} WHERE f.event_name = 'PostToolUseFailure'"""
    return count(conn, sql)


def workflow_mix(conn):
    return {
        "tools": tool_calls_by(conn, "tool_name"),
        "repos": tool_calls_by(conn, "repo_id"),
        "unmatched_starts": unmatched_starts(conn),
        "durations": spread(tool_seconds(conn)),
        "retries": retries(conn),
        "subagents": count(conn, "SELECT COUNT(*) FROM ingested WHERE event_name = 'SubagentStart'"),
        "subagent_sessions": count(conn, "SELECT COUNT(DISTINCT session_id) FROM ingested WHERE event_name = 'SubagentStart'"),
    }


def skill_counts(conn, event_names):
    marks = ", ".join("?" * len(event_names))
    sql = f"SELECT skill_name, COUNT(*) FROM ingested WHERE event_name IN ({marks}) AND skill_name IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT {TOP_SKILLS}"
    return dict(conn.execute(sql, event_names))


def skills(conn):
    return {"typed": skill_counts(conn, ("UserPromptSubmit",)), "invoked": skill_counts(conn, ("PostToolUse", "PostToolUseFailure"))}


def failure_rates(conn):
    sql = f"""SELECT tool_name, COUNT(DISTINCT CASE WHEN event_name = 'PostToolUseFailure' THEN COALESCE(tool_use_id, event_id) END),
        COUNT(DISTINCT COALESCE(tool_use_id, event_id)) FROM ingested
        WHERE event_name IN {FINISHED} GROUP BY 1 ORDER BY 3 DESC, 1 LIMIT {TOP_TOOLS}"""
    return {tool: {"failed": failed, "total": total} for tool, failed, total in rows(conn, sql)}


def failure_classes(conn, event_name):
    sql = "SELECT failure_class, COUNT(*) FROM ingested WHERE event_name = ? AND failure_class IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1"
    return dict(conn.execute(sql, (event_name,)))


def incomplete_sessions(conn):
    return count(conn, """SELECT COUNT(*) FROM (SELECT session_id FROM ingested GROUP BY 1
        HAVING SUM(event_name = 'SessionStart') > 0 AND SUM(event_name = 'SessionEnd') = 0)""")


def reliability(conn):
    return {
        "failure_rates": failure_rates(conn),
        "failure_classes": failure_classes(conn, "PostToolUseFailure"),
        "api_failures": failure_classes(conn, "StopFailure"),
        "requests": count(conn, "SELECT COUNT(*) FROM ingested WHERE event_name = 'PermissionRequest'"),
        "denials": count(conn, "SELECT COUNT(*) FROM ingested WHERE event_name = 'PermissionDenied'"),
        "incomplete_sessions": incomplete_sessions(conn),
    }


def bucket(value, buckets):
    return next(label for label, limit in buckets if limit is None or value < limit)


def bucketed(values, buckets):
    counts = {label: 0 for label, _ in buckets}
    for value in values:
        counts[bucket(value, buckets)] += 1
    return counts


def events_per_session(conn, event_name):
    sql = "SELECT COUNT(CASE WHEN event_name = ? THEN 1 END) FROM ingested GROUP BY session_id"
    return [found for (found,) in conn.execute(sql, (event_name,))]


def efficiency(conn):
    return {
        "tool_calls": bucketed(events_per_session(conn, "PreToolUse"), COUNT_BUCKETS),
        "prompts": bucketed(events_per_session(conn, "UserPromptSubmit"), COUNT_BUCKETS),
    }


def session_minutes(conn):
    sql = """SELECT session_id, event_name, julianday(occurred_at) FROM ingested
        WHERE event_name IN ('SessionStart', 'SessionEnd') AND julianday(occurred_at) IS NOT NULL ORDER BY 3, 2 DESC"""
    opened, minutes = {}, []
    for session, name, day in rows(conn, sql):
        if name == "SessionStart":
            opened[session] = day
        elif session in opened:
            minutes.append(round((day - opened.pop(session)) * 1440, 2))
    return sorted(minutes)


def session_lengths(conn):
    minutes = session_minutes(conn)
    return {"buckets": bucketed(minutes, LENGTH_BUCKETS), **spread(minutes)}


def prompts_by(conn, pattern, labels):
    sql = f"SELECT CAST(strftime('{pattern}', occurred_at, 'localtime') AS INTEGER), COUNT(*) FROM ingested WHERE event_name = 'UserPromptSubmit' GROUP BY 1"
    found = dict(rows(conn, sql))
    return {label: found.get(number, 0) for number, label in labels}


def rhythm(conn):
    hours = [(hour, f"{hour:02d}:00") for hour in range(24)]
    return {
        "lengths": session_lengths(conn),
        "hours": prompts_by(conn, "%H", hours),
        "weekdays": prompts_by(conn, "%w", list(enumerate(WEEKDAYS))),
    }


def totals(conn):
    sql = "SELECT COUNT(*), COUNT(DISTINCT session_id), MIN(occurred_at), MAX(occurred_at) FROM ingested"
    events, sessions, first, last = conn.execute(sql).fetchone()
    return {"events": events, "sessions": sessions, "first": first, "last": last}


def collect(conn):
    return {
        "totals": totals(conn),
        "adoption": adoption(conn),
        "workflow": workflow_mix(conn),
        "skills": skills(conn),
        "reliability": reliability(conn),
        "efficiency": efficiency(conn),
        "rhythm": rhythm(conn),
    }
