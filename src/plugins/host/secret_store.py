
from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Protocol, Tuple

import structlog

from src.plugins.host.identity import data_key, keychain_service, lookup
from src.plugins.sdk.manifest import Manifest
from src.core import relay_keychain
from src.core.json_artifact import atomic_write_json, read_json_object

logger = structlog.get_logger()

FILE = "secrets.json"
VERSION = 1
_lock = threading.RLock()


def network_key(cplug_id: str, state_dir: Optional[Path] = None) -> str:
    record = lookup(state_dir, cplug_id) if state_dir is not None else None
    return data_key(record, cplug_id)


class SecretError(Exception):

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


class Keychain(Protocol):

    def read(self, service: str, account: str) -> Optional[str]: ...

    def write(self, service: str, account: str, secret: str) -> None: ...

    def delete(self, service: str, account: str) -> bool: ...


class _Login:

    def read(self, service: str, account: str) -> Optional[str]:
        return relay_keychain.read_password(service, account)

    def write(self, service: str, account: str, secret: str) -> None:
        relay_keychain.write_password(service, account, secret)

    def delete(self, service: str, account: str) -> bool:
        return relay_keychain.delete_password(service, account)


class SecretsSnapshot:

    def __init__(self, key: str, prior_ledger: Dict[str, Any], prior_keychain: Dict[str, Optional[str]]) -> None:
        self.key = key
        self.prior_ledger = prior_ledger
        self.prior_keychain = prior_keychain


