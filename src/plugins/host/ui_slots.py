
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Mapping, Optional, Sequence, Tuple

from src.core.resource_push import topics
from src.plugins.host import activity_log, inspector_telemetry, risk, state as owner_state, ui_doc
from src.plugins.host.sidecar_registry import SidecarDefinition
from src.plugins.sdk._manifest_v2_sections import MAX_SLOTS

CORE_UI_SLOTS = frozenset({
    "commands",
    "chords",
    "session.row_actions",
    "session_row_actions",
    "session.badges",
    "session_badges",
    "terminal.toolbar",
    "terminal_toolbar",
    "project.panels",
    "project_panels",
    "popout",
})

SLOT_ALIASES: Dict[str, str] = {
    "session_row_actions": "session.row_actions",
    "session_badges": "session.badges",
    "terminal_toolbar": "terminal.toolbar",
    "project_panels": "project.panels",
}

UI_SLOT_RATE_LIMIT = 60
UI_SLOT_RATE_WINDOW = 60.0
MAX_SLOT_BYTES = 128 * 1024
_BAD_SUPERVISOR_STATES = frozenset(
    {
        "disabled",
        "disabled (safe mode)",
        "paused",
        "killed",
        "index_expired",
        "revoked",
        "crash_loop",
        "integrity",
        "needs_approval",
        "safe_mode",
    }
)


class UiSlotError(Exception):

    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail


def canonical_slot(slot: str) -> str:
    return SLOT_ALIASES.get(slot, slot)


def _declared_actions(d: Any) -> Tuple[Tuple[str, ...], Tuple[str, ...], Tuple[str, ...]]:
    m = d.manifest
    if isinstance(d, SidecarDefinition):
        routes = tuple(str(r) for r in (getattr(m, "routes", ()) or ()))
        tools = tuple(str(t["name"]) for t in (getattr(m, "tools", ()) or ()) if isinstance(t, Mapping) and "name" in t)
    else:
        routes = tuple(d.router.routes[i].name for i in range(len(d.router.routes))) if getattr(d, "router", None) is not None else ()
        tools = tuple(getattr(m.surfaces, "mcp_tools", ()) or ())
    macros_raw = getattr(m, "macros", None) or {}
    macros = tuple(str(k) for k in macros_raw.keys()) if isinstance(macros_raw, Mapping) else ()
    return routes, tools, macros


def _install_key(host: Any, d: Any) -> str:
    fn = getattr(host, "install_key", None)
    if callable(fn):
        try:
            return str(fn(d.id))
        except (OSError, KeyError, ValueError):
            pass
    return str(getattr(d, "install_key", "") or d.id)


def _is_active(
    host: Any,
    state_dir: Path,
    d: Any,
    *,
    safe_mode_active: bool = False,
    supervisor: Any = None,
) -> bool:
    m = d.manifest
    st = owner_state.get(state_dir, m)
    if not st.enabled:
        return False
    if risk.consent_owed(m.tier, m.code_digest, st.digest):
        return False
    if isinstance(d, SidecarDefinition):
        if safe_mode_active:
            return False
        if supervisor is not None:
            if hasattr(supervisor, "is_paused") and supervisor.is_paused(d.id):
                return False
            if supervisor.state(d.id) in _BAD_SUPERVISOR_STATES:
                return False
    unavailable = getattr(host, "unavailable", None)
    if isinstance(unavailable, Mapping) and d.id in unavailable:
        return False
    return True


def _publish_slots(host: Any) -> None:
    pub = getattr(host, "publish", None)
    if callable(pub):
        pub(topics.CPLUG_SLOTS)


def _popout_enabled(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, Mapping):
        if "enabled" in value and isinstance(value["enabled"], bool):
            return value["enabled"]
        return True
    return None


