
from __future__ import annotations

import asyncio
import secrets as _secrets
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional

import structlog

from src.core.notifications import doc_model, kind_specs, types
from src.core.notifications.destinations import secrets as secret_store
from src.core.notifications.destinations import switch_origin, validate
from src.core.notifications.settings_doc import view
from src.core.notifications.sync import seen
from src.core.notifications.settings_doc.store import Doc, SettingsDocStore
from src.core.notifications.settings_doc.ticks import SCOPE_GLOBAL, SCOPE_LOCAL

log = structlog.get_logger(__name__)

MAX_GLOBAL_DESTINATIONS = 40


class UnknownDestination(LookupError):
    pass


class DestinationLimit(Exception):
    pass


class KeychainUnavailable(Exception):
    pass


@dataclass(frozen=True)
class CreateResult:

    destination: Dict[str, Any]
    signing_secret: Optional[str]


def _tick_ids_for(doc: Doc, kind: str) -> List[str]:
    return [
        row.id for row in types.ordered_types()
        if view.default_tick(doc, row.id) and kind not in row.seed_excluded_kinds and not row.defaults.outside_locked_off
    ]


def owned_paths(doc: Doc, dest_id: str) -> List[str]:
    marks = (f"{doc_model.KIND_DEST}/{dest_id}", f"{doc_model.KIND_TICK}/{dest_id}/", f"{doc_model.KIND_EXTRA}/{dest_id}/")
    keys = set(doc["global"]) | set(doc["local"])
    return sorted(p for p in keys if p == marks[0] or p.startswith(marks[1]) or p.startswith(marks[2]))


