
from __future__ import annotations

import ctypes
import errno
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterator, List, Set, Tuple

import pytest

from src.core.attention import codex_lock_holders, codex_stores, output_holders
from tests.python.m10_core_attention.codex_lock_fixtures import (
    THREAD, holding, lock_path, make_codex_home, release, spawn_holder,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("lsof") is None, reason="needs libproc and lsof",
)

LSOF_SECONDS = 10
REFUSED_PID = 999_999


class _RefusingLibproc:

    def __init__(self, real: Any) -> None:
        self._real = real

    def proc_pidinfo(self, pid: int, *args: Any) -> int:
        if pid == REFUSED_PID:
            ctypes.set_errno(errno.EPERM)
            return 0
        return self._real.proc_pidinfo(pid, *args)

    def proc_pidfdinfo(self, *args: Any) -> int:
        return self._real.proc_pidfdinfo(*args)


class _TruncatingLibproc:

    def __init__(self, full_reads: int) -> None:
        self.full_reads = full_reads
        self.list_reads = 0

    def proc_pidinfo(self, pid: int, flavor: int, arg: int, buf: Any, size: int) -> int:
        entry = ctypes.sizeof(output_holders._ProcFdInfo)
        if buf is None:
            return 2 * entry
        self.list_reads += 1
        if self.list_reads <= self.full_reads:
            for slot in buf:
                slot.proc_fd, slot.proc_fdtype = 9, 0
            return size
        rows = [(3, output_holders._PROX_FDTYPE_VNODE), (4, 0), (5, output_holders._PROX_FDTYPE_VNODE)]
        for slot, (fd, kind) in zip(buf, rows):
            slot.proc_fd, slot.proc_fdtype = fd, kind
        return len(rows) * entry


@pytest.fixture
def files(tmp_path: Path) -> Tuple[Path, Path]:
    home = make_codex_home(tmp_path)
    other = tmp_path / "unrelated.txt"
    other.write_text("x")
    return home, other


@pytest.fixture
def holder(files: Tuple[Path, Path]) -> Iterator[subprocess.Popen]:
    home, other = files
    yield from holding(lock_path(home), other)


def _lsof_names(pid: int, under: str) -> Set[str]:
    out = subprocess.run(["lsof", "-a", "-p", str(pid), "-Fn"], capture_output=True, text=True,
                         timeout=LSOF_SECONDS, check=False).stdout
    return {line[1:] for line in out.splitlines() if line.startswith("n" + under)}


def test_open_paths_match_lsof(files: Tuple[Path, Path], holder: subprocess.Popen) -> None:
    under = os.path.realpath(files[0].parent)
    ours = {path for _, path in output_holders.open_vnode_paths(holder.pid) if path.startswith(under)}
    assert ours == _lsof_names(holder.pid, under)
    assert len(ours) == 2