class SecretStore:

    def __init__(self, state_dir: Path, *, keychain: Optional[Keychain] = None) -> None:
        self._path = Path(state_dir) / "cplugs" / FILE
        self._keychain: Keychain = keychain or _Login()

    def _read(self) -> Dict[str, Dict[str, list]]:
        if not self._path.exists():
            return {}
        data = read_json_object(self._path, log_event="cplug_secret_ledger_unreadable")
        if data is None or not isinstance(data.get("secrets"), dict):
            raise SecretError("secrets_unreadable", "the secret ledger could not be read")
        return data["secrets"]

    def _write(self, secrets: Dict[str, Any]) -> None:
        if not atomic_write_json(self._path, {"version": VERSION, "secrets": secrets}, log_event="cplug_secret_ledger_write_failed"):
            raise SecretError("secrets_unwritable", "the secret ledger could not be written")

    @staticmethod
    def _bindings(manifest: Any, name: str) -> Tuple[str, ...]:
        hosts = set(manifest.network.secret_hosts(name))
        webhooks = getattr(manifest, "webhooks", None)
        if isinstance(webhooks, Mapping):
            for hook_name, cfg in webhooks.items():
                if isinstance(cfg, Mapping) and cfg.get("hmac_secret") == name:
                    hosts.add(f"webhook:{hook_name}")
        is_v2 = getattr(manifest, "schema_version", 1) >= 2 or getattr(manifest, "schema", 1) == 2
        if is_v2 and not hosts and any(s.name == name for s in getattr(manifest.network, "secrets", ())):
            hosts.update(h.host for h in getattr(manifest.network, "network_hosts", ()))
        return tuple(sorted(hosts))

    def set(self, key: str, manifest: Manifest, name: str, value: str) -> None:
        bindings = self.validate_one(manifest, name, value)
        with _lock:
            ledger = self._read()
            try:
                self._keychain.write(keychain_service(key), name, value)
            except relay_keychain.KeychainWriteError as exc:
                raise SecretError("keychain_refused", "the Keychain refused the value") from exc
            ledger.setdefault(key, {})[name] = list(bindings)
            self._write(ledger)
        logger.info("cplug_secret_set", cplug=manifest.id, secret=name, hosts=list(bindings))

    @classmethod
    def validate_one(cls, manifest: Any, name: str, value: Any) -> Tuple[str, ...]:
        if name not in {s.name for s in manifest.network.secrets}:
            raise SecretError("secret_unknown", f"{manifest.id} declares no secret {name}")
        bindings = cls._bindings(manifest, name)
        if not bindings:
            raise SecretError("secret_unbound", f"no network host or webhook of {manifest.id} uses {name}")
        if not isinstance(value, str) or not relay_keychain.is_safe_secret(value):
            raise SecretError("secret_invalid", "a value may only use letters, digits and _ . ~ + / = : - (no spaces or quotes)")
        return bindings

    def set_many(self, key: str, manifest: Any, secrets_map: Mapping[str, str]) -> Optional[SecretsSnapshot]:
        if not secrets_map:
            return None
        bindings_by_name: Dict[str, Tuple[str, ...]] = {
            name: self.validate_one(manifest, name, val) for name, val in secrets_map.items()
        }
        with _lock:
            prior_ledger = copy.deepcopy(self._read())
            ledger = copy.deepcopy(prior_ledger)
            service = keychain_service(key)
            prior_kc: Dict[str, Optional[str]] = {name: self._keychain.read(service, name) for name in secrets_map}
            written: list[str] = []
            try:
                for name, val in secrets_map.items():
                    try:
                        self._keychain.write(service, name, val)
                    except relay_keychain.KeychainWriteError as exc:
                        raise SecretError("keychain_refused", "the Keychain refused the value") from exc
                    written.append(name)
                    ledger.setdefault(key, {})[name] = list(bindings_by_name[name])
                self._write(ledger)
            except BaseException:
                for name in reversed(written):
                    prev = prior_kc.get(name)
                    try:
                        if prev is None:
                            self._keychain.delete(service, name)
                        else:
                            self._keychain.write(service, name, prev)
                    except Exception:  # noqa: BLE001
                        logger.warning("cplug_secret_rollback_failed", cplug=manifest.id, secret=name)
                raise
        for name, bindings in bindings_by_name.items():
            logger.info("cplug_secret_set", cplug=manifest.id, secret=name, hosts=list(bindings))
        return SecretsSnapshot(key, prior_ledger, prior_kc)

    def restore_snapshot(self, snapshot: Optional[SecretsSnapshot]) -> None:
        if snapshot is None:
            return
        with _lock:
            service = keychain_service(snapshot.key)
            for name, prev in snapshot.prior_keychain.items():
                try:
                    if prev is None:
                        self._keychain.delete(service, name)
                    else:
                        self._keychain.write(service, name, prev)
                except Exception:  # noqa: BLE001
                    logger.warning("cplug_secret_restore_failed", key=snapshot.key, secret=name)
            try:
                self._write(snapshot.prior_ledger)
            except SecretError:
                logger.warning("cplug_secret_ledger_restore_failed", key=snapshot.key)

    def status(self, key: str, manifest: Manifest, name: str) -> Dict[str, bool]:
        with _lock:
            bound = self._read().get(key, {}).get(name)
        stored = bound is not None and bool(self._keychain.read(keychain_service(key), name))
        current = stored and tuple(sorted(bound)) == self._bindings(manifest, name)
        return {"secret_present": bool(current), "needs_reentry": bool(stored and not current)}

    def value_for(self, key: str, manifest: Manifest, name: str, host: str) -> Optional[str]:
        with _lock:
            bound = self._read().get(key, {}).get(name)
        if bound is None or host not in bound or tuple(sorted(bound)) != self._bindings(manifest, name):
            return None
        return self._keychain.read(keychain_service(key), name) or None

    def webhook_secret(self, key: str, manifest: Any, name: str, hook: str) -> Optional[str]:
        with _lock:
            bound = self._read().get(key, {}).get(name)
        if bound is None or f"webhook:{hook}" not in bound or tuple(sorted(bound)) != self._bindings(manifest, name):
            return None
        return self._keychain.read(keychain_service(key), name) or None

    def delete(self, key: str, name: str) -> bool:
        with _lock:
            ledger = self._read()
            had = ledger.get(key, {}).pop(name, None) is not None
            removed = self._keychain.delete(keychain_service(key), name)
            if had:
                self._write(ledger)
        return had or removed

    def holds(self, key: str) -> bool:
        with _lock:
            return bool(self._read().get(key))

    def purge(self, key: str) -> int:
        with _lock:
            ledger = self._read()
            names = list(ledger.pop(key, {}))
            for name in names:
                self._keychain.delete(keychain_service(key), name)
            if names:
                self._write(ledger)
        return len(names)
