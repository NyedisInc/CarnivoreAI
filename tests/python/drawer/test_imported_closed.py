
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.api.session_listing_collections import running_join_row
from src.api.session_record_payload import _session_record_payload
from src.core.lineage.row import is_lineage_row
from src.core.session_sleep import closed_rows, is_closed
from tests.test_session_restart_source import _insert_session, conn  # noqa: F401

CONV = "c0ffee00-0000-4000-8000-000000000001"


def shape(kind: str, **kw) -> dict:
    base = {"lifecycle": "stopped", "lifecycle_source": "closed_by_user", "archived_at": None, "claude_session_uuid": CONV,
            "tmux_name": "carnivore_x", "tmux_created_epoch": 5, "parent_session_id": None}
    if kind == "fork":
        base["parent_session_id"] = 3
    elif kind == "lineage":
        base.update(parent_session_id=3, tmux_created_epoch=None, tmux_name=None)
    elif kind == "import":
        base.update(lifecycle_source="import", tmux_created_epoch=None, tmux_name=None)
    base.update(kw)
    return base


@pytest.mark.parametrize("kind, closed", [("anchor", True), ("fork", True), ("lineage", False), ("import", True)])
def test_is_closed_across_the_four_row_shapes(kind, closed):
    assert is_closed(shape(kind)) is closed
    assert is_lineage_row(shape(kind)) is (kind == "lineage")


def test_an_archived_import_is_not_closed():
    assert is_closed(shape("import", archived_at="2026-11-01T00:00:00")) is False


def test_records_mark_an_unarchived_import_closed_and_leave_an_archived_one_out(conn):  # noqa: F811
    _insert_session(conn, session_uuid="imp", origin="imported", tmux_name=None, tmux_created_epoch=None, agent_type=None,
                    claude_session_uuid=CONV, lifecycle="stopped", lifecycle_source="import")
    _insert_session(conn, session_uuid="arch", origin="imported", tmux_name=None, tmux_created_epoch=None, agent_type=None,
                    claude_session_uuid="c0ffee00-0000-4000-8000-000000000002", lifecycle="stopped", lifecycle_source="import",
                    archived_at="2026-11-01T00:00:00")
    rows = {r["session_uuid"]: dict(r) for r in conn.execute("SELECT * FROM sessions").fetchall()}
    assert _session_record_payload(rows["imp"]).closed is True and running_join_row(rows["imp"], set()) is True
    assert _session_record_payload(rows["arch"]).closed is False and running_join_row(rows["arch"], set()) is False
    assert [r["session_uuid"] for r in closed_rows(conn)] == ["imp"]


def test_drawer_reopen_resumes_an_import_with_no_agent_type(conn, monkeypatch):  # noqa: F811
    from src.core import session_restart
    from src.core.account_switch import restart_account
    from src.core.session_ops import restart as ops

    _insert_session(conn, session_uuid="imp", origin="imported", tmux_name=None, tmux_created_epoch=None, agent_type=None,
                    claude_session_uuid=CONV, lifecycle="stopped", lifecycle_source="import", title="Home Assistant")
    seen = {}

    async def fake_create(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(tmux_session="carnivore_home_assistant")

    async def no_account(*_a, **_k):
        return SimpleNamespace(account_id=None)

    source = session_restart.resolve_restart_source(conn, session_uuid="imp", check_transcript=False)
    monkeypatch.setattr(restart_account, "resolve", no_account)
    app_state = SimpleNamespace(session_manager=SimpleNamespace(create_session=fake_create))
    asyncio.run(ops._create_replacement(app_state, "imp", source, "Home Assistant", True))
    assert source.outcome == session_restart.RESTART_RESUMABLE
    assert seen["agent_extra_args"] == ["--resume", CONV]
    assert seen["agent_type"] is None and seen["reuse_session_id"] == source.parent_id


def test_mcp_reopen_of_an_import_goes_to_the_restart_route_not_recreate(monkeypatch):
    from src.core.mcp import session_control_tools as sct

    calls = []

    async def restart(request, session_uuid):
        calls.append(("restart", session_uuid))

    async def recreate(*_a, **_k):
        calls.append(("recreate",))

    monkeypatch.setattr("src.api.session_restart_apply_routes.restart_session", restart)
    monkeypatch.setattr("src.api.recreate_routes.recreate_session", recreate)
    call = SimpleNamespace(request=object(), session_uuid="imp", args={}, target=SimpleNamespace(row=shape("import")))
    asyncio.run(sct._reopen_closed(call, None))
    assert calls == [("restart", "imp")]
    with pytest.raises(sct.ToolError):
        sct._reopen_closed(call, None, "acct")
    with pytest.raises(sct.ToolError, match="agent_type"):
        sct._reopen_closed(call, "claude")
