
from __future__ import annotations

import platform
import re
import subprocess
from typing import Optional

_UUID_RE = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)


def ioreg_platform_uuid() -> Optional[str]:
    if platform.system() != "Darwin":
        return None
    try:
        out = subprocess.run(
            ["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True, text=True, timeout=20, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out)
    if match is None:
        return None
    value = match.group(1).strip()
    return value if _UUID_RE.match(value) else None


def _scutil(key: str) -> str:
    if platform.system() != "Darwin":
        return ""
    try:
        return subprocess.run(
            ["/usr/sbin/scutil", "--get", key],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def computer_display_name() -> str:
    return _scutil("ComputerName") or platform.node()
