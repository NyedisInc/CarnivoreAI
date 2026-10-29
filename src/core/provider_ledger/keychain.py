
from __future__ import annotations

import subprocess
from typing import Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger()

TIMEOUT_SECONDS = 5.0

_last_failure: Dict[Tuple[str, Optional[str]], int] = {}


def read_password(
    service: str,
    *,
    account: Optional[str] = None,
    timeout: float = TIMEOUT_SECONDS,
) -> Optional[str]:
    argv: List[str] = ["security", "find-generic-password", "-s", service]
    if account is not None:
        argv += ["-a", account]
    argv.append("-w")

    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("keychain_read_timeout", service=service, timeout=timeout)
        return None
    except OSError as exc:
        logger.warning(
            "keychain_read_unavailable", service=service, error=type(exc).__name__
        )
        return None

    if completed.returncode != 0:
        key = (service, account)
        level = logger.debug if _last_failure.get(key) == completed.returncode else logger.info
        _last_failure[key] = completed.returncode
        level("keychain_read_failed", service=service, status=completed.returncode)
        return None

    _last_failure.pop((service, account), None)

    password = (completed.stdout or "").strip()
    return password or None
