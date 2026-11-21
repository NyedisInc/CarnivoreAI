
from __future__ import annotations

import asyncio
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.config import settings
from src.core.approvals.auto_answer import projects, rules
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.pack.jobs import slot_lookup
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import HostJob, HostState
from src.core.session_project_binding import (BINDING_AGENT_SLOT, BINDING_NONE, UNMINTABLE_JOBS, resolve_project_binding,
                                              unmintable_reason)

UID = "uid12345678"
JOB = "job_0123456789ab"


@pytest.fixture()
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state, 4, "0.0.0").status == "ok"
    root = tmp_path / "jobs"
    root.mkdir()
    monkeypatch.setenv("CARNIVORE_JOBS_ROOT", str(root))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    app = tmp_path / "app"
    app.mkdir()
    conn = connect(db_path_for(state))
    conn.execute("INSERT INTO projects (root, raw_path, display_name, source, presence, created_at, updated_at, uid) "
                 "VALUES (?, ?, 'app', 'user', 'unchecked', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', ?)", (str(app), str(app), UID))
    project_id = int(conn.execute("SELECT id FROM projects WHERE uid=?", (UID,)).fetchone()[0])
    yield SimpleNamespace(state=state, root=root, conn=conn, project_id=project_id, store=JobStore(state))
    conn.close()


def _hold(world, *, body: str = "agent", state: HostState = HostState.RUNNING, job: str = JOB) -> Path:
    slot = world.root / "folders" / "app-uid12345" / "slot1"
    (slot / "src").mkdir(parents=True, exist_ok=True)
    world.store.host_put(HostJob(job_id=job, project_uid=UID, state=state, slot_path=str(slot)))
    world.store.host_set(job, body=body)
    world.store.slot_claim(UID, "/r", lambda n: str(slot), job)
    return slot


def test_slot_binds_to_the_jobs_project_and_never_mints(world):
    slot = _hold(world)
    for folder in (slot, slot / "src"):
        binding = resolve_project_binding(world.conn, str(folder), allow_create=True)
        assert binding.rule == BINDING_AGENT_SLOT and binding.project_id == world.project_id and not binding.created_project
    assert world.conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1


def test_released_command_and_finished_slots_do_not_bind(world):
    slot = _hold(world)
    world.store.slot_free(str(slot))
    assert slot_lookup.live_agent_slot(str(slot)) is None
    world.store.slot_claim(UID, "/r", lambda n: str(slot), JOB)
    world.store.host_set(JOB, state=HostState.EXITED)
    assert slot_lookup.live_agent_slot(str(slot)) is None
    world.store.host_set(JOB, state=HostState.RUNNING, body="command")
    assert slot_lookup.live_agent_slot(str(slot)) is None
    binding = resolve_project_binding(world.conn, str(slot), allow_create=True)
    assert binding.rule == BINDING_NONE and binding.project_id is None
    assert world.conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1


def test_sibling_folder_under_the_jobs_root_is_refused(world):
    _hold(world)
    sibling = world.root / "folders" / "app-uid12345" / "slot10"
    sibling.mkdir()
    assert slot_lookup.live_agent_slot(str(sibling)) is None
    assert unmintable_reason(str(sibling)) == UNMINTABLE_JOBS
    binding = resolve_project_binding(world.conn, str(sibling), allow_create=True)
    assert binding.rule == BINDING_NONE and world.conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 1


def test_symlink_out_of_the_slot_does_not_count(world, tmp_path: Path):
    slot = _hold(world)
    outside = tmp_path / "outside"
    outside.mkdir()
    (slot / "escape").symlink_to(outside)
    assert slot_lookup.live_agent_slot(str(slot / "escape")) is None
    assert not projects.in_agent_slot_db(str(slot / "escape"))
    assert projects.in_agent_slot_db(str(slot / "src"))


def test_missing_file_or_table_answers_none_and_creates_nothing(world, tmp_path: Path):
    slot = world.root / "folders" / "x" / "slot1"
    slot.mkdir(parents=True)
    assert slot_lookup.live_agent_slot(str(slot)) is None
    assert not (world.state / "pack-jobs.db").exists()
    with closing(sqlite3.connect(world.state / "pack-jobs.db")) as conn:
        conn.execute("CREATE TABLE unrelated (x)")
    assert slot_lookup.live_agent_slot(str(slot)) is None


def test_trust_is_true_only_while_the_job_lives_and_only_for_the_plain_rule(world):
    slot = _hold(world, state=HostState.PARKED)
    assert projects.in_agent_slot_db(str(slot / "src"))
    world.store.host_set(JOB, state=HostState.STOPPED)
    assert not projects.in_agent_slot_db(str(slot / "src"))
    assert rules.Seams(lambda: None, lambda _f: None, lambda _f: False, lambda _f: False).in_agent_slot("/x") is False
    guards = [rules._external_imports_guard, rules._trust_permissions_guard, rules._bypass_accept_guard]
    for guard in guards:
        assert "in_agent_slot" not in guard.__code__.co_names


def test_plain_guard_allows_a_live_slot_and_declines_a_finished_one(world):
    slot = _hold(world)
    folder = str(slot.resolve() / "src")
    seams = rules.Seams(lambda: None, lambda _f: None, lambda _f: False, lambda _f: False, in_agent_slot=projects.in_agent_slot_db)
    dialog = SimpleNamespace()
    ctx = rules.Ctx(session_id="s", dialog=dialog, pane_pid=1, scope="projects", seams=seams, info=None) if "info" in rules.Ctx.__dataclass_fields__ \
        else None
    assert ctx is not None

    async def measured(_ctx):
        return folder, folder

    import src.core.approvals.auto_answer.rules as r
    r_measured, r_plain, r_shows = r._measured_folder, r.plain_dialog_folder, r.shows_folder
    r._measured_folder, r.plain_dialog_folder, r.shows_folder = measured, lambda _d: folder, lambda _d, _w: True
    try:
        assert asyncio.run(r._folder_trust_guard(ctx)).evidence == "agent_slot"
        world.store.host_set(JOB, state=HostState.STOPPED)
        assert asyncio.run(r._folder_trust_guard(ctx)).reason == "not_a_project"
    finally:
        r._measured_folder, r.plain_dialog_folder, r.shows_folder = r_measured, r_plain, r_shows


@pytest.mark.parametrize("guard_name", ["_external_imports_guard", "_trust_permissions_guard"])
def test_the_other_trust_rules_decline_a_live_agent_slot_even_when_the_seam_says_yes(world, guard_name):
    slot = _hold(world)
    folder = str(slot.resolve() / "src")
    seams = rules.Seams(lambda: None, lambda _f: None, lambda _f: False, lambda _f: False, in_agent_slot=lambda _f: True)

    async def info(_sid):
        return SimpleNamespace(session=SimpleNamespace(working_dir=folder), agent_family="claude", startup_gate=rules.GATE_AWAITING)

    ctx = rules.Ctx(session_id="s", dialog=SimpleNamespace(), pane_pid=1, scope="projects", info=info, seams=seams)
    verdict = asyncio.run(getattr(rules, guard_name)(ctx))
    assert (verdict.outcome, verdict.reason) == (rules.DECLINE, "not_a_project")
