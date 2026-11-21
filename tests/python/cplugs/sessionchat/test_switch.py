
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Tuple

from src.core.db import db_path_for
from src.core.pipeline import contract as C
from src.core.pipeline import deliver, plugin_db, switch
from src.core.pipeline.engine import Engine
from src.core.pipeline.plugin_db import PluginUnavailable
from src.core.pipeline.rebuild import PluginSwitchedOff, rebuild_plugin
from src.core.timeline.plugin import TIMELINE
from src.plugins.host import gate, runtime, state as owner_state
from tests.pipeline import corpus as K
from tests.s7_helpers import migrated_connection
from tests.pipeline.test_engine import Counting, Fake, drain

import pytest

FEATURE_ID = "sessionchat"


def _transcript(folder: Path, name: str) -> deliver.FileTarget:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(K.jl(*[K.user(i, K.MAIN, 1) for i in range(3)]))
    return deliver.FileTarget(str(path), name[:-6], C.FAMILY_CLAUDE, C.FILE_CONVERSATION)


def _engine(tmp_path: Path) -> Tuple[Engine, Counting, Fake]:
    counting, fake = Counting(), Fake()
    engine = Engine(tmp_path / "state", plugins=[TIMELINE, counting.plugin], clock=fake.mono, wall=fake.wall)
    return engine, counting, fake


def _timeline_db(engine: Engine) -> Path:
    return Path(plugin_db.db_path(engine.state_dir, TIMELINE))


def _switch(engine: Engine, on: bool) -> None:
    manifest = runtime.find(FEATURE_ID).manifest
    owner_state.update(engine.state_dir, manifest, None, lambda s: replace(s, enabled=on))


def test_the_default_is_off_and_no_timeline_db_is_created(tmp_path: Path) -> None:
    engine, counting, _ = _engine(tmp_path)
    target = _transcript(tmp_path / "c", "one.jsonl")
    assert gate.is_on(FEATURE_ID, engine.state_dir) is False
    engine.mark_dirty(target)
    drain(engine)
    assert counting.counts(engine.state_dir)[target.path] == 3
    assert not _timeline_db(engine).exists()
    assert [p.id for p in engine.active_plugins()] == [counting.plugin.id]
    assert TIMELINE.id not in engine.status()["plugins"]


def test_switched_on_it_runs_without_a_restart_and_switched_off_it_stops(tmp_path: Path) -> None:
    engine, _, fake = _engine(tmp_path)
    first, second = _transcript(tmp_path / "c", "a.jsonl"), _transcript(tmp_path / "c", "b.jsonl")
    engine.mark_dirty(first)
    drain(engine)
    assert not _timeline_db(engine).exists()
    _switch(engine, True)
    fake.advance(60)
    engine.mark_dirty(first)
    drain(engine)
    assert _timeline_db(engine).exists()
    assert TIMELINE.id in engine.status()["plugins"]
    conn = plugin_db.pooled_db(engine.state_dir, TIMELINE)
    assert plugin_db.get_cursor(conn, first.path).offset == Path(first.path).stat().st_size
    _switch(engine, False)
    fake.advance(60)
    engine.mark_dirty(second)
    drain(engine)
    assert plugin_db.get_cursor(conn, second.path) is None


def test_a_rebuild_of_an_off_plugin_is_refused(tmp_path: Path) -> None:
    engine, _, _ = _engine(tmp_path)
    assert switch.is_on(TIMELINE, engine.state_dir) is False
    seen = [p.id for p in engine.scanner.current_plugins()]
    assert TIMELINE.id not in seen
    with pytest.raises(PluginSwitchedOff):
        rebuild_plugin(engine, TIMELINE.id)
    assert not _timeline_db(engine).exists()


