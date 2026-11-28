
from __future__ import annotations

import asyncio
import sqlite3

import pytest

from src.core.mcp.session_delete_tools import CREATOR_REASON
from src.core.mcp import pending, session_creators, write_tools
from tests.python.mcp.test_mcp_session_delete import ASLEEP_UUID, PANE, _call, world  # noqa: F401

OTHER = PANE.__class__("ses_c", "cloude_c", "ses_c")


@pytest.fixture()
def creators(world, monkeypatch, tmp_path):  # noqa: F811
    path = tmp_path / "c.db"
    with sqlite3.connect(path) as conn:
        session_creators.apply_v106(conn)
    monkeypatch.setattr(session_creators, "_connect", lambda: sqlite3.connect(path))
    view, calls = world
    view.infos.append(_clone(view.infos[0], "cloude_c"))
    for info in view.infos:
        info.session_uuid = f"uuid-{info.session.id.removeprefix('ses_')}"
    return view, calls


def _clone(info, name):
    from types import SimpleNamespace
    return SimpleNamespace(**{**vars(info), "tmux_session": name, "session": SimpleNamespace(id="ses_c", tmux_created_epoch=7)})


def _record(view, created: str, caller) -> None:
    asyncio.run(session_creators.record(view, created, caller))


def _history() -> list:
    return [i for i in pending.get_store()._items.values()
            if i.action == "session_delete" and i.status == pending.APPROVED and i.approval_source == CREATOR_REASON]


def test_creator_deletes_at_once_with_an_audit_line_and_survives_a_restart(creators):
    view, calls = creators
    _record(view, "ses_b", PANE)
    write_tools._created.clear()
    answer = _call(view, "session_delete", {"target": "cloude_b"})
    assert calls == [("destroy_session", "ses_b")] and "pending" not in str(answer)
    rows = _history()
    assert len(rows) == 1 and rows[0].target_tmux == "cloude_b"


def test_a_different_agent_asks(creators):
    view, calls = creators
    _record(view, "ses_b", PANE)
    assert "pending" in str(_call(view, "session_delete", {"target": "cloude_b"}, caller=OTHER))
    assert calls == []


def test_an_unknown_creator_asks(creators):
    view, calls = creators
    assert "pending" in str(_call(view, "session_delete", {"target": "cloude_b"}))
    assert calls == []


def test_work_in_flight_asks_even_for_the_creator(creators):
    view, calls = creators
    _record(view, "ses_b", PANE)
    view.infos[1].subagents_running = 2
    assert "pending" in str(_call(view, "session_delete", {"target": "cloude_b"}))
    assert calls == []


def test_the_creator_deletes_an_asleep_session_it_made(creators):
    view, calls = creators
    session_creators._store(ASLEEP_UUID, "uuid-a")
    _call(view, "session_delete", {"target": ASLEEP_UUID})
    assert ("delete_session_record", ASLEEP_UUID) in calls


def test_an_unmeasured_status_asks_even_for_the_creator(creators):
    view, calls = creators
    _record(view, "ses_b", PANE)
    view.infos[1].activity_status = "unknown"
    assert "pending" in str(_call(view, "session_delete", {"target": "cloude_b"}))
    assert calls == []