def test_owned_uuids_match_the_lsof_path(files: Tuple[Path, Path], holder: subprocess.Popen,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    home, _ = files
    link = home.parent / "linked-home"
    link.symlink_to(home, target_is_directory=True)
    for spelling in (str(home), str(link)):
        via_libproc = codex_lock_holders.owned_lock_uuids(spelling, {holder.pid})
        with monkeypatch.context() as patch:
            patch.setattr(output_holders, "libproc_available", lambda: False)
            via_lsof = codex_lock_holders.owned_lock_uuids(spelling, {holder.pid})
        assert via_libproc == via_lsof == {THREAD}


def test_reverse_holders_match_lsof_t(files: Tuple[Path, Path], holder: subprocess.Popen) -> None:
    lock = lock_path(files[0])
    candidates = {holder.pid, os.getpid()}
    scope = ",".join(str(pid) for pid in sorted(candidates))
    out = subprocess.run(["lsof", "-t", "-a", "-p", scope, str(lock)], capture_output=True, text=True,
                         timeout=LSOF_SECONDS, check=False).stdout
    by_lsof = {int(tok) for tok in out.split()}
    identity = output_holders.vnode_identity(str(lock))
    assert output_holders.holders_among(identity, candidates) == by_lsof == {holder.pid}


def test_hint_confirms_only_a_current_holder(files: Tuple[Path, Path], holder: subprocess.Popen) -> None:
    home, other = files
    assert codex_lock_holders.owned_lock_uuids(str(home), {holder.pid}) == {THREAD}
    assert codex_lock_holders.hinted_holder_live(str(lock_path(home))) is True
    assert codex_lock_holders.hinted_holder_live(str(other)) is False


def test_refused_pid_is_skipped_as_lsof_skips_it(files: Tuple[Path, Path], holder: subprocess.Popen,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    home, _ = files
    monkeypatch.setattr(output_holders, "_LIBPROC", _RefusingLibproc(output_holders._LIBPROC))
    assert output_holders.open_vnode_paths(REFUSED_PID) is None
    assert codex_lock_holders.owned_lock_uuids(str(home), {REFUSED_PID, holder.pid}) == {THREAD}
    identity = output_holders.vnode_identity(str(lock_path(home)))
    assert output_holders.holders_among(identity, {REFUSED_PID, holder.pid}) == {holder.pid}


def test_descriptor_cap_and_budget_make_the_pane_unmeasurable(
        files: Tuple[Path, Path], holder: subprocess.Popen, monkeypatch: pytest.MonkeyPatch) -> None:
    home, _ = files
    with pytest.raises(output_holders.ScanLimitReached):
        output_holders.open_vnode_paths(holder.pid, max_entries=1)
    with monkeypatch.context() as patch:
        patch.setattr(codex_lock_holders, "MAX_SCANNED_DESCRIPTORS", 1)
        assert codex_lock_holders.owned_lock_uuids(str(home), {holder.pid}) == set()
    with monkeypatch.context() as patch:
        patch.setattr(codex_lock_holders, "SCAN_BUDGET_SECONDS", -1.0)
        assert codex_lock_holders.owned_lock_uuids(str(home), {holder.pid}) == set()
    assert codex_lock_holders.owned_lock_uuids(str(home), {holder.pid}) == {THREAD}


def test_a_full_descriptor_buffer_is_read_again_larger(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _TruncatingLibproc(full_reads=1)
    monkeypatch.setattr(output_holders, "_LIBPROC", fake)
    assert output_holders._vnode_fds(REFUSED_PID) == [3, 5]
    assert fake.list_reads == 2
    monkeypatch.setattr(output_holders, "_LIBPROC", _TruncatingLibproc(full_reads=99))
    with pytest.raises(output_holders._Unmeasurable):
        output_holders._vnode_fds(REFUSED_PID)


def test_released_hint_falls_back_to_lsof_and_finds_another_holder(
        files: Tuple[Path, Path], holder: subprocess.Popen, monkeypatch: pytest.MonkeyPatch) -> None:
    home, _ = files
    lock = lock_path(home)
    assert codex_lock_holders.owned_lock_uuids(str(home), {holder.pid}) == {THREAD}
    other = spawn_holder(lock)
    try:
        release(holder)
        fallbacks: List[str] = []

        def scoped_lsof_holders(path: str) -> Set[int]:
            fallbacks.append(path)
            out = subprocess.run(["lsof", "-t", "-a", "-p", str(other.pid), path], capture_output=True,
                                 text=True, timeout=LSOF_SECONDS, check=False).stdout
            return {int(tok) for tok in out.split()}

        monkeypatch.setattr(codex_stores, "_lsof_holders", scoped_lsof_holders)
        assert codex_stores.writer_lock_live(str(home), THREAD) is True
        assert fallbacks == [str(lock)]
        assert output_holders.vnode_identity(str(lock)) not in codex_lock_holders._hints
    finally:
        release(other)
