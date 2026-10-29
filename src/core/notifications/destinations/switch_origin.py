
from __future__ import annotations

import asyncio
from typing import Any, Mapping, Optional

import structlog

from src.core.notifications import doc_model, http, kind_specs
from src.core.notifications.destinations import secrets as secret_store
from src.core.notifications.settings_doc import view
from src.core.notifications.settings_doc.store import Doc, SettingsDocStore

log = structlog.get_logger(__name__)

_NTFY_DEFAULT_BASE = "https://ntfy.sh"


def needs_secret(kind_id: str) -> bool:
    return kind_id == kind_specs.KIND_WEBHOOK


def origin_for(kind_id: str, config: Mapping[str, Any], secrets: Mapping[str, Any]) -> Optional[str]:
    if kind_id == kind_specs.KIND_WEBHOOK:
        url = secrets.get("url")
    elif kind_id == kind_specs.KIND_NTFY:
        url = config.get("base_url") or _NTFY_DEFAULT_BASE
    else:
        return None
    return http.origin_of(url) if isinstance(url, str) and url else None


def value_for(origin: Optional[str]) -> Any:
    return origin or True


def keys_of(dest_id: str) -> tuple[str, str]:
    return view.allow_private_key(dest_id), view.allow_plain_http_key(dest_id)


async def effective(
    item: Mapping[str, Any], doc: Mapping[str, Any], secrets: secret_store.DestinationSecrets,
) -> dict[str, Any]:
    out = dict(item)
    names = ("allow_private", "allow_plain_http")
    if not any(out.get(n) for n in names):
        return out
    current: Optional[str] = None
    try:
        bundle = await secrets.get(out["id"]) if needs_secret(out["kind"]) else {}
        current = origin_for(out["kind"], out.get("config") or {}, bundle or {})
    except secret_store.SecretError:
        log.warning("notification_switch_view_secret_unavailable", dest_id=out["id"])
    for name, key in zip(names, keys_of(out["id"])):
        if out.get(name) and (current is None or view.switch_origin(doc, key) != current):
            out[name] = False
    return out


async def backfill(docs: SettingsDocStore, secrets: secret_store.DestinationSecrets) -> int:
    doc = await asyncio.to_thread(docs.snapshot)
    fill: dict[str, str] = {}
    for dest_id in view.dest_ids(doc):
        record = view.dest_record(doc, dest_id)
        spec = kind_specs.get_kind(record["kind"]) if record else None
        keys = [k for k in keys_of(dest_id) if doc["local"].get(k) is True]
        if not (record and spec and spec.allow_private and keys):
            continue
        bundle: Mapping[str, Any] = {}
        if needs_secret(spec.id):
            try:
                bundle = await secrets.get(dest_id) or {}
            except secret_store.SecretError:
                log.warning("notification_switch_backfill_secret_unavailable", dest_id=dest_id)
                continue
        origin = origin_for(spec.id, record.get("config") or {}, bundle)
        if origin:
            fill.update({k: origin for k in keys})
    if not fill:
        return 0

    def mutate(d: Doc, me: str) -> Optional[Doc]:
        changed = False
        for key, origin in fill.items():
            if d["local"].get(key) is True:
                d = doc_model.set_local(d, key, origin)
                changed = True
        return d if changed else None

    await asyncio.to_thread(docs.update, mutate)
    log.info("notification_switch_origin_backfilled", keys=len(fill))
    return len(fill)
