
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

import structlog

from src.core.catalog import catalog_auth, hosted_api
from src.core.relay_identity import device_key as dk

logger = structlog.get_logger()


def account_id(bearer: str) -> Optional[str]:
    parts = bearer.split(".")
    body = dk.unb64url(parts[1]) if len(parts) == 3 else None
    try:
        sub = json.loads(body.decode("utf-8")).get("sub") if body else None
    except (UnicodeDecodeError, ValueError, AttributeError):
        sub = None
    return sub if isinstance(sub, str) and sub.isascii() and sub else None


class RelayAccount:

    def __init__(self, state_dir: Path, api_base_url: Callable[[], str]) -> None:
        self._state_dir, self._base = Path(state_dir), api_base_url

    async def bearer(self, refused: Optional[str] = None) -> Optional[str]:
        try:
            return await catalog_auth.bearer(self._state_dir, self._base(), refused=refused)
        except catalog_auth.SignedOut:
            return None
        except (catalog_auth.RotationFailed, hosted_api.HostedUnavailable) as exc:
            logger.info("relay_account_bearer_unavailable", error=type(exc).__name__)
            return None
