
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from src.core import session_change_notice
from src.core.catalog import catalog_auth
from src.models.websocket import WSMessageType

_installed: Optional[Callable[[Dict[str, Any]], None]] = None
_installed_client: Optional[Callable[[str], None]] = None

FRAME = {"type": WSMessageType.ACCOUNT_SESSION.value, "reread": True}


def install(app_state: Any) -> None:
    global _installed, _installed_client
    if _installed is not None:
        catalog_auth.unsubscribe(_installed)
    if _installed_client is not None:
        catalog_auth.unsubscribe_client(_installed_client)

    def publish(_event: Dict[str, Any]) -> None:
        session_change_notice.publish(app_state, dict(FRAME))

    def publish_client(client_key: str) -> None:
        hub = getattr(app_state, "event_hub", None)
        if hub is not None:
            hub.publish(dict(FRAME), only_family=client_key)

    _installed, _installed_client = publish, publish_client
    catalog_auth.subscribe(publish)
    catalog_auth.subscribe_client(publish_client)