def test_the_scan_marks_nothing_for_an_off_plugin_and_everything_once_it_is_on(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    target = _transcript(tmp_path / "c", "scan.jsonl")
    migrated_connection(state).close()
    size = Path(target.path).stat().st_size
    with closing(sqlite3.connect(db_path_for(state))) as conn:
        conn.execute("INSERT INTO transcript_files (path, family, root, source_path, conversation_id, kind, size, mtime_ns, "
                     "complete_bytes, status, first_seen, last_seen, changed_at, gone_at) "
                     "VALUES (?, 'claude', '/r', ?, ?, 'conversation', ?, 1, ?, 'present', 't', 't', 't', NULL)",
                     (target.path, target.path, target.conversation_id, size, size))
        conn.commit()
    engine = Engine(state, db_path=db_path_for(state), plugins=[TIMELINE], refresh_fn=lambda: SimpleNamespace(changed=[]))
    assert engine.scanner.run_once()["marked"] == 0
    assert not _timeline_db(engine).exists()
    _switch(engine, True)
    assert engine.scanner.run_once()["marked"] == 1
    assert engine.dirty.size() == 1


def test_the_registered_plugin_names_the_switch_and_the_feature_ships_off() -> None:
    assert TIMELINE.switch_id == FEATURE_ID
    manifest = runtime.find(FEATURE_ID).manifest
    assert manifest.tier == "builtin" and manifest.default_enabled is False
    assert owner_state.default_state(manifest).enabled is False


def test_a_plugin_without_a_switch_is_always_on(tmp_path: Path) -> None:
    plain = Counting().plugin
    assert plain.switch_id is None and switch.is_on(plain, tmp_path) is True
    assert switch.is_on(replace(plain, switch_id="nosuchfeature"), tmp_path) is False


def _raising_gate(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    def boom(*_a: object, **_k: object) -> bool:
        raise error

    monkeypatch.setattr(gate, "is_on", boom)


def test_a_gate_that_raises_reads_off_and_the_always_on_plugin_still_gets_the_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    switch._read_failure_logged.clear()
    _raising_gate(monkeypatch, runtime.RegistryError("ship list broken"))
    engine, counting, _ = _engine(tmp_path)
    target = _transcript(tmp_path / "c", "boom.jsonl")
    assert switch.is_on(TIMELINE, engine.state_dir) is False
    assert switch.is_on(counting.plugin, engine.state_dir) is True
    engine.mark_dirty(target)
    drain(engine)
    assert counting.counts(engine.state_dir)[target.path] == 3
    assert not _timeline_db(engine).exists()
    assert [p.id for p in engine.scanner.current_plugins()] == [counting.plugin.id]


@pytest.mark.parametrize("error", [OSError("disk"), ValueError("bad"), KeyError("manifest")])
def test_every_error_the_gate_can_raise_reads_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    _raising_gate(monkeypatch, error)
    assert switch.is_on(TIMELINE, tmp_path) is False


def test_a_batch_whose_run_list_raises_is_not_lost_from_the_dirty_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, _, _ = _engine(tmp_path)
    engine.mark_dirty(_transcript(tmp_path / "c", "keep.jsonl"))
    entries = engine.dirty.take(1, bulk=False)
    assert entries
    monkeypatch.setattr(engine, "active_plugins", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        engine._deliver_batch(entries)
    assert engine._in_flight == {}
    assert engine.dirty.size() == 1


def test_a_same_id_non_compiled_in_plugin_does_not_resolve_as_the_switch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = runtime.find(FEATURE_ID)
    _switch_state = tmp_path
    owner_state.update(_switch_state, real.manifest, None, lambda s: replace(s, enabled=True))
    assert switch.is_on(TIMELINE, tmp_path) is True
    outsider = SimpleNamespace(id=FEATURE_ID, manifest=replace(real.manifest, tier="third_party"))
    monkeypatch.setattr(runtime, "definitions", lambda: (outsider,))
    assert switch.is_on(TIMELINE, tmp_path) is False


def test_a_corrupt_and_an_unreadable_state_file_both_read_off(tmp_path: Path) -> None:
    path = owner_state.state_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = runtime.find(FEATURE_ID).manifest
    owner_state.update(tmp_path, manifest, None, lambda s: replace(s, enabled=True))
    assert switch.is_on(TIMELINE, tmp_path) is True
    path.write_text("{ not json", encoding="utf-8")
    assert switch.is_on(TIMELINE, tmp_path) is False
    path.write_text('{"cplugs": {"sessionchat": {"enabled": true}}}', encoding="utf-8")
    path.chmod(0)
    try:
        assert switch.is_on(TIMELINE, tmp_path) is False
    finally:
        path.chmod(0o600)


def test_a_rebuild_of_an_off_plugin_says_it_is_off_not_that_the_old_database_was_kept(tmp_path: Path) -> None:
    engine, _, _ = _engine(tmp_path)
    with pytest.raises(PluginSwitchedOff) as raised:
        rebuild_plugin(engine, TIMELINE.id)
    assert "turn it on in settings, features" in str(raised.value) and "kept" not in str(raised.value)
    assert not isinstance(raised.value, PluginUnavailable)


def test_the_route_maps_the_switched_off_refusal_to_409_and_the_mcp_tool_refuses_before_approval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from fastapi import HTTPException

    from src.api import pipeline_plugin_routes
    from src.config import settings
    from src.core.mcp import pipeline_tools
    from src.core.mcp.common import ToolError
    from src.core.pipeline import runtime as pipeline_runtime

    def refuse(plugin_id: str) -> None:
        raise PluginSwitchedOff(f"{plugin_id} is switched off; turn it on in settings, features, then rebuild")

    monkeypatch.setattr(pipeline_runtime, "rebuild_plugin", refuse)
    with pytest.raises(HTTPException) as http:
        asyncio.run(pipeline_plugin_routes.rebuild_plugin(TIMELINE.id))
    assert http.value.status_code == 409 and "kept" not in http.value.detail

    monkeypatch.setattr(type(settings), "get_state_dir", lambda _self: tmp_path)

    async def never_parked(*_a: object, **_k: object) -> dict:
        raise AssertionError("the owner must not be asked to approve a rebuild that cannot run")

    monkeypatch.setattr(pipeline_tools, "park", never_parked)
    with pytest.raises(ToolError, match="turn it on in settings, features"):
        asyncio.run(pipeline_tools.pipeline_plugin_rebuild(None, None, {"plugin_id": TIMELINE.id}))