def normalize_sidebar_tab(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, Mapping):
        return None
    out: Dict[str, Any] = {}
    for key in ("id", "title", "icon", "mode", "view", "ui_file"):
        if key in raw and isinstance(raw[key], str):
            out[key] = raw[key]
    if "popout" in raw:
        pop = raw["popout"]
        if isinstance(pop, bool):
            out["popout"] = pop
        elif isinstance(pop, Mapping):
            out["popout"] = dict(pop)
    if "multi" in raw and isinstance(raw["multi"], bool):
        out["multi"] = raw["multi"]
    if "popout_multi" in raw and isinstance(raw["popout_multi"], bool):
        out["popout_multi"] = raw["popout_multi"]
    if "document" in raw and isinstance(raw["document"], Mapping):
        out["has_document"] = True
    return out


def row_metadata(manifest: Any, *, plugin_id: str) -> Dict[str, Any]:
    raw_ui_meta = getattr(manifest, "ui_meta", None)
    ui_meta = dict(raw_ui_meta) if isinstance(raw_ui_meta, Mapping) else {}
    raw_contrib = getattr(manifest, "ui_contribute", None)
    contrib: Dict[str, List[Dict[str, Any]]] = {}
    if isinstance(raw_contrib, Mapping):
        for k, v in raw_contrib.items():
            if isinstance(v, (list, tuple)):
                contrib[str(k)] = [dict(x) for x in v if isinstance(x, Mapping)]

    commands = list(ui_meta.get("commands") or ()) if isinstance(ui_meta.get("commands"), (list, tuple)) else []
    commands.extend(contrib.get("commands", ()))

    chords: List[Any] = []
    if isinstance(ui_meta.get("chords"), (list, tuple)):
        chords.extend(ui_meta["chords"])
    for cmd in commands:
        if isinstance(cmd, Mapping) and cmd.get("shortcut"):
            chords.append({"command": cmd.get("id"), "shortcut": cmd.get("shortcut")})
    chords.extend(contrib.get("chords", ()))

    session_badges: List[Any] = []
    if isinstance(ui_meta.get("session_badge"), Mapping):
        session_badges.append(dict(ui_meta["session_badge"]))
    elif isinstance(ui_meta.get("session_badges"), (list, tuple)):
        session_badges.extend(ui_meta["session_badges"])
    session_badges.extend(contrib.get("session.badges", ()))
    session_badges.extend(contrib.get("session_badges", ()))

    session_row_actions = list(contrib.get("session.row_actions", ())) + list(contrib.get("session_row_actions", ()))
    terminal_toolbar = list(contrib.get("terminal.toolbar", ())) + list(contrib.get("terminal_toolbar", ()))
    project_panels = list(contrib.get("project.panels", ())) + list(contrib.get("project_panels", ()))

    raw_channels = getattr(manifest, "channels", None) or {}
    channels = [
        {
            "id": str(k),
            "kind_id": f"plugin:{plugin_id}:{k}",
            "label": str(v.get("label") or k) if isinstance(v, Mapping) else str(k),
        }
        for k, v in (raw_channels.items() if isinstance(raw_channels, Mapping) else ())
    ]
    harnesses = list(getattr(manifest, "harnesses", ()) or ())
    sidebar_tab = normalize_sidebar_tab(ui_meta.get("sidebar_tab"))
    if "popout" in ui_meta:
        popout = ui_meta.get("popout")
    elif contrib.get("popout"):
        popout = contrib.get("popout")
    else:
        flags = [
            _popout_enabled(ui_meta.get("widget", {}).get("popout") if isinstance(ui_meta.get("widget"), Mapping) else None),
            _popout_enabled(sidebar_tab.get("popout") if isinstance(sidebar_tab, Mapping) else None),
            _popout_enabled(getattr(manifest, "page", None).get("popout") if isinstance(getattr(manifest, "page", None), Mapping) else None),
            *[_popout_enabled(v.get("popout")) for v in (getattr(manifest, "views", ()) or ()) if isinstance(v, Mapping)],
        ]
        known = [f for f in flags if f is not None]
        popout = True if any(known) else (False if known else None)

    svc_provides = [
        dict(x) for x in (getattr(manifest, "services_provides", ()) or ()) if isinstance(x, Mapping)
    ]
    events_on = getattr(manifest, "events_on", None)
    if events_on is None:
        events_on = [
            str(s)
            for s in (getattr(manifest, "subscriptions", ()) or ())
            if not str(s).startswith("webhook.")
        ]
    return {
        "services": {
            "provides": svc_provides,
            "consumes": list(getattr(manifest, "services_consumes", ()) or ()),
        },
        "events": {
            "on": list(events_on or ()),
            "emit": list(getattr(manifest, "events_emit", ()) or ()),
            "allowed": list(getattr(manifest, "events_allowed", ()) or ()),
        },
        "ui_slots": list(getattr(manifest, "ui_slots", ()) or ()),
        "ui_contribute": contrib,
        "commands": commands,
        "chords": chords,
        "session_row_actions": session_row_actions,
        "session_badges": session_badges,
        "terminal_toolbar": terminal_toolbar,
        "project_panels": project_panels,
        "channels": channels,
        "harnesses": harnesses,
        "sidebar_tab": sidebar_tab,
        "popout": popout,
    }


