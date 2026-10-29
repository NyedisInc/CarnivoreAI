
from __future__ import annotations

import asyncio
import time
from contextlib import closing
from datetime import datetime, timedelta

import pytest

from src.api import asleep_themes
from src.api.session_listing_collections import build_asleep, build_list, build_records
from src.core.automations import pause
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.cplugs.huddle import schedule_port, service
from src.cplugs.huddle.roles import port as roles_port
from src.cplugs.huddle.roles import tags
from src.cplugs.huddle.roles.store import RoleStore
from src.models import Session, SessionInfo
from tests.python.cplugs.huddle.test_page_load_connections import count_connects
from tests.python.cplugs.huddle.test_task_manager_routes import app, note  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import env, iso  # noqa: F401

NOW = datetime(2026, 10, 22, 12, 0, 0)
SLEEPERS = [("u-13-old", 13), ("u-12-lead", 12), ("u-99", 99), ("u-13-new", 13)]


class Automations:

    def list_all(self):
        return []

    def latest_stopped_runs(self):
        return {}


def live(sid: str, project: int, hours_old: float) -> SessionInfo:
    session = Session(id=sid, working_dir=f"/tmp/p{project}", agent_type="claude", created_at=NOW - timedelta(hours=hours_old),
                      last_activity=NOW - timedelta(hours=hours_old))
    return SessionInfo(session=session, tmux_session=f"cloude_{sid}", label=sid, project_id=project, project_name=f"p{project}",
                       agent_type="claude", activity_status="idle")


def seed_sleepers(db) -> None:
    with closing(connect(db, create=False)) as conn, conn:
        for project in sorted({p for _key, p in SLEEPERS}):
            conn.execute("INSERT INTO projects (id, root, raw_path, display_name, source, created_at, updated_at) "
                         "VALUES (?, ?, ?, ?, 'test', '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z')",
                         (project, f"/tmp/p{project}", f"/tmp/p{project}", f"p{project}"))
        for i, (key, project) in enumerate(SLEEPERS):
            conn.execute("INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, origin, lifecycle, lifecycle_source, "
                         "created_at, updated_at, project_id, working_dir) VALUES (?, 'cloude', ?, ?, 'created', 'stopped', 'slept_by_user', "
                         "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', ?, ?)", (key, f"cloude_{key}", i + 1, project, f"/tmp/p{project}"))


@pytest.fixture
def world(env, monkeypatch, tmp_path):
    from src.config import settings

    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: state, raising=True)
    assert ensure_db_migrated(state, 4, "0.0.0").status == "ok"
    seed_sleepers(db_path_for(state))
    monkeypatch.setattr(service, "project_names", lambda ctx: {"12": "p12", "13": "p13", "99": "p99"})
    monkeypatch.setattr(pause, "is_paused", lambda *a, **k: False)
    env.app.state.automation_store = Automations()
    rows = [live("ses_old", 12, 5), live("ses_new", 12, 1), live("ses_other", 99, 3)]
    builds = []

    async def infos():
        builds.append(1)
        return list(rows)

    env.app.state.session_manager.list_session_infos = infos
    env.builds = builds
    note(env.app, "ses_old", "12", 100.0)
    schedule_port.register(env.ctx)
    roles_port.register(env.ctx)
    yield env
    schedule_port.unregister()
    roles_port.unregister()


def scheduled(env, list_key: str, name: str, seconds: float, tag: str = "") -> None:
    item = env.store.add(list_key, name, actor="joe", title=name, fire_at=iso(seconds))
    if tag:
        tags.set_tag(env.store, item["id"], tag)


def seed_schedules(env) -> None:
    store = RoleStore(env.store)
    store.set_lead("12", "u-12-lead", "pinned")
    store.set_lead("99", "ses_other", "pinned")
    scheduled(env, "12", "asleep tag", 900, "u-12-lead")
    scheduled(env, "12", "live tag", 800, "ses_other")
    for i in range(3):
        scheduled(env, "12", f"gone tag {i}", 700 + i, f"gone-{i}")
    scheduled(env, "12", "cross project asleep tag", 600, "u-99")
    scheduled(env, "12", "untagged live", 500)
    scheduled(env, "13", "untagged asleep project", 400)
    scheduled(env, "13", "gone tag no lead", 650, "gone-13")
    scheduled(env, "99", "gone tag live lead", 300, "gone-99")


