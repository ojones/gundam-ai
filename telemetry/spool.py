import sqlite3
import time

MIGRATIONS = (
    """
    CREATE TABLE events (
        id INTEGER PRIMARY KEY,
        event_id TEXT UNIQUE NOT NULL,
        payload TEXT NOT NULL,
        created_at REAL NOT NULL,
        claimed_until REAL NOT NULL DEFAULT 0
    );
    CREATE TABLE counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
    """,
)
LEASE_SECONDS = 300


def migrate(conn):
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
        conn.executescript(script)
        conn.execute(f"PRAGMA user_version = {number}")


def open_spool(config):
    config.spool_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    config.spool_dir.chmod(0o700)
    conn = sqlite3.connect(config.spool_path, timeout=config.busy_timeout_ms / 1000, isolation_level=None)
    conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


def bump_counter(conn, name, amount=1):
    conn.execute(
        "INSERT INTO counters(name, value) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET value = value + excluded.value",
        (name, amount),
    )


def set_counter(conn, name, value):
    conn.execute("INSERT INTO counters(name, value) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET value = excluded.value", (name, value))


def counter(conn, name):
    row = conn.execute("SELECT value FROM counters WHERE name = ?", (name,)).fetchone()
    return row[0] if row else 0


def database_bytes(config):
    return config.spool_path.stat().st_size if config.spool_path.exists() else 0


def enqueue(conn, config, event_id, payload, now=None):
    if database_bytes(config) >= config.max_db_bytes:
        bump_counter(conn, "dropped_full")
        return False
    created = time.time() if now is None else now
    cursor = conn.execute("INSERT OR IGNORE INTO events(event_id, payload, created_at) VALUES (?, ?, ?)", (event_id, payload, created))
    return cursor.rowcount == 1


def queue_depth(conn):
    return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]


def claim_batch(conn, limit, now=None):
    current = time.time() if now is None else now
    conn.execute("BEGIN IMMEDIATE")
    rows = conn.execute("SELECT event_id, payload FROM events WHERE claimed_until <= ? ORDER BY id LIMIT ?", (current, limit)).fetchall()
    conn.executemany("UPDATE events SET claimed_until = ? WHERE event_id = ?", [(current + LEASE_SECONDS, event_id) for event_id, _ in rows])
    conn.execute("COMMIT")
    return rows


def acknowledge(conn, event_ids):
    conn.executemany("DELETE FROM events WHERE event_id = ?", [(event_id,) for event_id in event_ids])


def release(conn, event_ids):
    conn.executemany("UPDATE events SET claimed_until = 0 WHERE event_id = ?", [(event_id,) for event_id in event_ids])


def reject(conn, event_ids):
    acknowledge(conn, event_ids)
    bump_counter(conn, "rejected", len(event_ids))


def expire_older_than(conn, cutoff):
    cursor = conn.execute("DELETE FROM events WHERE created_at < ?", (cutoff,))
    bump_counter(conn, "expired", cursor.rowcount)
    return cursor.rowcount


def dropped_total(conn):
    return sum(counter(conn, f"dropped_{reason}") for reason in ("full", "invalid", "oversize", "error"))


def health(conn):
    return {
        "queue_depth": queue_depth(conn),
        "dropped": dropped_total(conn),
        "expired": counter(conn, "expired"),
        "rejected": counter(conn, "rejected"),
        "last_upload_at": counter(conn, "last_upload_at"),
    }
