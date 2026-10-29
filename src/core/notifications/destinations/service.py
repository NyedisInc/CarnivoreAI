
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

from src.core.notifications.destinations import secrets as secret_store
from src.core.notifications.destinations.routing import RoutingProvider
from src.core.notifications.destinations.store import DestinationStore
from src.core.notifications.settings_doc.store import SettingsDocStore


class NotificationService:

    def __init__(self, config_path: Path, *, subscriptions: Any = None, native_devices: Any = None) -> None:
        self.docs = SettingsDocStore(config_path)
        self.secrets = secret_store.DestinationSecrets()
        self.destinations = DestinationStore(self.docs, self.secrets)
        self.routing = RoutingProvider(self.docs, subscriptions or (lambda: ()), native_devices or (lambda: ()))


_current: Optional[NotificationService] = None


def current_service() -> Optional[NotificationService]:
    return _current


def get_service(app_state: Any) -> NotificationService:
    global _current
    service: Optional[NotificationService] = getattr(app_state, "notification_service", None)
    if service is None:
        from src.config import settings  # noqa: PLC0415

        service = NotificationService(Path(settings.auth_config_file).expanduser(), subscriptions=_subscription_rows(app_state),
                                     native_devices=_native_device_rows(app_state))
        app_state.notification_service = service
    _current = service
    return service


def _subscription_rows(app_state: Any) -> Any:
    def rows() -> Any:
        from src.core.web_push.wiring import sender_for  # noqa: PLC0415

        return sender_for(app_state).store.list()

    return rows


def _native_device_rows(app_state: Any) -> Any:
    def rows() -> Any:
        from src.core.native_push.wiring import store_for  # noqa: PLC0415

        return store_for(app_state).list()

    return rows
