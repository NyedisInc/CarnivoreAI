
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Mapping, NamedTuple, Optional, Sequence

import structlog

from src.cplugs.host.session_uuid_reads import session_uuids

logger = structlog.get_logger()

TOAST_KIND = "Notification"

Infos = Callable[[], Awaitable[List[Any]]]


class ToastRef(NamedTuple):

    session_id: str
    toast_id: str


class Sessions:

    def __init__(self, infos: Infos, request: Optional[Any] = None, may_message: bool = False, *,
                 may_create: Optional[bool] = None, may_control: Optional[bool] = None, may_resume: bool = False,
                 app_state: Optional[Any] = None) -> None:
        self._infos = infos
        self._app_state = app_state
        if may_message and request is not None:
            from src.cplugs.host import session_actions  # noqa: PLC0415

            self.message = _messenger(request)
            self.deliver = _deliverer(request)
            self.booted = lambda: session_actions.booted(request)
            if may_control if may_control is not None else True:
                self.asleep = lambda: session_actions.asleep(request)
                self.wake = lambda session_uuid: session_actions.wake(request, session_uuid)
            if may_create if may_create is not None else True:
                self.start = lambda project_id: session_actions.start(request, project_id)
                self.start_in_folder = lambda working_dir, label, opening_prompt: session_actions.start_in_folder(request, working_dir, label, opening_prompt)
        if may_resume and request is not None:
            from src.cplugs.host import session_actions  # noqa: PLC0415,F811

            self.resume = lambda session_uuid, wrapper: session_actions.resume(request, session_uuid, wrapper)

    async def list(self) -> List[Any]:
        return await self._infos()

    async def asleep_read(self) -> Optional[List[Dict[str, Any]]]:
        if self._app_state is None:
            return None
        from types import SimpleNamespace  # noqa: PLC0415
        from src.cplugs.host import session_actions  # noqa: PLC0415

        return await session_actions.asleep(SimpleNamespace(app=SimpleNamespace(state=self._app_state)))

    async def list_allowed(self) -> List[Dict[str, Any]]:
        from src.cplugs.host import session_fields  # noqa: PLC0415

        return [session_fields.project(i) for i in await self._infos()]

    async def get_allowed(self, ref: str) -> Optional[Dict[str, Any]]:
        if ref.startswith("remote:"):
            raise PermissionError("permission_denied: a remote session is not readable here")
        return next((r for r in await self.list_allowed() if r["id"] == ref), None)

    async def durable_keys(self, infos: Optional[List[Any]] = None) -> Dict[str, str]:
        rows = await self._infos() if infos is None else infos
        row_ids = {i.session.id: getattr(i, "session_row_id", None) for i in rows}
        uuids = await asyncio.to_thread(session_uuids, sorted({r for r in row_ids.values() if r is not None}))
        return {sid: uuids.get(rid) or sid for sid, rid in row_ids.items()}

    async def stored_rows(self, keys: List[str]) -> Dict[str, Any]:
        from src.cplugs.host import session_rows  # noqa: PLC0415

        return await asyncio.to_thread(session_rows.read, keys)


_RESTRICTED_ACTIONS = ("message", "deliver", "booted", "asleep", "wake")


class RestrictedSessions:

    def __init__(self, infos: Infos, request: Optional[Any] = None, may_message: bool = False, *,
                 may_control: bool = False) -> None:
        inner = Sessions(infos, request, may_message, may_create=False, may_control=may_control)
        self._sessions = inner
        for name in _RESTRICTED_ACTIONS:
            action = getattr(inner, name, None)
            if action is not None:
                setattr(self, name, action)

    async def list(self) -> List[Dict[str, Any]]:
        return await self._sessions.list_allowed()

    async def get(self, ref: str) -> Optional[Dict[str, Any]]:
        return await self._sessions.get_allowed(ref)


async def _recorded_delivery_known(request: Any, target: str, recorded: Optional[int]) -> bool:
    from src.core import db  # noqa: PLC0415
    from src.core.swarm import delivery  # noqa: PLC0415

    if recorded is None:
        return False
    info = await request.app.state.session_manager.get_session_info(session_id=target)
    try:
        return bool(await asyncio.to_thread(delivery.is_delivery_of_body, getattr(info, "session_row_id", None), recorded))
    except (db.DatastoreUnreadableError, sqlite3.Error, OSError):
        return False


def _messenger(request: Any) -> Callable[[str, str], Awaitable[Any]]:
    async def message(target: str, line: str, *, recorded: Optional[int] = None) -> Any:
        from src.core.swarm import delivery  # noqa: PLC0415

        if await _recorded_delivery_known(request, target, recorded):
            from src.api.one_shot_routes import paste_through_gates  # noqa: PLC0415

            return await paste_through_gates(request, target, line)
        return await delivery.paste_as_data(request, target, line, f"plugin:message:{target}")

    return message