class DestinationStore:

    def __init__(
        self, doc_store: SettingsDocStore, secrets: Optional[secret_store.DestinationSecrets] = None,
        *, new_id: Callable[[], str] = kind_specs.new_destination_id, clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._docs = doc_store
        self._secrets = secrets or secret_store.DestinationSecrets()
        self._new_id = new_id
        self._clock = clock or time.time

    async def reported(self, item: Dict[str, Any], doc: Doc) -> Dict[str, Any]:
        return await switch_origin.effective(item, doc, self._secrets)

    async def list(self) -> List[Dict[str, Any]]:
        doc = await asyncio.to_thread(self._docs.snapshot)
        items = [d for d in (view.destination_dict(doc, i) for i in view.dest_ids(doc)) if d is not None]
        return [await switch_origin.effective(d, doc, self._secrets) for d in items]

    async def get(self, dest_id: str) -> Dict[str, Any]:
        doc = await asyncio.to_thread(self._docs.snapshot)
        found = view.destination_dict(doc, dest_id) if kind_specs.is_destination_id(dest_id) else None
        if found is None:
            raise UnknownDestination(dest_id)
        return await switch_origin.effective(found, doc, self._secrets)

    async def create(
        self, kind: str, name: str, config: Mapping[str, Any], secret_values: Mapping[str, Any],
        *, scope: str = SCOPE_GLOBAL, enabled: bool = True, dest_id: Optional[str] = None,
        allow_private: Optional[bool] = None, allow_plain_http: Optional[bool] = None,
    ) -> CreateResult:
        spec = kind_specs.get_kind(kind)
        if spec is None or spec.virtual:
            raise validate.InvalidDestination({"kind": validate.BAD_VALUE})
        if scope not in (SCOPE_GLOBAL, SCOPE_LOCAL):
            raise validate.InvalidDestination({"scope": validate.BAD_VALUE})
        clean_name = validate.check_name(name)
        private = validate.check_allow_private(spec, False if allow_private is None else allow_private)
        plain = validate.check_allow_plain_http(spec, False if allow_plain_http is None else allow_plain_http, private)
        public = validate.typed_config(
            spec, validate.validate_fields(spec.public_fields, config, spec, allow_private=private, allow_plain_http=plain))
        values = validate.validate_fields(
            spec.secret_fields, secret_values, spec, allow_private=private, allow_plain_http=plain)
        signing: Optional[str] = None
        if kind == kind_specs.KIND_WEBHOOK and not values.get("signing_secret"):
            signing = _secrets.token_urlsafe(32)
            values["signing_secret"] = signing
        dest_id = dest_id or self._new_id()
        if not await self._secrets.put_verified(dest_id, values):
            await self._drop_secret(dest_id)
            raise KeychainUnavailable()
        record = {"kind": kind, "name": clean_name, "enabled": bool(enabled), "config": public,
                  "secret_fields": sorted(values), "secret_rev": 1}

        def mutate(doc: Doc, me: str) -> Optional[Doc]:
            if scope == SCOPE_GLOBAL and sum(
                1 for i in view.dest_ids(doc) if view.dest_scope(doc, i) == view.SRC_GLOBAL
            ) >= MAX_GLOBAL_DESTINATIONS:
                raise DestinationLimit()
            def put(d: Doc, path: str, val: Any) -> Doc:
                return doc_model.set_global(d, path, val, me) if scope == SCOPE_GLOBAL else doc_model.set_local(d, path, val)

            doc = put(doc, doc_model.dest_path(dest_id), record)
            if scope == SCOPE_GLOBAL:
                doc = seen.mark_seen(doc, dest_id, 1)
            for type_id in _tick_ids_for(doc, kind):
                doc = put(doc, doc_model.tick_path(dest_id, type_id), True)
            approved = switch_origin.value_for(switch_origin.origin_for(kind, public, values))
            for key, on in zip(switch_origin.keys_of(dest_id), (private, plain)):
                if on:
                    doc = doc_model.set_local(doc, key, approved)
            return doc

        doc = await self._write_doc(mutate, lambda: self._drop_secret(dest_id))
        log.info("notification_destination_created", dest_id=dest_id, kind=kind, scope=scope)
        return CreateResult(await switch_origin.effective(view.destination_dict(doc, dest_id) or {}, doc, self._secrets), signing)

    async def _write_doc(self, mutate: Callable[[Doc, str], Optional[Doc]],
                         undo: Optional[Callable[[], Awaitable[None]]]) -> Doc:
        write = asyncio.ensure_future(asyncio.to_thread(self._docs.update, mutate))
        write.add_done_callback(lambda t: t.cancelled() or t.exception())
        try:
            return await asyncio.shield(write)
        except asyncio.CancelledError:
            raise
        except BaseException:
            if undo is not None:
                await undo()
            raise

    async def update(self, dest_id: str, **changes: Any) -> Dict[str, Any]:
        async with self._secrets.lock_for(dest_id):
            return await self._update(dest_id, **changes)

    async def _update(
        self, dest_id: str, *, name: Optional[str] = None, enabled: Optional[bool] = None,
        config: Optional[Mapping[str, Any]] = None, secret_patch: Optional[Mapping[str, Any]] = None,
        local_only: bool = False, allow_private: Optional[bool] = None, allow_plain_http: Optional[bool] = None,
    ) -> Dict[str, Any]:
        doc = await asyncio.to_thread(self._docs.snapshot)
        record = view.dest_record(doc, dest_id) if kind_specs.is_destination_id(dest_id) else None
        spec = kind_specs.get_kind(record["kind"]) if record else None
        if record is None or spec is None:
            raise UnknownDestination(dest_id)
        new_name = validate.check_name(name) if name is not None else None
        if allow_private is not None:
            validate.check_allow_private(spec, allow_private)
        private = view.allow_private(doc, dest_id) if allow_private is None else allow_private
        if allow_plain_http is not None:
            validate.check_allow_plain_http(spec, allow_plain_http, private)
        plain = (view.allow_plain_http(doc, dest_id) if allow_plain_http is None else allow_plain_http) and private
        new_public = None
        if config is not None:
            merged_cfg = {**record.get("config", {}), **dict(config)}
            new_public = validate.typed_config(
                spec, validate.validate_fields(
                    spec.public_fields, merged_cfg, spec, allow_private=private, allow_plain_http=plain))
        set_names = list(record.get("secret_fields") or [])
        url_changed = spec.id == kind_specs.KIND_NTFY and bool(config and "base_url" in config)
        patch = {k: v for k, v in (secret_patch or {}).items() if isinstance(v, (str, list, tuple)) and v}
        previous: Optional[Dict[str, str]] = None
        if patch:
            try:
                previous = await self._secrets.get(dest_id)
            except secret_store.SecretError:
                raise KeychainUnavailable() from None
            normal = validate.validate_fields(spec.secret_fields, patch, spec, existing=previous or {}, allow_private=private,
                                           allow_plain_http=plain)
            merged = secret_store.merge(previous, normal)
            validate.validate_fields(spec.secret_fields, merged, spec, existing={}, allow_private=private, allow_plain_http=plain)
            if not await self._secrets.put_verified(dest_id, merged):
                await self._restore(dest_id, previous)
                raise KeychainUnavailable()
            set_names = sorted(merged)
            url_changed = url_changed or (spec.id == kind_specs.KIND_WEBHOOK and "url" in patch)
        explicit = (allow_private is True, allow_plain_http is True)
        stored = [doc["local"].get(k) for k in switch_origin.keys_of(dest_id)]
        approved: Any = None
        if (private or plain) and (url_changed or any(explicit) or any(v is True for v in stored)):
            bundle = merged if patch else None
            if bundle is None and switch_origin.needs_secret(spec.id):
                try:
                    bundle = await self._secrets.get(dest_id) or {}
                except secret_store.SecretError:
                    raise KeychainUnavailable() from None
            approved = switch_origin.value_for(switch_origin.origin_for(
                spec.id, new_public if new_public is not None else record.get("config") or {}, bundle or {}))

        def mutate(d: Doc, me: str) -> Optional[Doc]:
            if view.dest_scope(d, dest_id) is None:
                raise UnknownDestination(dest_id)
            global_dest = view.dest_scope(d, dest_id) == view.SRC_GLOBAL
            path = doc_model.dest_path(dest_id)
            base = view.dest_record(d, dest_id) or {}
            if global_dest:
                base = dict(d["global"][path]["val"])
            changes: Dict[str, Any] = {}
            if new_name is not None:
                changes["name"] = new_name
            if new_public is not None:
                changes["config"] = new_public
            new_rev = seen.record_rev(base) + 1
            if patch:
                changes["secret_fields"] = set_names
                changes["secret_rev"] = new_rev
            overlay_now = d["local"].get(path) if isinstance(d["local"].get(path), dict) else {}
            to_overlay = global_dest and (local_only or "enabled" in overlay_now)
            if enabled is not None and not to_overlay:
                changes["enabled"] = bool(enabled)
            if changes:
                full = {**base, **changes}
                d = doc_model.set_global(d, path, full, me) if global_dest else doc_model.set_local(d, path, full)
            if enabled is not None and to_overlay:
                d = doc_model.set_local(d, path, {**overlay_now, "enabled": bool(enabled)})
            if patch and global_dest:
                d = seen.mark_seen(d, dest_id, new_rev)
            touched = (allow_private is not None, allow_plain_http is not None or allow_private is False)
            for key, on, was_touched in zip(switch_origin.keys_of(dest_id), (private, plain), touched):
                fresh = any(explicit) or url_changed or not isinstance(d["local"].get(key), str)
                if on and approved is not None and fresh and d["local"].get(key) != approved:
                    d = doc_model.set_local(d, key, approved)
                elif was_touched and not on:
                    d = doc_model.clear_local(d, key)
            return d

        doc = await self._write_doc(mutate, (lambda: self._restore(dest_id, previous)) if patch else None)
        log.info("notification_destination_updated", dest_id=dest_id, secrets_changed=bool(patch))
        return await switch_origin.effective(view.destination_dict(doc, dest_id) or {}, doc, self._secrets)

    async def delete(self, dest_id: str) -> None:
        def mutate(doc: Doc, me: str) -> Optional[Doc]:
            scope = view.dest_scope(doc, dest_id) if kind_specs.is_destination_id(dest_id) else None
            if scope is None:
                raise UnknownDestination(dest_id)
            for path in owned_paths(doc, dest_id):
                entry = doc["global"].get(path)
                if entry is not None and not doc_model.is_tombstone(entry):
                    doc = doc_model.delete_global(doc, path, me, self._clock())
                doc = doc_model.clear_local(doc, path)
            doc = doc_model.clear_local(doc, view.allow_private_key(dest_id))
            return seen.forget(doc_model.clear_local(doc, view.allow_plain_http_key(dest_id)), dest_id)

        await asyncio.to_thread(self._docs.update, mutate)
        await self._drop_secret(dest_id)
        log.info("notification_destination_deleted", dest_id=dest_id)

    async def seed_destination_ticks(self, dest_id: str, kind: str) -> None:
        if not kind_specs.is_push_destination_id(dest_id):
            raise ValueError("only a web push or native app destination is seeded this way")

        def mutate(doc: Doc, me: str) -> Optional[Doc]:
            changed = False
            for type_id in _tick_ids_for(doc, kind):
                path = doc_model.tick_path(dest_id, type_id)
                if not doc_model.is_pinned(doc, path):
                    doc = doc_model.set_local(doc, path, True)
                    changed = True
            return doc if changed else None

        await asyncio.to_thread(self._docs.update, mutate)

    async def drop_local_destination(self, dest_id: str) -> None:
        def mutate(doc: Doc, me: str) -> Optional[Doc]:
            owned = [p for p in owned_paths(doc, dest_id) if p in doc["local"]]
            for path in owned:
                doc = doc_model.clear_local(doc, path)
            return doc if owned else None

        await asyncio.to_thread(self._docs.update, mutate)

    async def _drop_secret(self, dest_id: str) -> None:
        try:
            await self._secrets.delete(dest_id)
        except (secret_store.SecretError, OSError) as exc:
            log.warning("notification_secret_cleanup_failed", dest_id=dest_id, error=type(exc).__name__)

    async def _restore(self, dest_id: str, previous: Optional[Mapping[str, str]]) -> None:
        try:
            if previous:
                await self._secrets.put(dest_id, previous)
        except secret_store.SecretError as exc:
            log.warning("notification_secret_restore_failed", dest_id=dest_id, error=type(exc).__name__)
