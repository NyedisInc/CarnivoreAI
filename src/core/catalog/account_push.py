
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from src.core import session_change_notice
from src.core.catalog import catalog_auth
from src.models.websocket import WSMessageType

_installed: Optional[Callable[[Dict[str, Any]], None]] = None


def install(app_state: Any) -> None:
    global _installed
    if _installed is not None:
        catalog_auth.unsubscribe(_installed)

    def publish(event: Dict[str, Any]) -> None:
        session_change_notice.publish(app_state, {"type": WSMessageType.ACCOUNT_SESSION.value, **event})

    _installed = publish
    catalog_auth.subscribe(publish)
