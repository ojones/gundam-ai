import os
import plistlib
import subprocess
import sys
from pathlib import Path

UPLOADER_LABEL = "com.gundam-ai.telemetry.uploader"
INGEST_LABEL = "com.gundam-ai.telemetry.fake-ingest"
SERVICES = {UPLOADER_LABEL: "telemetry.service", INGEST_LABEL: "telemetry.fake_ingest"}
ENDPOINT = "http://localhost:8080/v1/events"


def plist_for(label, module, repo, endpoint=ENDPOINT):
    environment = {"PYTHONPATH": str(repo), "TELEMETRY_ENDPOINT": endpoint}
    arguments = [sys.executable, "-m", module]
    log = Path.home() / "Library" / "Logs" / f"{label}.log"
    return {"Label": label, "ProgramArguments": arguments, "EnvironmentVariables": environment, "RunAtLoad": True, "KeepAlive": True, "StandardErrorPath": str(log)}


def plist_path(label):
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def domain():
    return f"gui/{os.getuid()}"


def install(repo):
    for label, module in SERVICES.items():
        plist_path(label).parent.mkdir(parents=True, exist_ok=True)
        plist_path(label).write_bytes(plistlib.dumps(plist_for(label, module, repo)))
        subprocess.run(["launchctl", "bootstrap", domain(), str(plist_path(label))], check=False)


def uninstall():
    for label in SERVICES:
        subprocess.run(["launchctl", "bootout", f"{domain()}/{label}"], check=False)
        plist_path(label).unlink(missing_ok=True)


def main(argv):
    repo = Path(__file__).resolve().parent.parent
    if argv == ["install"]:
        install(repo)
    elif argv == ["uninstall"]:
        uninstall()
    else:
        print("usage: python3 -m telemetry.launchd install|uninstall", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
