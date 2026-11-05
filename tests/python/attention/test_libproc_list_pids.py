
from __future__ import annotations

import ctypes
from typing import Any, List, Optional

from src.core.machine_stats import libproc_snapshot


class _StubLib:

    def __init__(self, pids: List[int], count: Optional[int] = None) -> None:
        self._pids = pids
        self._count = len(pids) if count is None else count
        self.read_buffer_len = 0
        self.read_size = 0

    def proc_listallpids(self, buf: Any, size: int) -> int:
        if buf is None:
            return self._count
        self.read_buffer_len, self.read_size = len(buf), size
        for index, pid in enumerate(self._pids):
            buf[index] = pid
        return len(self._pids)


def test_list_pids_returns_the_listed_pids_and_allows_headroom() -> None:
    lib = _StubLib([1, 40, 7])
    assert libproc_snapshot._list_pids(lib) == [1, 40, 7]  # type: ignore[arg-type]
    assert lib.read_buffer_len == 3 + libproc_snapshot._PID_HEADROOM
    assert lib.read_size == lib.read_buffer_len * ctypes.sizeof(ctypes.c_int)


def test_list_pids_is_none_when_the_size_query_finds_nothing() -> None:
    assert libproc_snapshot._list_pids(_StubLib([], count=0)) is None  # type: ignore[arg-type]


def test_list_pids_is_empty_when_the_read_returns_nothing() -> None:
    assert libproc_snapshot._list_pids(_StubLib([], count=5)) == []  # type: ignore[arg-type]
