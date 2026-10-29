from __future__ import annotations

import ctypes
import ctypes.util
import sys
from typing import Callable, Optional

IOPOL_TYPE_VFS_MATERIALIZE_DATALESS_FILES: int = 3
IOPOL_SCOPE_PROCESS: int = 0
IOPOL_MATERIALIZE_DATALESS_FILES_ON: int = 2

_IS_DARWIN: bool = sys.platform == "darwin"


def _load_libc() -> Optional[ctypes.CDLL]:
    if not _IS_DARWIN:
        return None
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    libc.setiopolicy_np.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    libc.setiopolicy_np.restype = ctypes.c_int
    libc.getiopolicy_np.argtypes = [ctypes.c_int, ctypes.c_int]
    libc.getiopolicy_np.restype = ctypes.c_int
    return libc


_LIBC: Optional[ctypes.CDLL] = _load_libc()


def materialize_dataless_on() -> None:
    if _LIBC is not None:
        _LIBC.setiopolicy_np(
            IOPOL_TYPE_VFS_MATERIALIZE_DATALESS_FILES, IOPOL_SCOPE_PROCESS, IOPOL_MATERIALIZE_DATALESS_FILES_ON
        )


def spawn_preexec() -> Optional[Callable[[], None]]:
    return materialize_dataless_on if _LIBC is not None else None


def current_policy() -> Optional[int]:
    if _LIBC is None:
        return None
    value = _LIBC.getiopolicy_np(IOPOL_TYPE_VFS_MATERIALIZE_DATALESS_FILES, IOPOL_SCOPE_PROCESS)
    return None if value < 0 else value
