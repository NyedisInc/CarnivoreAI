
from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from src.core.federation import peer_links
from src.core.notifications.destinations.service import get_service
from src.core.notifications.sync.manager import SyncManager
from src.core.notifications.sync.peers import LinkGateway


def start(app_state: Any, open_db: Callable[[], Any]) -> "asyncio.Task[None]":
    service = get_service(app_state)
    gateway = LinkGateway(open_db, lambda: peer_links.LINKS)
    manager = SyncManager(service.docs, service.secrets, gateway)
    manager.attach()
    app_state.notification_sync = manager
    if peer_links.LINKS is not None:
        peer_links.LINKS.add_connect_listener(lambda install_id: manager.request_sync())
    return asyncio.create_task(manager.run(), name="notification-settings-sync")


def current(app_state: Any) -> Optional[SyncManager]:
    return getattr(app_state, "notification_sync", None)
