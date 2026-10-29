
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

import structlog

from src.cplugs.host.identity import data_key, keychain_service, lookup
from src.cplugs.sdk.manifest import Manifest
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

    def set(self, key: str, manifest: Manifest, name: str, value: str) -> None:
        hosts = manifest.network.secret_hosts(name)
        if name not in {s.name for s in manifest.network.secrets}:
            raise SecretError("secret_unknown", f"{manifest.id} declares no secret {name}")
        if not hosts:
            raise SecretError("secret_unbound", f"no network host of {manifest.id} uses {name}")
        if not isinstance(value, str) or not relay_keychain.is_safe_secret(value):
            raise SecretError("secret_invalid", "a value may only use letters, digits and _ . ~ + / = : - (no spaces or quotes)")
        with _lock:
            ledger = self._read()
            try:
                self._keychain.write(keychain_service(key), name, value)
            except relay_keychain.KeychainWriteError as exc:
                raise SecretError("keychain_refused", "the Keychain refused the value") from exc
            ledger.setdefault(key, {})[name] = list(hosts)
            self._write(ledger)
        logger.info("cplug_secret_set", cplug=manifest.id, secret=name, hosts=list(hosts))

    def status(self, key: str, manifest: Manifest, name: str) -> Dict[str, bool]:
        with _lock:
            bound = self._read().get(key, {}).get(name)
        stored = bound is not None and bool(self._keychain.read(keychain_service(key), name))
        current = stored and tuple(sorted(bound)) == manifest.network.secret_hosts(name)
        return {"secret_present": bool(current), "needs_reentry": bool(stored and not current)}

    def value_for(self, key: str, manifest: Manifest, name: str, host: str) -> Optional[str]:
        with _lock:
            bound = self._read().get(key, {}).get(name)
        if bound is None or host not in bound or tuple(sorted(bound)) != manifest.network.secret_hosts(name):
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
