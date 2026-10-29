
from __future__ import annotations

import asyncio
import functools
import subprocess
from contextlib import closing
from pathlib import Path
from typing import Any, Dict

import pytest

from test_session_move import EVENTS, hooks_for, seed, subject_of, world  # noqa: F401

from src.api import pack_migrate_env as env_mod  # noqa: E402
from src.core.pack.carry.step import CodeStep  # noqa: E402
from src.core.pack.migrate import apply  # noqa: E402
from src.core.pack.migrate.plan import MigrateError  # noqa: E402
from src.core.pack.move import ops, session_move, turn  # noqa: E402
from src.core.pack.send import check as send_check  # noqa: E402

UUID = "sess-0001-aaaa"


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True, capture_output=True)


def _repo(path: Path, dirty: bool = False) -> None:
    path.mkdir(exist_ok=True)
    _git(path, "init", "-q")
    (path / "a.txt").write_text("one\n")
    _git(path, "add", "a.txt")
    _git(path, "commit", "-q", "-m", "first")
    if dirty:
        (path / "a.txt").write_text("two\n")


def _step(root: Path, caps=(), carried=None) -> CodeStep:
    async def carry() -> Dict[str, Any]:
        if carried is not None:
            carried.append(1)
        return {"machine": "studio", "sent": True, "refs": 1}

    return CodeStep(root=str(root), air_gap=False, label="studio", target_caps=caps, carry_commits=carry)


def test_a_nested_repo_is_refused_at_the_check_and_before_the_sleep(world, monkeypatch) -> None:
    a, b, link = world
    uid, root_a, root_b = seed(a, b, {})
    _repo(root_a / "PillPanic", dirty=True)
    monkeypatch.setattr(turn, "wait_for_turn_end", functools.partial(turn.wait_for_turn_end, settle=0.02, poll=0.005))
    env = env_mod.source_env()

    ready = asyncio.run(send_check.check(env, apply.guarded(link(a, b)), subject=subject_of(a, UUID), account_key="larkspur", target_label="studio", target_caps=[]))
    for mode in ("move", "copy", "fresh"):
        assert ready[mode]["ok"] is False and ready[mode]["reason"] == "content_not_carried", ready[mode]
        assert "PillPanic" in ready[mode]["detail"] and "update studio" in ready[mode]["detail"]
    assert [u["path"] for u in ready["carry"]["units"]] == ["PillPanic"] and ready["carry"]["units"][0]["state"] == "dirty"

    EVENTS.clear()
    with pytest.raises(MigrateError) as refused:
        asyncio.run(session_move.move_session(env, hooks_for(a, ["idle"], {UUID: "larkspur"}), apply.guarded(link(a, b)), subject=subject_of(a, UUID),
                                              target_install_id="iid-b", target_label="studio", wait_seconds=5, code=_step(root_a)))
    assert refused.value.code == "content_not_carried" and "PillPanic" in refused.value.detail
    assert "a:sleep" not in EVENTS and b.launched == [], EVENTS


def test_a_git_root_sends_its_commits_at_step_code_before_the_sleep_and_a_failed_carry_refuses(world, monkeypatch) -> None:
    a, b, link = world
    uid, root_a, root_b = seed(a, b, {})
    _repo(root_a)
    monkeypatch.setattr(turn, "wait_for_turn_end", functools.partial(turn.wait_for_turn_end, settle=0.02, poll=0.005))
    env, accounts = env_mod.source_env(), {UUID: "larkspur", "sess-0002-bbbb": "larkspur"}
    seen = []

    async def carry() -> Dict[str, Any]:
        EVENTS.append("a:carry_commits")
        with closing(a.conn()) as conn:
            seen.append(conn.execute("SELECT step FROM pack_session_moves WHERE role = 'source'").fetchone()[0])
        return {"machine": "studio", "sent": True, "refs": 1}

    step = CodeStep(root=str(root_a), air_gap=False, label="studio", target_caps=[], carry_commits=carry)
    EVENTS.clear()
    asyncio.run(session_move.move_session(env, hooks_for(a, ["idle"], accounts), apply.guarded(link(a, b)), subject=subject_of(a, UUID),
                                          target_install_id="iid-b", target_label="studio", wait_seconds=5, code=step))
    assert seen == ["code"] and EVENTS.index("a:carry_commits") < EVENTS.index("a:sleep") < EVENTS.index("b:launch"), EVENTS

    async def broken() -> Dict[str, Any]:
        return {"machine": "studio", "sent": False, "error": "runs_older_carnivore"}

    EVENTS.clear()
    bad = CodeStep(root=str(root_a), air_gap=False, label="studio", target_caps=[], carry_commits=broken)
    with pytest.raises(MigrateError) as refused:
        asyncio.run(session_move.move_session(env, hooks_for(a, ["idle"], accounts), apply.guarded(link(a, b)), subject=subject_of(a, "sess-0002-bbbb"),
                                              target_install_id="iid-b", target_label="studio", wait_seconds=5, code=bad))
    assert refused.value.code == "carry_failed" and "older carnivore" in refused.value.detail and "a:sleep" not in EVENTS
