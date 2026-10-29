
from __future__ import annotations

import asyncio
from contextlib import closing
from types import SimpleNamespace
from typing import Any

import pytest

from src.api import session_purge_routes as routes
from src.core.db import connect
from src.core.mcp import session_purge_tools as tool
from src.core.mcp.common import ToolError
from src.core.inventory import target as purge_target
from tests.python.session_purge import purge_world as W

OLD_UUID, NEW_UUID, ARCH_UUID, BARE_UUID = "uuid-old-0001", "uuid-new-0002", "uuid-arch-0003", "uuid-bare-0004"
CONV_BARE = "99999999-aaaa-bbbb-cccc-000000000001"


@pytest.fixture
def world(tmp_path: Any, monkeypatch: Any) -> Any:
    w = W.build(tmp_path, monkeypatch)
    monkeypatch.setattr(routes, "_panes", lambda: (True, ()))
    with closing(connect(w.db)) as conn:
        w.old_id = W.add_session(conn, OLD_UUID, "carnivore_Trader", None, epoch=1)
        w.new_id = W.add_session(conn, NEW_UUID, "carnivore_Trader", None, epoch=2)
        w.arch_id = W.add_session(conn, ARCH_UUID, "carnivore_trust-test", None, title="trust test")
        conn.execute("UPDATE sessions SET archived_at = 'now', legacy_session_id = 'ses_abcd1234' WHERE id = ?",
                     (w.arch_id,))
        w.bare_id = W.add_session(conn, BARE_UUID, "carnivore_permprobe", CONV_BARE)
        conn.execute("UPDATE sessions SET working_dir = '/private/tmp/claude-501/scratch', project_id = NULL "
                     "WHERE id = ?", (w.bare_id,))
        conn.commit()
    return w


def resolve(w: Any, target: str) -> str:
    with closing(connect(w.db)) as conn:
        return purge_target.resolve_session_uuid(conn, target)


def test_archived_row_resolves_by_uuid_app_id_and_row_id(world: Any) -> None:
    assert resolve(world, ARCH_UUID) == ARCH_UUID
    assert resolve(world, "ses_abcd1234") == ARCH_UUID
    assert resolve(world, f"row:{world.arch_id}") == ARCH_UUID
    assert resolve(world, str(world.arch_id)) == ARCH_UUID
    assert resolve(world, "carnivore_trust-test") == ARCH_UUID


def test_shadowed_older_row_reached_by_uuid_and_row_id(world: Any) -> None:
    assert resolve(world, OLD_UUID) == OLD_UUID
    assert resolve(world, f"row:{world.old_id}") == OLD_UUID


def test_shared_tmux_name_is_ambiguous_and_names_the_candidates(world: Any) -> None:
    with pytest.raises(purge_target.TargetAmbiguous) as caught:
        resolve(world, "carnivore_Trader")
    assert caught.value.candidates == [OLD_UUID, NEW_UUID]
    assert OLD_UUID in str(caught.value) and NEW_UUID in str(caught.value)


def test_unknown_target_is_not_found(world: Any) -> None:
    with pytest.raises(purge_target.TargetNotFound):
        resolve(world, "nope")


def test_no_project_row_plans_and_traces_a_private_tmp_cwd(world: Any) -> None:
    transcript = world.home / "projects" / "-private-tmp-claude-501-scratch" / f"{CONV_BARE}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(W.SECRET_LINE)
    answer = routes.plan_and_maybe_apply(BARE_UUID, routes.SessionPurgeRequest(), False)
    assert answer["ok"], answer["blockers"]
    assert answer["confirm_text"] == "carnivore_permprobe"
    assert any(a["kind"] == "file" and a["what"] == str(transcript) and a["action"] == "delete" for a in answer["artifacts"])


def test_archived_and_shadowed_rows_keep_every_refusal(world: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(routes, "_panes", lambda: (True, (("carnivore_Trader", 1, "/w"),)))
    old = routes.plan_and_maybe_apply(OLD_UUID, routes.SessionPurgeRequest(), False)
    assert any("is live" in b for b in old["blockers"])
    new = routes.plan_and_maybe_apply(NEW_UUID, routes.SessionPurgeRequest(), False)
    assert not any("is live" in b for b in new["blockers"])


def test_tool_resolves_stored_rows_and_refuses_ambiguity(world: Any, monkeypatch: Any) -> None:
    async def no_live(_manager: Any) -> list:
        return []

    monkeypatch.setattr("src.core.mcp.common._all_infos", no_live)
    run = lambda t: asyncio.run(tool._resolve_uuid(SimpleNamespace(), {"target": t}))  # noqa: E731
    assert run(f"row:{world.arch_id}") == ARCH_UUID
    assert run(OLD_UUID) == OLD_UUID
    with pytest.raises(ToolError, match=OLD_UUID):
        run("carnivore_Trader")
    with pytest.raises(ToolError, match="no stored session"):
        run("nope")
