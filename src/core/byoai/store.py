
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

import structlog
from pydantic import ValidationError

from src.config.byoai import BYOAI_KEY, ByoaiConfig, ConnectionConfig, ModelOverride, TargetRef
from src.core import config_writer
from src.core.byoai import keys as keys_module
from src.core.byoai.contracts import (
    AUTH_CLI_ACCOUNT, AUTH_NONE, ByoaiError, KIND_CLI, NotConfigured, StaleRevision,
)
from src.core.byoai.presets import auth_style, default_base_url, get_preset
from src.core.byoai.transport import key_origin, validate_base_url


logger = structlog.get_logger()

_CHANGE_LISTENERS: List[Callable[[int], None]] = []


def add_change_listener(listener: Callable[[int], None]) -> None:
    if listener not in _CHANGE_LISTENERS:
        _CHANGE_LISTENERS.append(listener)


def remove_change_listener(listener: Callable[[int], None]) -> None:
    if listener in _CHANGE_LISTENERS:
        _CHANGE_LISTENERS.remove(listener)


def _notify_listeners(revision: int) -> None:
    for listener in list(_CHANGE_LISTENERS):
        try:
            listener(revision)
        except Exception as exc:  # noqa: BLE001
            logger.warning("byoai_change_listener_failed", error=type(exc).__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ByoaiStore:

    def __init__(self, config_path: Path, *, keys: Optional[keys_module.KeyStore] = None,
                 clock: Callable[[], str] = _now) -> None:
        self._path = Path(config_path)
        self._keys = keys or keys_module.KeyStore()
        self._clock = clock

    @staticmethod
    def _block(data: Mapping[str, Any]) -> ByoaiConfig:
        try:
            return ByoaiConfig.model_validate(data.get(BYOAI_KEY) or {})
        except ValidationError:
            raise ByoaiError("the byoai block in config.json is invalid") from None

    def read(self) -> ByoaiConfig:
        try:
            data = config_writer.read_config(self._path)
        except FileNotFoundError:
            data = {}
        return self._block(data)

    def _write(self, change: Callable[[ByoaiConfig], None],
               expected_revision: Optional[int]) -> ByoaiConfig:
        def precondition(data: Dict[str, Any]) -> Optional[str]:
            if expected_revision is not None and self._block(data).revision != expected_revision:
                return config_writer.STALE_REVISION
            return None

        def mutate(data: Dict[str, Any]) -> Dict[str, Any]:
            block = self._block(data)
            change(block)
            block.revision += 1
            checked = ByoaiConfig.model_validate(block.model_dump())
            return {**data, BYOAI_KEY: checked.model_dump(mode="json")}

        outcome = config_writer.commit(self._path, mutate, precondition=precondition)
        if outcome.status == config_writer.STALE_REVISION:
            raise StaleRevision(f"byoai revision is {self._block(outcome.data).revision}")
        if not outcome.wrote:
            raise ByoaiError(f"config write did not land ({outcome.status})")
        written = self._block(outcome.data)
        _notify_listeners(written.revision)
        return written

    @staticmethod
    def _find(block: ByoaiConfig, connection_id: str) -> ConnectionConfig:
        for item in block.connections:
            if item.id == connection_id:
                return item
        raise NotConfigured(f"no connection {connection_id}")

    def _set_key(self, item: ConnectionConfig, key: str) -> None:
        preset = get_preset(item.preset)
        if auth_style(preset, item.options) in (AUTH_NONE, AUTH_CLI_ACCOUNT):
            raise ByoaiError(f"{preset.id} takes no key")
        item.key_hint = self._keys.set(item.id, key)
        item.key_host = key_origin(item.base_url)

    def _clear_key(self, item: ConnectionConfig) -> None:
        if not self._keys.delete(item.id) and not self._keys.confirmed_gone(item.id):
            raise ByoaiError("the keychain could not be reached, so the key was not removed; unlock it and try again")
        item.key_host = None
        item.key_hint = ""

    @staticmethod
    def _checked_url(preset_kind: str, url: str) -> str:
        return "" if preset_kind == KIND_CLI else validate_base_url(url)

    def add_connection(self, *, preset: str, label: str = "", base_url: str = "",
                       options: Optional[Mapping[str, Any]] = None, key: Optional[str] = None,
                       expected_revision: Optional[int] = None) -> ConnectionConfig:
        spec = get_preset(preset)
        opts = dict(options or {})
        for field in spec.fields:
            if field.default is not None:
                opts.setdefault(field.name, field.default)
        url = self._checked_url(spec.kind, base_url or default_base_url(spec, opts))
        created: Dict[str, ConnectionConfig] = {}

        def change(block: ByoaiConfig) -> None:
            taken = {c.id for c in block.connections}
            cid = f"{spec.id.replace('_', '-')}-{secrets.token_hex(2)}"
            while cid in taken:
                cid = f"{spec.id.replace('_', '-')}-{secrets.token_hex(2)}"
            now = self._clock()
            try:
                item = ConnectionConfig(id=cid, preset=spec.id, label=label or spec.label,
                                        base_url=url, options=opts, created_at=now, updated_at=now)
            except ValidationError as exc:
                raise ByoaiError(_first_error(exc)) from None
            if key is not None:
                self._set_key(item, key)
            block.connections.append(item)
            created["item"] = item

        self._write(change, expected_revision)
        return created["item"]

    def update_connection(self, connection_id: str, *, label: Optional[str] = None,
                          base_url: Optional[str] = None,
                          options: Optional[Mapping[str, Any]] = None,
                          enabled: Optional[bool] = None,
                          models: Optional[Mapping[str, Mapping[str, Any]]] = None,
                          key: Optional[str] = None,
                          expected_revision: Optional[int] = None) -> ConnectionConfig:
        done: Dict[str, ConnectionConfig] = {}

        def change(block: ByoaiConfig) -> None:
            item = self._find(block, connection_id)
            spec = get_preset(item.preset)
            if label is not None:
                item.label = label
            if options is not None:
                try:
                    item.options = ConnectionConfig(
                        id=item.id, preset=item.preset, options=dict(options)).options
                except ValidationError as exc:
                    raise ByoaiError(_first_error(exc)) from None
            if base_url is not None:
                item.base_url = self._checked_url(spec.kind, base_url)
            if enabled is not None:
                item.enabled = enabled
            if models is not None:
                try:
                    item.models = {m: ModelOverride.model_validate(o) for m, o in models.items()}
                except ValidationError as exc:
                    raise ByoaiError(_first_error(exc)) from None
            if key is not None:
                self._set_key(item, key)
            elif item.key_host is not None and item.key_host != key_origin(item.base_url):
                self._clear_key(item)
            item.updated_at = self._clock()
            done["item"] = item

        self._write(change, expected_revision)
        return done["item"]

    def clear_key(self, connection_id: str, *, expected_revision: Optional[int] = None) -> ConnectionConfig:
        done: Dict[str, ConnectionConfig] = {}

        def change(block: ByoaiConfig) -> None:
            item = self._find(block, connection_id)
            self._clear_key(item)
            item.updated_at = self._clock()
            done["item"] = item

        self._write(change, expected_revision)
        return done["item"]

    def delete_connection(self, connection_id: str, *, expected_revision: Optional[int] = None) -> None:
        def change(block: ByoaiConfig) -> None:
            self._clear_key(self._find(block, connection_id))
            block.connections = [c for c in block.connections if c.id != connection_id]
            block.defaults = {k: v for k, v in block.defaults.items() if v.connection != connection_id}
            block.features = {k: v for k, v in block.features.items() if v.connection != connection_id}

        self._write(change, expected_revision)

    def set_default(self, capability: str, target: Optional[TargetRef], *,
                    expected_revision: Optional[int] = None) -> ByoaiConfig:
        return self._write(lambda b: self._route(b, b.defaults, capability, target), expected_revision)

    def set_feature(self, feature_id: str, target: Optional[TargetRef], *,
                    expected_revision: Optional[int] = None) -> ByoaiConfig:
        return self._write(lambda b: self._route(b, b.features, feature_id, target), expected_revision)

    def _route(self, block: ByoaiConfig, table: Dict[str, TargetRef], name: str,
               target: Optional[TargetRef]) -> None:
        if not name:
            raise ByoaiError("a name is required")
        if target is None:
            table.pop(name, None)
            return
        self._find(block, target.connection)
        table[name] = target


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    return str(err.get("msg", "invalid"))
