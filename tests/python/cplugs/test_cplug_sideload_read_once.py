
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, List

import pytest

from src.cplugs.host import sideload

HOUR = 3600


@pytest.fixture
def opens(monkeypatch: pytest.MonkeyPatch) -> List[Path]:
    seen: List[Path] = []
    real = Path.read_text

    def counting(self: Path, *args: object, **kwargs: object) -> str:
        if self.name == sideload.FILE_NAME:
            seen.append(self)
        return real(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", counting)
    return seen


def clock(t: float) -> Callable[[], float]:
    return lambda: t


def forget_snapshots() -> None:
    sideload._snapshots.clear()


def test_unchanged_file_is_not_reopened(tmp_path: Path, opens: List[Path]) -> None:
    assert sideload.set_switch(tmp_path, True, clock(0.0), hours=12)
    opens.clear()
    for _ in range(50):
        assert sideload.is_on(tmp_path, clock(10.0))
    assert len(opens) <= 1


def test_a_cold_call_reads_the_file_once_not_three_times(tmp_path: Path, opens: List[Path]) -> None:
    sideload.set_switch(tmp_path, True, clock(0.0), hours=12)
    forget_snapshots()
    opens.clear()
    assert sideload.is_on(tmp_path, clock(1.0))
    assert len(opens) == 1


def test_own_write_is_seen_at_once(tmp_path: Path) -> None:
    sideload.set_switch(tmp_path, True, clock(0.0), hours=12)
    assert sideload.is_on(tmp_path, clock(1.0))
    sideload.set_switch(tmp_path, False)
    assert not sideload.is_on(tmp_path, clock(1.0))
    sideload.set_switch(tmp_path, True, clock(0.0), hours=1)
    assert sideload.is_on(tmp_path, clock(1.0))


def test_outside_edit_is_seen(tmp_path: Path) -> None:
    sideload.set_switch(tmp_path, True, clock(0.0), hours=12)
    assert sideload.is_on(tmp_path, clock(1.0))
    sideload.switch_path(tmp_path).write_text(json.dumps({"enabled_at": None, "items": {}}), encoding="utf-8")
    assert not sideload.is_on(tmp_path, clock(1.0))


def test_expiry_follows_the_clock_on_every_call(tmp_path: Path) -> None:
    sideload.set_switch(tmp_path, True, clock(0.0), hours=1)
    assert sideload.is_on(tmp_path, clock(HOUR - 1))
    assert not sideload.is_on(tmp_path, clock(HOUR))
    assert sideload.is_on(tmp_path, clock(HOUR - 1))


def test_missing_file_is_off_and_forgets_a_stale_snapshot(tmp_path: Path) -> None:
    assert not sideload.is_on(tmp_path, clock(0.0))
    sideload.set_switch(tmp_path, True, clock(0.0))
    assert sideload.is_on(tmp_path, clock(1.0))
    sideload.switch_path(tmp_path).unlink()
    assert not sideload.is_on(tmp_path, clock(1.0))


def test_unreadable_file_turns_the_switch_off(tmp_path: Path) -> None:
    sideload.set_switch(tmp_path, True, clock(0.0), hours=12)
    path = sideload.switch_path(tmp_path)
    assert sideload.is_on(tmp_path, clock(1.0))
    try:
        path.chmod(0o000)
        assert not sideload.is_on(tmp_path, clock(1.0))
    finally:
        path.chmod(0o600)
    assert sideload.is_on(tmp_path, clock(1.0))


def test_a_failed_read_is_not_cached_as_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sideload.set_switch(tmp_path, True, clock(0.0), hours=12)
    forget_snapshots()
    real = Path.read_text
    calls: List[int] = []

    def flaky(self: Path, *args: object, **kwargs: object) -> str:
        if self.name == sideload.FILE_NAME and not calls:
            calls.append(1)
            raise OSError(24, "Too many open files")
        return real(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", flaky)
    assert not sideload.is_on(tmp_path, clock(1.0))
    assert sideload.is_on(tmp_path, clock(1.0))
