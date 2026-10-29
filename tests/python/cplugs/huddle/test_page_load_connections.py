
from __future__ import annotations

import asyncio
import collections
import sqlite3
import traceback

from src.core.db_migration import ensure_db_migrated
from src.cplugs.huddle import schedule_port, scheduled
from src.cplugs.huddle.roles import port as roles_port
from src.cplugs.huddle.roles import tags
from tests.python.cplugs.huddle.test_task_manager_routes import app, client, note  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import env, iso  # noqa: F401


def count_connects(monkeypatch) -> list:
    opened: list = []
    real = sqlite3.connect

    def counting(*args, **kwargs):
        frames = [f for f in traceback.extract_stack()[:-1] if "/src/" in f.filename][-3:]
        if not any(f.filename.endswith("thread_connections.py") for f in frames):
            opened.append(" < ".join(f"{f.filename.rsplit('/', 1)[-1]}:{f.name}" for f in reversed(frames)))
        return real(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", counting)
    return opened


def schedule(env, count: int, first: int = 0) -> None:
    for i in range(first, first + count):
        item = env.store.add("12", f"task {i}", actor="joe", title=f"task {i}", fire_at=iso(600 + i))
        tags.set_tag(env.store, item["id"], f"gone-{i}")


def one_pass(env) -> tuple:
    infos = asyncio.run(env.app.state.session_manager.list_session_infos())
    entries = asyncio.run(schedule_port.SchedulePort(env.ctx).by_session(infos))
    roles = asyncio.run(roles_port.RolesPort(env.ctx).read(env.app.state, infos))
    return entries, roles


def test_a_pass_opens_the_same_few_connections_for_3_or_30_scheduled_tasks(env, monkeypatch, tmp_path):
    ensure_db_migrated(tmp_path)
    note(env.app, "ses_old", "12", 100.0)
    schedule(env, 3)
    one_pass(env)
    opened = count_connects(monkeypatch)
    few, few_roles = one_pass(env)
    small = len(opened)

    monkeypatch.undo()
    schedule(env, 27, first=3)
    one_pass(env)
    opened = count_connects(monkeypatch)
    many, many_roles = one_pass(env)
    large = len(opened)

    assert large == small, f"connections grew with the tasks: {small} for 3, {large} for 30 ({collections.Counter(opened).most_common()})"
    assert large <= 6, f"one pass opened {large} connections: {opened}"
    (target,) = list(few)
    assert list(many) == [target] and [e["name"] for e in many[target]] == [f"task {i}" for i in range(30)]
    assert [e["name"] for e in few[target]] == ["task 0", "task 1", "task 2"]
    assert few_roles == many_roles


def test_the_shared_seat_read_answers_what_the_per_item_read_did(env):
    note(env.app, "ses_old", "12", 100.0)
    schedule(env, 2)
    leads = scheduled.lead_keys(env.ctx)
    for tag in ("gone-0", "gone-1", ""):
        assert asyncio.run(scheduled.tagged_pings(env.ctx, "12", tag, leads)) == asyncio.run(scheduled.tagged_pings(env.ctx, "12", tag))
