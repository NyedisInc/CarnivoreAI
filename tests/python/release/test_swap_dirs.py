
from __future__ import annotations

import ctypes
import errno
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "scripts" / "deploy" / "swap_dirs.py"


def _load():
    spec = importlib.util.spec_from_file_location("swap_dirs", HELPER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _pair(tmp_path: Path) -> tuple[Path, Path]:
    live = tmp_path / "app" / "Contents"
    staged = tmp_path / "stage" / "Contents"
    live.mkdir(parents=True)
    staged.mkdir(parents=True)
    (live / "who").write_text("old")
    (staged / "who").write_text("new")
    return live, staged


def _state(live: Path, staged: Path) -> tuple[str, str]:
    return (live / "who").read_text(), (staged / "who").read_text()


def test_contents_are_exchanged(tmp_path: Path) -> None:
    mod = _load()
    live, staged = _pair(tmp_path)
    mod.swap_dirs(live, staged)
    assert _state(live, staged) == ("new", "old")


def test_cli_swaps_and_exits_zero(tmp_path: Path) -> None:
    live, staged = _pair(tmp_path)
    res = subprocess.run([sys.executable, "-I", str(HELPER), str(live), str(staged)],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert _state(live, staged) == ("new", "old")


def test_check_mode_moves_nothing(tmp_path: Path) -> None:
    live, staged = _pair(tmp_path)
    res = subprocess.run([sys.executable, "-I", str(HELPER), "--check", str(live), str(staged)],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert _state(live, staged) == ("old", "new")


def test_missing_source_raises_and_moves_nothing(tmp_path: Path) -> None:
    mod = _load()
    live, _staged = _pair(tmp_path)
    with pytest.raises(mod.SwapPathError, match="does not exist"):
        mod.swap_dirs(live, tmp_path / "nope" / "Contents")
    assert (live / "who").read_text() == "old"


def test_missing_source_cli_exits_nonzero_with_message(tmp_path: Path) -> None:
    live, _staged = _pair(tmp_path)
    res = subprocess.run([sys.executable, "-I", str(HELPER), str(tmp_path / "gone"), str(live)],
                         capture_output=True, text=True)
    assert res.returncode == 1
    assert "does not exist" in res.stderr
    assert (live / "who").read_text() == "old"


def test_a_file_is_refused(tmp_path: Path) -> None:
    mod = _load()
    live, _staged = _pair(tmp_path)
    with pytest.raises(mod.SwapPathError, match="not a directory"):
        mod.swap_dirs(live, live / "who")
    assert (live / "who").read_text() == "old"


def test_cross_volume_pair_is_refused_before_the_syscall(tmp_path: Path, monkeypatch) -> None:
    mod = _load()
    live, staged = _pair(tmp_path)
    called = []
    monkeypatch.setattr(mod, "_device_of", lambda p: 1 if Path(p) == live else 2)
    monkeypatch.setattr(mod, "_renamex_np", lambda *a: called.append(a) or 0)
    with pytest.raises(mod.CrossVolumeError, match="different volumes"):
        mod.swap_dirs(live, staged)
    assert called == []
    assert _state(live, staged) == ("old", "new")


def test_real_second_volume_is_refused(tmp_path: Path) -> None:
    mod = _load()
    live, _staged = _pair(tmp_path)
    if mod._device_of(live) == mod._device_of(Path("/dev")):
        pytest.skip("/dev is on the same device here")
    with pytest.raises(mod.CrossVolumeError):
        mod.swap_dirs(live, Path("/dev"))
    assert (live / "who").read_text() == "old"


def test_failed_exchange_raises_and_moves_nothing(tmp_path: Path, monkeypatch) -> None:
    mod = _load()
    live, staged = _pair(tmp_path)

    def refuse(_a: bytes, _b: bytes, _flags: int) -> int:
        ctypes.set_errno(errno.EXDEV)
        return -1

    monkeypatch.setattr(mod, "_renamex_np", refuse)
    with pytest.raises(mod.SwapSyscallError) as info:
        mod.swap_dirs(live, staged)
    assert info.value.errno == errno.EXDEV
    assert _state(live, staged) == ("old", "new")


def test_swap_flag_is_rename_swap() -> None:
    assert _load().RENAME_SWAP == 0x2
