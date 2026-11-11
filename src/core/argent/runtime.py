
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.core.argent.device_login import DeviceLogin
from src.core.argent.store import ArgentStore
from src.core.argent.token_store import TokenStore


@dataclass
class Runtime:

    store: ArgentStore
    tokens: TokenStore
    login: DeviceLogin


_runtime: Optional[Runtime] = None


def get_runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        store, tokens = ArgentStore(), TokenStore()
        _runtime = Runtime(store=store, tokens=tokens, login=DeviceLogin(store, tokens))
    return _runtime


def set_runtime(runtime: Optional[Runtime]) -> None:
    global _runtime
    _runtime = runtime