class UiSlotRegistry:

    def __init__(self, state_dir: Path, clock: Callable[[], float] = time.monotonic) -> None:
        self.state_dir = Path(os.path.realpath(state_dir))
        self._clock = clock
        self._lock = threading.RLock()
        self._owners: Dict[str, str] = {}
        self._dynamic: Dict[Tuple[str, str], Tuple[Dict[str, Any], ...]] = {}
        self._windows: Dict[str, Deque[float]] = {}

    def _audit(
        self,
        host: Any,
        d: Any,
        *,
        method: str,
        slot: str,
        status: str,
        allowed: bool,
        size: int = 0,
        detail: str = "",
    ) -> None:
        key = _install_key(host, d)
        activity_log.ActivityLog(self.state_dir).record(
            key,
            method=method,
            permission=f"ui.slot:{slot}",
            target=slot,
            status=status,
            size=size,
        )
        telem = inspector_telemetry.telemetry_for(self.state_dir)
        telem.record_capability(
            d.id,
            permission=f"ui.slot:{slot}",
            allowed=allowed,
            reason=detail,
            caller=f"ui.slot:{slot}",
        )

    def _validate_items(self, d: Any, slot: str, raw_items: Sequence[Any]) -> Tuple[Dict[str, Any], ...]:
        routes, tools, macros = _declared_actions(d)
        cleaned: List[Dict[str, Any]] = []
        for idx, item in enumerate(raw_items):
            cleaned.append(
                ui_doc.validate_slot_entry(
                    item,
                    routes=routes,
                    tools=tools,
                    macros=macros,
                    path=f"/ui/contribute/{slot}/{idx}",
                )
            )
        return tuple(cleaned)

    def sync(
        self,
        definitions: Sequence[Any],
        *,
        host: Any,
        safe_mode_active: bool = False,
        supervisor: Any = None,
    ) -> Dict[str, str]:
        owners: Dict[str, str] = {}
        active_by_id: Dict[str, Any] = {}
        for d in definitions:
            if not _is_active(host, self.state_dir, d, safe_mode_active=safe_mode_active, supervisor=supervisor):
                continue
            active_by_id[d.id] = d
            for slot in getattr(d.manifest, "ui_slots", ()) or ():
                slot_name = canonical_slot(str(slot))
                if slot_name not in CORE_UI_SLOTS and slot_name not in owners:
                    owners[slot_name] = d.id
        removed = 0
        with self._lock:
            self._owners = owners
            for key in list(self._dynamic):
                pid, slot_name = key
                d = active_by_id.get(pid)
                if d is None:
                    self._dynamic.pop(key, None)
                    removed += 1
                    continue
                granted = {canonical_slot(str(s)) for s in owner_state.granted_ui_slots(self.state_dir, d.manifest)}
                if canonical_slot(slot_name) not in granted:
                    self._dynamic.pop(key, None)
                    removed += 1
        if removed:
            _publish_slots(host)
        return dict(owners)

    def clear_plugin(self, plugin_id: str, *, host: Any = None, publish: bool = True) -> int:
        removed = 0
        with self._lock:
            for key in list(self._dynamic):
                if key[0] == plugin_id:
                    self._dynamic.pop(key, None)
                    removed += 1
        if removed and publish and host is not None:
            _publish_slots(host)
        return removed

    def publish(
        self,
        plugin_id: str,
        slot: str,
        items: Sequence[Mapping[str, Any]],
        *,
        host: Any,
        definitions: Sequence[Any],
        safe_mode_active: bool = False,
        supervisor: Any = None,
        now: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        d = next((item for item in definitions if item.id == plugin_id), None)
        if d is None or not _is_active(host, self.state_dir, d, safe_mode_active=safe_mode_active, supervisor=supervisor):
            raise UiSlotError(409, "plugin_disabled", f"{plugin_id} is not active")

        canon = canonical_slot(slot)
        granted = {canonical_slot(str(s)) for s in owner_state.granted_ui_slots(self.state_dir, d.manifest)}
        if canon not in granted:
            self._audit(host, d, method="ui.slot.publish", slot=canon, status="denied", allowed=False, detail="not_granted")
            raise UiSlotError(403, "not_granted", f"{plugin_id} does not hold consent for ui slot {canon}")

        self.sync(definitions, host=host, safe_mode_active=safe_mode_active, supervisor=supervisor)
        with self._lock:
            owner = self._owners.get(canon)
        declared_slots = {canonical_slot(str(s)) for s in (getattr(d.manifest, "ui_slots", ()) or ())}
        if canon not in CORE_UI_SLOTS and owner is None and canon not in declared_slots:
            self._audit(host, d, method="ui.slot.publish", slot=canon, status="unknown_slot", allowed=False, detail="unknown_slot")
            raise UiSlotError(404, "unknown_slot", f"ui slot {canon} has no active owner")

        ts = self._clock() if now is None else now
        with self._lock:
            hits = self._windows.setdefault(plugin_id, deque())
            while hits and hits[0] <= ts - UI_SLOT_RATE_WINDOW:
                hits.popleft()
            if len(hits) >= UI_SLOT_RATE_LIMIT:
                self._audit(host, d, method="ui.slot.publish", slot=canon, status="rate_limited", allowed=False, detail="rate_limited")
                raise UiSlotError(429, "rate_limited", f"too many ui slot updates for {plugin_id}")
            hits.append(ts)

        if not isinstance(items, (list, tuple)) or len(items) > MAX_SLOTS:
            self._audit(host, d, method="ui.slot.publish", slot=canon, status="invalid:bad_slots", allowed=False, detail="bad_slots")
            raise UiSlotError(422, "bad_slots", f"slot {canon} requires a list of at most {MAX_SLOTS} items")

        try:
            validated = self._validate_items(d, canon, items)
        except ui_doc.UiDocError as exc:
            self._audit(host, d, method="ui.slot.publish", slot=canon, status=f"invalid:{exc.code}", allowed=False, detail=exc.code)
            raise UiSlotError(422, exc.code, str(exc)) from exc

        payload_bytes = len(json.dumps([dict(x) for x in validated], separators=(",", ":")).encode("utf-8"))
        if payload_bytes > MAX_SLOT_BYTES:
            self._audit(
                host,
                d,
                method="ui.slot.publish",
                slot=canon,
                status="invalid:slot_payload_too_large",
                allowed=False,
                detail="slot_payload_too_large",
                size=payload_bytes,
            )
            raise UiSlotError(422, "slot_payload_too_large", f"slot {canon} payload exceeds {MAX_SLOT_BYTES} bytes")
        with self._lock:
            self._dynamic[(plugin_id, canon)] = validated
        self._audit(host, d, method="ui.slot.publish", slot=canon, status="ok", allowed=True, size=payload_bytes)
        _publish_slots(host)
        return [dict(x) for x in validated]

    def resolve(
        self,
        *,
        host: Any,
        definitions: Sequence[Any],
        safe_mode_active: bool = False,
        supervisor: Any = None,
    ) -> Dict[str, Any]:
        owners = self.sync(definitions, host=host, safe_mode_active=safe_mode_active, supervisor=supervisor)
        slots_out: Dict[str, List[Dict[str, Any]]] = {}
        for d in definitions:
            if not _is_active(host, self.state_dir, d, safe_mode_active=safe_mode_active, supervisor=supervisor):
                continue
            granted = {canonical_slot(str(s)) for s in owner_state.granted_ui_slots(self.state_dir, d.manifest)}
            if not granted:
                continue
            contrib = getattr(d.manifest, "ui_contribute", None)
            if not isinstance(contrib, Mapping):
                contrib = {}
            with self._lock:
                dyn_slots: Dict[str, Tuple[Dict[str, Any], ...]] = {
                    canonical_slot(s): v for (pid, s), v in self._dynamic.items() if pid == d.id
                }
            contrib_by_canon: Dict[str, List[Tuple[str, Any]]] = {}
            for raw_slot, raw_items in contrib.items():
                slot_str = str(raw_slot)
                contrib_by_canon.setdefault(canonical_slot(slot_str), []).append((slot_str, raw_items))
            candidate_canons = list(dict.fromkeys([*contrib_by_canon.keys(), *dyn_slots.keys()]))
            declared_slots = {canonical_slot(str(s)) for s in (getattr(d.manifest, "ui_slots", ()) or ())}
            key = _install_key(host, d)
            for canon in candidate_canons:
                if canon not in granted:
                    continue
                if canon not in CORE_UI_SLOTS and canon not in owners and canon not in declared_slots:
                    continue
                if canon in dyn_slots:
                    declared_slot = contrib_by_canon[canon][0][0] if canon in contrib_by_canon else canon
                    if dyn_slots[canon]:
                        dyn_bytes = len(json.dumps([dict(x) for x in dyn_slots[canon]], separators=(",", ":")).encode("utf-8"))
                        if dyn_bytes > MAX_SLOT_BYTES:
                            self._audit(
                                host,
                                d,
                                method="ui.slot.sync",
                                slot=canon,
                                status="invalid:slot_payload_too_large",
                                allowed=False,
                                detail="slot_payload_too_large",
                                size=dyn_bytes,
                            )
                            continue
                        bucket = slots_out.setdefault(canon, [])
                        for item in dyn_slots[canon]:
                            bucket.append({
                                "plugin_id": d.id,
                                "install_key": key,
                                "slot": canon,
                                "declared_slot": declared_slot,
                                "item": dict(item),
                            })
                    continue
                for declared_slot, raw_items in contrib_by_canon[canon]:
                    if not isinstance(raw_items, (list, tuple)):
                        continue
                    try:
                        items = self._validate_items(d, canon, raw_items)
                    except ui_doc.UiDocError as exc:
                        self._audit(host, d, method="ui.slot.sync", slot=canon, status=f"invalid:{exc.code}", allowed=False, detail=exc.code)
                        continue
                    if items:
                        static_bytes = len(json.dumps([dict(x) for x in items], separators=(",", ":")).encode("utf-8"))
                        if static_bytes > MAX_SLOT_BYTES:
                            self._audit(
                                host,
                                d,
                                method="ui.slot.sync",
                                slot=canon,
                                status="invalid:slot_payload_too_large",
                                allowed=False,
                                detail="slot_payload_too_large",
                                size=static_bytes,
                            )
                            continue
                        bucket = slots_out.setdefault(canon, [])
                        for item in items:
                            bucket.append({
                                "plugin_id": d.id,
                                "install_key": key,
                                "slot": canon,
                                "declared_slot": declared_slot,
                                "item": dict(item),
                            })
        return {"slots": slots_out, "owners": owners}


_REGISTRIES_LOCK = threading.RLock()
_REGISTRIES: Dict[str, UiSlotRegistry] = {}


def registry_for(state_dir: Path) -> UiSlotRegistry:
    key = os.path.realpath(state_dir)
    with _REGISTRIES_LOCK:
        reg = _REGISTRIES.get(key)
        if reg is None:
            reg = UiSlotRegistry(Path(key))
            _REGISTRIES[key] = reg
        return reg
