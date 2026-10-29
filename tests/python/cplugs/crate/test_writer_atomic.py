
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.db import connect, db_path_for
from src.cplugs.crate import publish as publish_module
from src.cplugs.crate import record as record_module
from src.cplugs.crate.handle import ExportCancelled, JobHandle
from src.cplugs.crate.plan import build_plan
from src.cplugs.crate.writer import ExportFailed, ExportRefused, run_export
from src.cplugs.sdk import crate_format as cf
from tests.python.cplugs.crate.crate_world import env_for, make_world, session_request


@pytest.fixture
def world(tmp_path: Path) -> SimpleNamespace:
    w = make_world(tmp_path)
    w.seeded = _count(w)
    return w


def _count(w: SimpleNamespace) -> int:
    with closing(connect(db_path_for(w.state))) as conn:
        return conn.execute("SELECT count(*) FROM export_bundles").fetchone()[0]


def _bundles(w: SimpleNamespace) -> int:
    return _count(w) - w.seeded


def _left(w: SimpleNamespace) -> list:
    folder = Path(w.state) / "crates"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def test_a_fault_after_some_blobs_leaves_nothing(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    env = env_for(world)
    plan = build_plan(env, session_request())
    real = cf.CrateSink.add_blob
    calls = {"n": 0}

    def failing(self, raw):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("disk went away")
        return real(self, raw)

    monkeypatch.setattr(cf.CrateSink, "add_blob", failing)
    job = JobHandle("f")
    with pytest.raises(OSError, match="disk went away"):
        run_export(env, plan, job)
    assert _left(world) == [] and _bundles(world) == 0 and job.temp_paths == []


def test_a_cancel_leaves_nothing(world: SimpleNamespace) -> None:
    env = env_for(world)
    job = JobHandle("c")
    job.cancel()
    with pytest.raises(ExportCancelled):
        run_export(env, build_plan(env, session_request()), job)
    assert _left(world) == [] and _bundles(world) == 0


def test_a_taken_name_is_refused_and_untouched(world: SimpleNamespace) -> None:
    env = env_for(world)
    plan = build_plan(env, session_request())
    taken = Path(plan.folder) / "crate-taken-1.crate"
    taken.write_bytes(b"someone else's file")
    with pytest.raises(ExportFailed) as caught:
        run_export(env, plan, JobHandle("t"), bundle_id="crate-taken-1")
    assert caught.value.code == "name_taken" and taken.read_bytes() == b"someone else's file"
    assert _left(world) == ["crate-taken-1.crate"] and _bundles(world) == 0


def test_without_hard_links_the_name_is_reserved_then_renamed(world: SimpleNamespace,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    def no_links(src, dst):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(publish_module.os, "link", no_links)
    env = env_for(world)
    result = run_export(env, build_plan(env, session_request()), JobHandle("r"))
    assert result.path.is_file() and cf.verify(result.path, "full", expected_sha256=result.sha256).ok
    assert sorted(_left(world)) == sorted([result.file_name, f"{result.file_name}.sha256"])
    taken = Path(result.path.parent) / "crate-x-1.crate"
    taken.write_bytes(b"theirs")
    with pytest.raises(publish_module.NameTaken):
        publish_module.publish(result.path, taken)
    assert taken.read_bytes() == b"theirs"


def test_a_failed_record_removes_the_published_files(world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_a, **_k):
        raise OSError("database is locked")

    monkeypatch.setattr(record_module, "record_own", broken)
    env = env_for(world)
    with pytest.raises(OSError, match="locked"):
        run_export(env, build_plan(env, session_request()), JobHandle("x"))
    assert _left(world) == [] and _bundles(world) == 0


def test_a_changed_plan_and_a_blocked_plan_refuse(world: SimpleNamespace) -> None:
    env = env_for(world)
    plan = build_plan(env, session_request())
    stale = build_plan(env, session_request())
    stale.fingerprint = "0" * 64
    with pytest.raises(ExportRefused) as caught:
        run_export(env, stale, JobHandle("s"))
    assert caught.value.code == "plan_changed" and caught.value.detail.fingerprint == plan.fingerprint
    blocked = build_plan(env_for(world, folder="relative"), session_request())
    with pytest.raises(ExportRefused) as caught:
        run_export(env_for(world, folder="relative"), blocked, JobHandle("b"))
    assert caught.value.code == "blocked" and _left(world) == [] and _bundles(world) == 0