def _deliverer(request: Any) -> Callable[..., Awaitable[Any]]:
    async def deliver(target: str, line: str, meta: Optional[Mapping[str, str]] = None, *,
                      recorded: Optional[int] = None) -> Any:
        from src.api.channel_delivery import deliver_through_gates  # noqa: PLC0415

        if await _recorded_delivery_known(request, target, recorded):
            return await deliver_through_gates(request, target, line, meta)
        from src.core.swarm import delivery  # noqa: PLC0415

        async def send(req: Any, session_id: str, text: str) -> Any:
            return await deliver_through_gates(req, session_id, text, meta)

        return await delivery.paste_as_data(request, target, line, f"plugin:message:{target}", send=send)

    return deliver


class Projects:

    def __init__(self, restricted: bool = False) -> None:
        self._restricted = restricted

    def get(self, project_id: int) -> Optional[Dict[str, Any]]:
        from src.api import projects_service  # noqa: PLC0415
        from src.config import settings  # noqa: PLC0415
        from src.models import ProjectResponse  # noqa: PLC0415

        view = projects_service.current_view(settings)
        found = next((p for p in projects_service.views_to_responses(view, ProjectResponse) if p.id == project_id), None)
        if found is not None and self._restricted:
            return {"id": found.id, "name": found.name}
        return None if found is None else {"id": found.id, "name": found.name, "path": found.path,
                                           "default_launch_profile": found.default_launch_profile}

    def list(self, *, include_archived: bool = False, strict: bool = False) -> List[Dict[str, Any]]:
        from src.api import projects_service  # noqa: PLC0415
        from src.config import settings  # noqa: PLC0415
        from src.models import ProjectResponse  # noqa: PLC0415

        view = projects_service.current_view(settings, include_archived=include_archived)
        if strict and view.degraded:
            raise OSError(view.detail or view.message or "the project list could not be read")
        return [{"id": p.id, "name": p.name}
                for p in projects_service.views_to_responses(view, ProjectResponse) if p.id is not None]

    def enclosing(self) -> Dict[str, List[str]]:
        if self._restricted:
            return {}
        from src.api import projects_service  # noqa: PLC0415
        from src.config import settings  # noqa: PLC0415
        from src.core import project_directory  # noqa: PLC0415
        from src.models import ProjectResponse  # noqa: PLC0415

        view = projects_service.current_view(settings)
        if view.degraded:
            raise OSError(view.detail or view.message or "the project list could not be read")
        return project_directory.enclosing_projects({str(p.id): p.path for p in projects_service.views_to_responses(view, ProjectResponse)
                                                     if p.id is not None and p.path})


def local_infos_from_app(app_state: Any) -> Infos:
    async def infos() -> List[Any]:
        from src.core.hosts.ddl import LOCAL_HOST_KEY  # noqa: PLC0415

        manager = getattr(app_state, "session_manager", None)
        if manager is None:
            return []
        rows = await manager.list_session_infos()
        return [i for i in rows if getattr(i, "host_key", LOCAL_HOST_KEY) == LOCAL_HOST_KEY]

    return infos


TOAST_TITLE_MAX = 80
TOAST_BUDGET = 6
TOAST_WINDOW_S = 3600.0
_URL_SHAPED = re.compile(r"[a-z][a-z0-9+.\-]*://|\bwww\.|\b[a-z0-9\-]+(?:\.[a-z0-9\-]+)*\.[a-z]{2,}\b", re.IGNORECASE)
_toast_times: Dict[str, "deque[float]"] = defaultdict(deque)
_toast_clock: Callable[[], float] = time.monotonic
_ALERT_KEY = re.compile(r"^[a-z0-9_]{1,32}$")


def toast_allowed(cplug_id: str) -> bool:
    now = _toast_clock()
    times = _toast_times[cplug_id]
    while times and now - times[0] > TOAST_WINDOW_S:
        times.popleft()
    if len(times) >= TOAST_BUDGET:
        return False
    times.append(now)
    return True


PLUGIN_NOTIFY_TYPE = "plugin.notice"


def plugin_notify_type(cplug_id: str, requested: Optional[str]) -> str:
    from src.core.notifications.types import is_registered  # noqa: PLC0415

    if requested and requested.startswith(f"cplug.{cplug_id}.") and is_registered(requested):
        return requested
    return PLUGIN_NOTIFY_TYPE


