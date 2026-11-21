
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple, TypeVar

T = TypeVar("T")

MAX_AGE_SECONDS = 60.0

LOGIN_KEYCHAIN_RELATIVE = Path("Library") / "Keychains" / "login.keychain-db"

_Stamp = Tuple[int, int, int]
_Key = Tuple[str, Optional[str]]

_lock = threading.Lock()
_entries: Dict[_Key, Tuple[_Stamp, float, object]] = {}


def keychain_stamp() -> Optional[_Stamp]:
    path = Path.home() / LOGIN_KEYCHAIN_RELATIVE
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def clear() -> None:
    with _lock:
        _entries.clear()


def remembered_read(
    service: str, account: Optional[str], read: Callable[[], Optional[T]], *, fresh: bool = False
) -> Optional[T]:
    stamp = keychain_stamp()
    key: _Key = (service, account)
    if stamp is None:
        return read()
    now = time.monotonic()
    with _lock:
        entry = _entries.get(key)
    if not fresh and entry is not None and entry[0] == stamp and now - entry[1] < MAX_AGE_SECONDS:
        return entry[2]  # type: ignore[return-value]
    value = read()
    with _lock:
        if value is None:
            _entries.pop(key, None)
        else:
            _entries[key] = (stamp, now, value)
    return value
