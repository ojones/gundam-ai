from datetime import datetime, timezone

LOG_NAME = "diagnostics.log"
MAX_LOG_BYTES = 100_000


def record(spool_dir, code, error=None):
    spool_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    log = spool_dir / LOG_NAME
    if log.exists() and log.stat().st_size >= MAX_LOG_BYTES:
        return
    kind = type(error).__name__ if error is not None else "-"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with log.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp} {code} {kind}\n")