def one_pass(env) -> dict:
    async def run() -> dict:
        context: dict = {}
        out = {}
        for name, build in (("list", build_list), ("records", build_records), ("asleep", build_asleep)):
            result = await build(env.app.state, context)
            assert result.ok, (name, result.detail)
            out[name] = result.rows
        return out

    return asyncio.run(run())


def by_fire(env) -> dict:
    items = env.store.scheduled_items()
    return {i["start_trigger"]["fire_at"]: i["title"] for i in items}


def fields(env, rows: dict) -> dict:
    names = by_fire(env)
    marks = lambda row: [(m["name"], names.get(m["next_fire_at"])) for m in row.get("automations_next") or []]  # noqa: E731
    out = {"list": {r["session"]["id"]: (r["automations_state"], r["automations_total"], marks(r), r["task_lead"], r["do_not_disturb"])
                    for r in rows["list"]}}
    for name in ("records", "asleep"):
        out[name] = {r["session_uuid"]: (names.get(r["next_wake_at"]), r["automations_state"], r["automations_total"], marks(r))
                     for r in rows[name] if r.get("asleep")}
    return out


EXPECTED_LIST = {
    "ses_old": ("ok", 1, [("untagged live", "untagged live")], False, False),
    "ses_new": ("none", 0, [], False, False),
    "ses_other": ("ok", 2, [("gone tag live lead", "gone tag live lead"), ("live tag", "live tag")], True, False),
}
EXPECTED_ASLEEP = {
    "u-13-new": ("untagged asleep project", "ok", 2, [("untagged asleep project", "untagged asleep project"), ("gone tag no lead", "gone tag no lead")]),
    "u-99": ("cross project asleep tag", "ok", 1, [("cross project asleep tag", "cross project asleep tag")]),
    "u-12-lead": ("gone tag 0", "ok", 4, [("gone tag 0", "gone tag 0"), ("gone tag 1", "gone tag 1"), ("gone tag 2", "gone tag 2"),
                                           ("asleep tag", "asleep tag")]),
    "u-13-old": (None, "none", 0, []),
}


def test_a_pass_builds_the_listing_once_and_the_asleep_list_once_with_the_same_answers(world, monkeypatch):
    seed_schedules(world)
    one_pass(world)
    world.builds.clear()
    asleep_builds = []
    real_themes = asleep_themes.read_dotfile_themes
    monkeypatch.setattr(asleep_themes, "read_dotfile_themes", lambda rows: asleep_builds.append(1) or real_themes(rows))
    opened = count_connects(monkeypatch)
    started = time.perf_counter()
    got = fields(world, one_pass(world))
    took = time.perf_counter() - started
    print(f"\nlisting builds {len(world.builds)}, asleep builds {len(asleep_builds)}, sqlite connects {len(opened)}, {took * 1000:.0f} ms")
    assert got["list"] == EXPECTED_LIST
    assert got["asleep"] == EXPECTED_ASLEEP and got["records"] == EXPECTED_ASLEEP
    assert len(world.builds) == 1, f"the live listing was built {len(world.builds)} times in one pass"
    assert len(asleep_builds) == 1, f"the asleep list was built {len(asleep_builds)} times in one pass"


def test_a_write_wakes_the_listing_only_when_it_moved_what_a_row_shows(world, monkeypatch):
    woken = []
    monkeypatch.setattr(schedule_port, "listing_wake", lambda state: lambda: woken.append(state))
    port = schedule_port.SchedulePort(world.ctx)
    port._app_state = world.app.state
    scheduled(world, "12", "sweep", 900)
    item = world.store.scheduled_items()[0]["id"]
    port.wrote()
    port.wrote()
    world.store.add("12", "an unscheduled task", actor="joe")
    port.wrote()
    assert len(woken) == 1
    tags.set_tag(world.store, item, "ses_other")
    port.wrote()
    assert len(woken) == 2