def toaster(cplug_id: str, app_state: Any, prefix: str = "") -> Callable[..., Optional[ToastRef]]:
    def toast(session_id: str, title: str, notify_type: Optional[str] = None) -> Optional[ToastRef]:
        from src.core import session_change_notice  # noqa: PLC0415
        from src.core.attention.raise_gate import resolve_raise  # noqa: PLC0415
        from src.models import ToastNewMessage  # noqa: PLC0415

        manager = getattr(app_state, "session_manager", None)
        if manager is None or not session_id:
            return None
        shown = f"{prefix}{title}"[:TOAST_TITLE_MAX] if prefix else title
        if prefix and _URL_SHAPED.search(title):
            logger.warning("cplug_toast_refused", cplug=cplug_id, reason="url_shaped")
            return None
        if prefix and not toast_allowed(cplug_id):
            logger.warning("cplug_toast_refused", cplug=cplug_id, reason="budget")
            return None
        try:
            gate = resolve_raise(
                TOAST_KIND,
                policy_store_attached=getattr(manager, "_notification_policy_store", None) is not None,
                policy=manager.notification_policy_stamp(session_id))
            if not gate.raises_toast:
                return None
            row = manager.record_toast(session_id=session_id, kind=TOAST_KIND, title=shown,
                                       notify_type=plugin_notify_type(cplug_id, notify_type))
            session_change_notice.publish(app_state, json.loads(ToastNewMessage(toast=row).model_dump_json()))
            return ToastRef(row.session_id, row.id)
        except (ValueError, AttributeError, KeyError, TypeError) as exc:
            logger.warning("cplug_toast_failed", cplug=cplug_id, error_type=type(exc).__name__, error=str(exc))
            return None

    return toast


def toast_dismisser(cplug_id: str, app_state: Any) -> Callable[[ToastRef], bool]:
    def dismiss(ref: ToastRef) -> bool:
        from src.core import toast_auto_ack  # noqa: PLC0415

        services = getattr(app_state, "services", None)
        inbox = getattr(services, "toasts", None)
        if inbox is None:
            return False
        try:
            return bool(inbox.ack(ref.session_id, ref.toast_id, toast_auto_ack.ACK_REASON_ANSWERED))
        except (AttributeError, KeyError, TypeError) as exc:
            logger.warning("cplug_toast_dismiss_failed", cplug=cplug_id, error_type=type(exc).__name__, error=str(exc))
            return False

    return dismiss


def alerter(cplug_id: str, third_party: bool = False) -> Callable[..., Optional[Dict[str, Any]]]:
    def alert(key: str, severity: str, title_key: str, params: Optional[Mapping[str, Any]] = None, *,
              detail_key: Optional[str] = None, actions: Sequence[Mapping[str, Any]] = ()) -> Optional[Dict[str, Any]]:
        from src.core.app_alerts.service import raise_alert  # noqa: PLC0415

        if third_party:
            if not isinstance(key, str) or not _ALERT_KEY.match(key):
                raise ValueError("alert key must match ^[a-z0-9_]{1,32}$")
            if not isinstance(title_key, str) or not title_key.startswith(f"cplug.{cplug_id}."):
                raise ValueError(f"alert title_key must start with cplug.{cplug_id}.")
            if detail_key is not None and not (isinstance(detail_key, str) and detail_key.startswith(f"cplug.{cplug_id}.")):
                raise ValueError(f"alert detail_key must start with cplug.{cplug_id}.")
            if actions:
                raise ValueError("a third-party alert carries no actions")
            key = f"p.{key}"
        return raise_alert(f"cplug.{cplug_id}.{key}", source=f"cplug.{cplug_id}", severity=severity,
                           title_key=title_key, params=params, detail_key=detail_key, actions=actions)

    return alert


def alert_resolver(cplug_id: str, third_party: bool = False) -> Callable[[str], Any]:
    def alert_resolve(key: str) -> Any:
        from src.core.app_alerts.service import resolve  # noqa: PLC0415

        if third_party:
            if not isinstance(key, str) or not _ALERT_KEY.match(key):
                raise ValueError("alert key must match ^[a-z0-9_]{1,32}$")
            key = f"p.{key}"
        return resolve(f"cplug.{cplug_id}.{key}")

    return alert_resolve


def swarm_capability(state_dir: Path, infos: Infos, app_state: Any = None) -> Any:
    from src.core.swarm.facade import SwarmFacade  # noqa: PLC0415

    return SwarmFacade(state_dir, infos, app_state)


def work_capability(state_dir: Path) -> Any:
    from src.core.work.capability import WorkCapability  # noqa: PLC0415

    return WorkCapability(state_dir)
