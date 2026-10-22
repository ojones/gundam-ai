import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
SPOOL_FILE = "spool.sqlite"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    spool_dir: Path
    max_input_bytes: int = 1_048_576
    max_db_bytes: int = 50_000_000
    max_queue_age_days: int = 14
    batch_size: int = 200
    busy_timeout_ms: int = 50
    upload_interval_seconds: int = 30
    http_timeout_seconds: int = 5
    endpoint: str | None = None
    user_id: str | None = None
    team_id: str | None = None
    repo_id: str | None = None

    @property
    def spool_path(self):
        return self.spool_dir / SPOOL_FILE


def default_spool_dir(env, platform=sys.platform):
    if platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "claude-telemetry"
    data_home = env.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data_home) / "claude-telemetry"


def int_setting(env, name, default, minimum=1):
    raw = env.get(name)
    if raw is None:
        return default
    if not raw.isdigit() or int(raw) < minimum:
        raise ConfigError(f"{name} must be an integer >= {minimum}")
    return int(raw)


def endpoint_setting(env):
    url = env.get("TELEMETRY_ENDPOINT")
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in LOCAL_HOSTS):
        raise ConfigError("TELEMETRY_ENDPOINT must be https (http only for localhost)")
    return url


def load_config(env):
    spool_dir = Path(env["TELEMETRY_SPOOL_DIR"]) if "TELEMETRY_SPOOL_DIR" in env else default_spool_dir(env)
    defaults = Config(spool_dir=spool_dir)
    return Config(
        spool_dir=spool_dir,
        max_input_bytes=int_setting(env, "TELEMETRY_MAX_INPUT_BYTES", defaults.max_input_bytes),
        max_db_bytes=int_setting(env, "TELEMETRY_MAX_DB_BYTES", defaults.max_db_bytes),
        max_queue_age_days=int_setting(env, "TELEMETRY_MAX_QUEUE_AGE_DAYS", defaults.max_queue_age_days),
        batch_size=int_setting(env, "TELEMETRY_BATCH_SIZE", defaults.batch_size),
        busy_timeout_ms=int_setting(env, "TELEMETRY_BUSY_TIMEOUT_MS", defaults.busy_timeout_ms),
        upload_interval_seconds=int_setting(env, "TELEMETRY_UPLOAD_INTERVAL_SECONDS", defaults.upload_interval_seconds),
        http_timeout_seconds=int_setting(env, "TELEMETRY_HTTP_TIMEOUT_SECONDS", defaults.http_timeout_seconds),
        endpoint=endpoint_setting(env),
        user_id=env.get("TELEMETRY_USER_ID"),
        team_id=env.get("TELEMETRY_TEAM_ID"),
        repo_id=env.get("TELEMETRY_REPO_ID"),
    )
