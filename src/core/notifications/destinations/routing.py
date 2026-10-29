
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

import structlog

from src.core.notifications import doc_model, kind_specs
from src.core.notifications.routing_view import DestinationView, RoutingView
from src.core.notifications.settings_doc import mutes, view
from src.core.notifications.settings_doc.store import Doc, SettingsDocStore

log = structlog.get_logger(__name__)

SUBSCRIPTION_TTL_SECONDS = 2.0


def subscription_label(row: Mapping[str, Any]) -> str:
    from src.core.web_push.endpoints import host_of  # noqa: PLC0415

    try:
        host = host_of(str(row.get("endpoint", "")))
    except (ValueError, TypeError):
        host = ""
    return f"web push ({host})" if host else "web push device"


def native_device_label(row: Mapping[str, Any]) -> str:
    platform = str(row.get("platform") or "").strip()
    return f"{platform} app" if platform else "app device"


class RoutingProvider:

    def __init__(
        self, doc_store: SettingsDocStore, subscriptions: Callable[[], Sequence[Mapping[str, Any]]] = lambda: (),
        native_devices: Callable[[], Sequence[Mapping[str, Any]]] = lambda: (), *, clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._docs = doc_store
        self._subscriptions = subscriptions
        self._native_devices = native_devices
        self._clock = clock
        self._cached: Optional[RoutingView] = None
        self._key: Optional[tuple] = None
        self._built_at = 0.0

    def view(self) -> RoutingView:
        doc = self._docs.snapshot()
        now = self._clock()
        key = (doc["rev"],)
        if self._cached is not None and self._key == key and now - self._built_at < SUBSCRIPTION_TTL_SECONDS:
            return self._cached
        try:
            rows = list(self._subscriptions())
        except (OSError, ValueError):
            log.warning("notification_subscriptions_unreadable")
            rows = []
        try:
            devices = list(self._native_devices())
        except (OSError, ValueError):
            log.warning("notification_native_devices_unreadable")
            devices = []
        pushes = [view.webpush_view(doc, str(r["id"]), subscription_label(r)) for r in rows if r.get("id")]
        pushes += [view.apns_view(doc, str(r["id"]), native_device_label(r)) for r in devices if r.get("id")]
        owners = {kind_specs.webpush_destination_id(str(r["id"])): str(r["device_id"])
                  for r in rows if r.get("id") and r.get("device_id")}
        owners.update({kind_specs.apns_destination_id(str(r["id"])): str(r["device_id"])
                       for r in devices if r.get("id") and r.get("device_id")})
        self._cached = view.DocRoutingView(doc, pushes, _owner_keys(owners))
        self._key, self._built_at = key, now
        return self._cached

    async def disable_locally(self, dest_id: str, reason: str) -> None:
        if not kind_specs.is_destination_id(dest_id):
            return

        def mutate(doc: Doc, me: str) -> Optional[Doc]:
            if view.dest_scope(doc, dest_id) is None:
                return None
            path = doc_model.dest_path(dest_id)
            current = doc["local"].get(path)
            overlay = dict(current) if isinstance(current, dict) else {}
            overlay["enabled"] = False
            overlay["disabled_reason"] = reason[:200]
            return doc_model.set_local(doc, path, overlay)

        await asyncio.to_thread(self._docs.update, mutate)
        log.warning("notification_destination_disabled_locally", dest_id=dest_id, reason=reason)


def _owner_keys(owners: Mapping[str, str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for column, device in owners.items():
        try:
            out[column] = mutes.link_device_key(device)
        except ValueError:
            continue
    return out
