
from __future__ import annotations

from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional

from src.cplugs.sdk.storage import CplugStorage

CAPABILITY_GRANTS: Mapping[str, str] = {
    "sessions": "sessions.read",
    "projects": "sessions.read",
    "toast": "notify",
    "toast_dismiss": "notify",
    "alert": "notify",
    "alert_resolve": "notify",
    "activity": "activity.read",
    "swarm": "swarm",
    "work": "work",
    "ai": "ai_features:cplug.<id>.<name>",
    "http": "network_hosts:<host> or lan_hosts:<entry>",
}


class GrantRevoked(RuntimeError):

    def __init__(self, permission: str, method: str) -> None:
        super().__init__(f"{method} needs the {permission} permission, which the owner has revoked")
        self.permission = permission
        self.method = method


class CapabilityMissing(AttributeError):
    pass


class CplugContext:

    def __init__(self, cplug_id: str, *, storage: CplugStorage, settings: Dict[str, Any],
                 notify: Callable[[str, Optional[str]], None], log: Any, grants: FrozenSet[str],
                 capabilities: Mapping[str, Any],
                 settings_source: Optional[Callable[[], Dict[str, Any]]] = None,
                 settings_adopter: Optional[Callable[[str, Any], Dict[str, Any]]] = None,
                 enabled_source: Optional[Callable[[], bool]] = None, at_boot: bool = False,
                 grants_source: Optional[Callable[[], FrozenSet[str]]] = None,
                 push: Optional[Callable[[str, Dict[str, Any]], bool]] = None,
                 follow: Optional[Callable[[str, Callable[[List[str]], None]], Callable[[], None]]] = None) -> None:
        self.id = cplug_id
        self.at_boot = at_boot
        self.storage = storage
        self.settings = dict(settings)
        self._settings_source = settings_source
        self._settings_adopter = settings_adopter
        self._enabled_source = enabled_source
        self.log = log
        self._grants = grants
        self._grants_source = grants_source
        self._notify = notify
        self._push = push
        self._follow = follow
        for name, value in capabilities.items():
            setattr(self, name, value)

    def settings_now(self) -> Dict[str, Any]:
        return dict(self._settings_source()) if self._settings_source is not None else dict(self.settings)

    def enabled_now(self) -> bool:
        return bool(self._enabled_source()) if self._enabled_source is not None else True

    def adopt_settings(self, source_id: str, keys: Any) -> Dict[str, Any]:
        return self._settings_adopter(source_id, tuple(keys)) if self._settings_adopter is not None else {}

    def notify(self, name: str, key: Optional[str] = None) -> None:
        self._notify(name, key)

    def push_data(self, name: str, data: Dict[str, Any]) -> bool:
        return self._push(name, data) if self._push is not None else False

    def follow(self, name: str, listener: Callable[[List[str]], None]) -> Callable[[], None]:
        return self._follow(name, listener) if self._follow is not None else (lambda: None)

    @property
    def grants(self) -> FrozenSet[str]:
        return self._grants_source() if self._grants_source is not None else self._grants

    def has(self, permission: str) -> bool:
        return permission in self.grants

    def __getattr__(self, name: str) -> Any:
        grant = CAPABILITY_GRANTS.get(name)
        if grant is not None:
            raise CapabilityMissing(f"plugin {self.__dict__.get('id')} has no {name}: the owner has not granted {grant}")
        raise AttributeError(name)
