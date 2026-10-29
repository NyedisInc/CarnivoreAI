
from __future__ import annotations

import asyncio
import inspect
import re
from typing import Any, Callable, Dict, FrozenSet, Optional

from src.cplugs.host.activity_log import ActivityLog
from src.cplugs.sdk.context import GrantRevoked

LiveGrants = Callable[[], FrozenSet[str]]
_LABEL_ONLY = frozenset({"ai_features", "network_hosts"})
_TARGETED = frozenset({"sessions.message", "notify"})
_ID = re.compile(r"^[A-Za-z0-9:_.\-]{1,80}$")
_SESSION_METHOD_PERMISSION: Dict[str, str] = {
    "message": "sessions.message", "deliver": "sessions.message", "booted": "sessions.message",
    "start": "sessions.create", "start_in_folder": "sessions.create", "resume": "sessions.create", "asleep": "sessions.control", "wake": "sessions.control",
}

_FIRST_PARTY_SESSION_METHOD_PERMISSION: Dict[str, str] = {
    **_SESSION_METHOD_PERMISSION,
    "start": "sessions.message", "start_in_folder": "sessions.message", "asleep": "sessions.message", "wake": "sessions.message",
}


def _size(result: Any) -> int:
    return len(result) if isinstance(result, (str, bytes)) else 0


_SUBCLASSES: Dict[type, type] = {}


def _audited_getattribute(self: Any, attr: str) -> Any:
    value = object.__getattribute__(self, attr)
    if attr.startswith("_") or not callable(value) or inspect.isclass(value):
        return value
    log, cplug_id, name, permission, live = object.__getattribute__(self, "_audit")
    return _recorder(value, log, cplug_id, f"{name}.{attr}", permission(attr) if callable(permission) else permission, live)


def _recording_class(cls: type) -> type:
    sub = _SUBCLASSES.get(cls)
    if sub is None:
        sub = _SUBCLASSES[cls] = type(cls.__name__, (cls,), {"__getattribute__": _audited_getattribute, "__module__": cls.__module__})
    return sub


def _recorder(fn: Callable[..., Any], log: ActivityLog, cplug_id: str, method: str, permission: str,
              live: Optional[LiveGrants] = None) -> Callable[..., Any]:
    def target_of(args: tuple) -> str:
        first = args[0] if args else ""
        return first if permission in _TARGETED and isinstance(first, str) and _ID.match(first) else ""

    def record(args: tuple, status: str, result: Any = None) -> None:
        try:
            asyncio.get_running_loop()
            hot = True
        except RuntimeError:
            hot = False
        log.record(cplug_id, method=method, permission=permission, target=target_of(args), status=status, size=_size(result), hot=hot)

    async def record_off_loop(args: tuple, status: str, result: Any = None) -> None:
        await asyncio.to_thread(log.record, cplug_id, method=method, permission=permission, target=target_of(args),
                                status=status, size=_size(result))

    async def finish(awaitable: Any, args: tuple) -> Any:
        try:
            result = await awaitable
        except Exception as exc:  # noqa: BLE001
            await record_off_loop(args, f"error:{type(exc).__name__}")
            raise
        await record_off_loop(args, "ok", result)
        return result

    def call(*args: Any, **kwargs: Any) -> Any:
        try:
            if live is not None and permission not in _LABEL_ONLY and permission not in live():
                raise GrantRevoked(permission, method)
            result = fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            record(args, f"error:{type(exc).__name__}")
            raise
        if inspect.isawaitable(result):
            return finish(result, args)
        record(args, "ok", result)
        return result

    return call


def audited(capability: Any, log: ActivityLog, cplug_id: str, name: str, permission: Any, live: Optional[LiveGrants] = None) -> Any:
    if inspect.isfunction(capability) or inspect.ismethod(capability):
        return _recorder(capability, log, cplug_id, name, permission if isinstance(permission, str) else permission(name), live)
    object.__setattr__(capability, "_audit", (log, cplug_id, name, permission, live))
    capability.__class__ = _recording_class(type(capability))
    return capability


def sessions_permission_for(outside: bool) -> Callable[[str], str]:
    table = _SESSION_METHOD_PERMISSION if outside else _FIRST_PARTY_SESSION_METHOD_PERMISSION
    return lambda method: table.get(method, "sessions.read")
