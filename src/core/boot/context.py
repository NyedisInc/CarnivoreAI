
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Optional, Union

from src.config import settings

if TYPE_CHECKING:
    from fastapi import FastAPI

    from src.config.auth import AuthConfig
    from src.core.composition import AppServices
    from src.core.db_state import DatastoreState
    from src.core.auto_sleep.idle_clock import IdleClock
    from src.core.boot.teardown import TeardownRunner
    from src.core.local_servers import LocalServersTracker
    from src.core.log_monitor import LogMonitor
    from src.core.refresh_store import RefreshStore
    from src.core.session_manager import SessionManager
    from src.core.session_notification_policy import NotificationPolicyStore
    from src.core.sessions.background_store import SessionBackgroundStore
    from src.core.spectator_links_store import SpectatorLinksStore
    from src.core.ui_preferences_store import UiPreferencesStore


class BootContextError(RuntimeError):
    pass


@dataclass
class BootContext:

    app: "FastAPI"
    _services: Optional["AppServices"] = None
    _datastore_state: Optional["DatastoreState"] = None
    _auth_cfg: Optional["AuthConfig"] = None
    ui_preferences_store: Optional["UiPreferencesStore"] = None
    session_background_store: Optional["SessionBackgroundStore"] = None
    log_monitor: Optional["LogMonitor"] = None
    local_servers: Optional["LocalServersTracker"] = None
    notification_policy_store: Optional["NotificationPolicyStore"] = None
    refresh_store: Optional["RefreshStore"] = None
    spectator_links_store: Optional["SpectatorLinksStore"] = None
    auto_sleep_clock: Optional["IdleClock"] = None
    teardown: Optional["TeardownRunner"] = None
    allowed_parts: frozenset[str] = frozenset()

    @staticmethod
    def config_path() -> Path:
        return Path(settings.auth_config_file).expanduser()

    @staticmethod
    def state_dir() -> Path:
        return settings.get_state_dir()

    @property
    def services(self) -> "AppServices":
        if self._services is None:
            raise BootContextError("services read before the core services step ran")
        return self._services

    @services.setter
    def services(self, value: "AppServices") -> None:
        self._services = value

    @property
    def session_manager(self) -> "SessionManager":
        return self.services.session_manager

    @property
    def datastore_state(self) -> "DatastoreState":
        if self._datastore_state is None:
            raise BootContextError("datastore_state read before the datastore step ran")
        return self._datastore_state

    @datastore_state.setter
    def datastore_state(self, value: "DatastoreState") -> None:
        self._datastore_state = value

    @property
    def auth_cfg(self) -> "AuthConfig":
        if self._auth_cfg is None:
            raise BootContextError("auth_cfg read before the core services step loaded it")
        return self._auth_cfg

    @auth_cfg.setter
    def auth_cfg(self, value: "AuthConfig") -> None:
        self._auth_cfg = value

    async def stop_part(self, name: str, fn: Callable[[], Union[None, Awaitable[None]]], *,
                        requires: tuple[str, ...] = ()) -> bool:
        if self.teardown is None:
            raise BootContextError("stop_part called outside BootRunner.stop_all")
        if name not in self.allowed_parts:
            raise BootContextError(f"stop part {name!r} is not declared in this step's stop_parts")
        return await self.teardown.run(name, fn, requires=requires)
