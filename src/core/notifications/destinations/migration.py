
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import urlsplit, urlunsplit

import structlog

from src.core import config_writer
from src.core.app_alerts import service as alert_service
from src.core.notifications import doc_model, kind_specs, types
from src.core.notifications.destinations import store as store_mod
from src.core.notifications.destinations import validate
from src.core.notifications.routing_view import RoutingWriter
from src.core.notifications.settings_doc import view
from src.core.notifications.settings_doc.store import Doc, SettingsDocStore

log = structlog.get_logger(__name__)

MIGRATED_KEY = doc_model.local_key("migration_v1")
DEFAULT_NTFY_BASE = "https://ntfy.sh"
MAX_SKIP_BOOTS = 3
ALERT_KEY = "notifications.migration_skipped"
ALERT_TITLE_KEY = "app_alert.notifications.migration_skipped.title"
ALERT_DETAIL_KEY = "app_alert.notifications.migration_skipped.detail"
HTTP_BASE_REASON = ("the old ntfy server address used plain http, which is not allowed any more. "
                    "change it to https and turn this on.")


@dataclass
class MigrationResult:

    migrated: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    abandoned: List[str] = field(default_factory=list)
    push_devices: int = 0
    complete: bool = False
    already_done: bool = False


def _channels(block: Mapping[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    text = lambda k: str(block.get(k) or "").strip()  # noqa: E731
    if text("slack_webhook_url"):
        out.append({"kind": "slack", "config": {}, "secrets": {"url": text("slack_webhook_url")},
                    "scrub": ["slack_webhook_url"]})
    if text("ntfy_topic"):
        base = text("ntfy_base_url")
        out.append({"kind": "ntfy", "config": {"base_url": base} if base and base != DEFAULT_NTFY_BASE else {},
                    "secrets": {"topic": text("ntfy_topic")}, "scrub": ["ntfy_topic"]})
    if text("pushover_token") and text("pushover_user_key"):
        out.append({"kind": "pushover", "config": {},
                    "secrets": {"app_token": text("pushover_token"), "user_key": text("pushover_user_key")},
                    "scrub": ["pushover_token", "pushover_user_key"]})
    return out


def _scrub(config_path: Path, keys: Sequence[str]) -> bool:
    state = {"retired": False}

    def mutate(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        block = data.get("notifications")
        if not isinstance(block, dict):
            return None
        new = dict(block)
        changed = False
        for key in keys:
            if new.get(key):
                new[key] = ""
                changed = True
        if "public_base_url" in new:
            state["retired"] = bool(new.pop("public_base_url"))
            changed = True
        return {**data, "notifications": new} if changed else None

    config_writer.commit(config_path, mutate)
    return state["retired"]


def _rewrite_bak(config_path: Path) -> None:
    config_writer.commit(config_path, lambda data: dict(data))


def _read_block(config_path: Path) -> Dict[str, Any]:
    block = config_writer.read_config(config_path).get("notifications")
    return dict(block) if isinstance(block, dict) else {}


def _channel_id(install_id: str, kind: str) -> str:
    return "d_" + hashlib.sha256(f"{install_id}:{kind}".encode()).hexdigest()[:12]


def _push_ticks(docs: SettingsDocStore, sub_ids: Sequence[str]) -> int:
    ticked = {"n": 0}

    def mutate(doc: Doc, me: str) -> Optional[Doc]:
        for sub_id in sub_ids:
            col = kind_specs.webpush_destination_id(sub_id)
            if any(doc_model.is_pinned(doc, doc_model.tick_path(col, t.id)) for t in types.ordered_types()):
                continue
            for type_id in sorted(types.NEEDS_YOU):
                doc = doc_model.set_local(doc, doc_model.tick_path(col, type_id), True)
            ticked["n"] += 1
        return doc if ticked["n"] else None

    docs.update(mutate)
    return ticked["n"]


def _skip_key(kind: str) -> str:
    return doc_model.local_key(f"migration_skips_{kind}")


def _https_base(base: str) -> Optional[str]:
    try:
        parts = urlsplit(base)
    except ValueError:
        return None
    return urlunsplit(parts._replace(scheme="https")) if parts.scheme.lower() == "http" else None


def _private_base(kind: str, https_base: str) -> bool:
    spec = kind_specs.get_kind(kind)
    if spec is None:
        return False
    try:
        validate.validate_fields(spec.public_fields, {"base_url": https_base}, spec, allow_private=False)
    except validate.InvalidDestination as exc:
        return exc.fields.get("base_url") == validate.PRIVATE_ADDRESS
    return False


async def _create(
    destinations: store_mod.DestinationStore, channel: Dict[str, Any], dest_id: str, enabled: bool,
    config: Dict[str, Any], plain_http: bool = False,
) -> None:
    kind = channel["kind"]
    if plain_http:
        await destinations.create(kind, kind, config, channel["secrets"], enabled=enabled, dest_id=dest_id,
                                  allow_private=True, allow_plain_http=True)
        return
    try:
        await destinations.create(kind, kind, config, channel["secrets"], enabled=enabled, dest_id=dest_id)
    except validate.InvalidDestination as exc:
        if exc.fields.get("base_url") != validate.PRIVATE_ADDRESS:
            raise
        await destinations.create(kind, kind, config, channel["secrets"], enabled=enabled, dest_id=dest_id,
                                  allow_private=True)


async def _raise_skip_alert(kinds: Sequence[str]) -> None:
    await asyncio.to_thread(lambda: alert_service.raise_alert(
        ALERT_KEY, source="notifications", severity="warn", title_key=ALERT_TITLE_KEY,
        params={"kinds": ", ".join(kinds)}, detail_key=ALERT_DETAIL_KEY))


async def migrate(
    config_path: Path, docs: SettingsDocStore, destinations: store_mod.DestinationStore,
    subscription_ids: Sequence[str] = (), writer: Optional[RoutingWriter] = None,
) -> MigrationResult:
    result = MigrationResult()
    if (await asyncio.to_thread(docs.snapshot))["local"].get(MIGRATED_KEY):
        result.already_done = result.complete = True
        return result
    try:
        block = await asyncio.to_thread(_read_block, config_path)
    except (OSError, ValueError):
        log.warning("notification_migration_config_unreadable")
        return result
    doc = await asyncio.to_thread(docs.update, lambda d, me: doc_model.set_local(d, doc_model.local_key("migration_started"), True))
    install_id = doc["local"]["local/install_id"]
    enabled = bool(block.get("enabled"))
    scrub_keys: List[str] = []
    newly_abandoned: List[str] = []
    for channel in _channels(block):
        kind, dest_id = channel["kind"], _channel_id(install_id, channel["kind"])
        if (await asyncio.to_thread(docs.snapshot))["local"].get(_skip_key(kind), 0) >= MAX_SKIP_BOOTS:
            result.abandoned.append(kind)
            continue
        config, channel_enabled, http_reason = dict(channel["config"]), enabled, False
        https = _https_base(config.get("base_url", ""))
        plain_http = bool(https) and _private_base(kind, https)
        if https and not plain_http:
            config["base_url"], channel_enabled, http_reason = https, False, True
        exists = view.dest_scope(await asyncio.to_thread(docs.snapshot), dest_id) is not None
        try:
            if not exists:
                await _create(destinations, channel, dest_id, channel_enabled, config, plain_http)
            if http_reason and writer is not None:
                await writer.disable_locally(dest_id, HTTP_BASE_REASON)
        except (validate.InvalidDestination, store_mod.KeychainUnavailable, store_mod.DestinationLimit, OSError) as exc:
            log.warning("notification_migration_channel_skipped", kind=kind, reason=type(exc).__name__)
            result.skipped.append(kind)
            count = (await asyncio.to_thread(docs.snapshot))["local"].get(_skip_key(kind), 0) + 1
            await asyncio.to_thread(docs.update, lambda d, me, k=kind, n=count: doc_model.set_local(d, _skip_key(k), n))
            if count >= MAX_SKIP_BOOTS:
                newly_abandoned.append(kind)
            continue
        scrub_keys += channel["scrub"]
        result.migrated.append(kind)
    retired = await asyncio.to_thread(_scrub, config_path, scrub_keys)
    if retired:
        log.info("notification_public_base_url_retired")
    if scrub_keys or retired:
        await asyncio.to_thread(_rewrite_bak, config_path)
    result.push_devices = await asyncio.to_thread(_push_ticks, docs, list(subscription_ids))
    if newly_abandoned:
        await _raise_skip_alert(newly_abandoned)
    if not [k for k in result.skipped if k not in newly_abandoned]:
        await asyncio.to_thread(docs.update, lambda d, me: doc_model.set_local(d, MIGRATED_KEY, True))
        result.complete = True
    log.info("notification_migration_done", migrated=result.migrated, skipped=result.skipped,
             push_devices=result.push_devices, complete=result.complete)
    return result
