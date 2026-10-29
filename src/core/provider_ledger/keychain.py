
from __future__ import annotations

import subprocess
from typing import List, Optional

import structlog

logger = structlog.get_logger()

TIMEOUT_SECONDS = 5.0


def read_password(
    service: str,
    *,
    account: Optional[str] = None,
    timeout: float = TIMEOUT_SECONDS,
) -> Optional[str]:
    """Read one generic password, or report that it could not be read.

    Description: shells out to ``security find-generic-password``. The
      account is omitted when it is not given, because some items carry
      no account and a service-only lookup is the one that finds them.
    Inputs: service (str) - the keychain service name; account (str |
      None) - the account name, keyword only, omitted when None; timeout
      (float) - seconds, keyword only.
    Output: str | None - the password as written, or None when the item
      is absent, unreadable, or the read did not finish.
    Example: read_password("Claude Code-credentials")
    """
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
        logger.info(
            "keychain_read_failed", service=service, status=completed.returncode
        )
        return None

    password = (completed.stdout or "").strip()
    return password or None
