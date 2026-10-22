import subprocess
import sys

KEYCHAIN_SERVICE = "claude-telemetry"


def lookup(service=KEYCHAIN_SERVICE, platform=sys.platform):
    if platform != "darwin":
        return None
    result = subprocess.run(["security", "find-generic-password", "-s", service, "-w"], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None
