
from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.cplugs.crate import constants as K
from src.cplugs.crate import copying as copying_module
from src.cplugs.crate import record as record_module
from src.cplugs.crate.handle import JobHandle
from src.cplugs.crate.plan import build_plan
from src.cplugs.crate.writer import run_export
from tests.python.cplugs.crate.crate_world import env_for, make_world, session_request


@pytest.fixture
def world(tmp_path: Path) -> SimpleNamespace:
    w = make_world(tmp_path)
    w.second = tmp_path / "second"
    w.second.mkdir()
    return w


def _export(w: SimpleNamespace) -> object:
    env = env_for(w, secondFolder=str(w.second))
    return run_export(env, build_plan(env, session_request()), JobHandle("s"))


def test_a_cancel_during_the_copy_ends_done_with_a_warning(world: SimpleNamespace,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    real = copying_module._stream_copy

    def cancelled_midway(src, temp, job):
        job.cancel()
        return real(src, temp, job)

    monkeypatch.setattr(copying_module, "_stream_copy", cancelled_midway)
    result = _export(world)
    assert result.recorded and result.path.is_file() and result.second is None
    assert any(w.startswith(f"{K.W_SECOND_COPY}:") and "cancelled" in w for w in result.warnings)
    assert sorted(p.name for p in world.second.iterdir()) == []


def test_a_copy_that_cannot_be_recorded_is_removed(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    def locked(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(record_module, "add_location", locked)
    result = _export(world)
    assert result.recorded and result.path.is_file() and result.second is None
    assert any("could not be recorded (OperationalError)" in w for w in result.warnings)
    assert sorted(p.name for p in world.second.iterdir()) == []


def test_a_good_second_copy_is_kept(world: SimpleNamespace) -> None:
    result = _export(world)
    assert result.second is not None and result.second.is_file()
    assert not any(w.startswith(K.W_SECOND_COPY) for w in result.warnings)
