
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException

from src.plugins.save import routes as save_routes
from src.plugins.save.offload import constants as C
from src.plugins.save.offload import list_routes, offload_routes, push, reconcile, restore_routes, settings
from src.plugins.save.offload.ledger import Ledger
from src.plugins.save.vault.units import Scanner
from src.plugins.sdk import vault_sources
from tests.python.cplugs.save.offload.test_offload_session import ID, installed, ledger_of  # noqa: F401
from tests.python.cplugs.save.vault_helpers import World


@pytest.fixture
def named(monkeypatch: pytest.MonkeyPatch) -> List[str]:
    calls: List[str] = []
    push.bind(calls.append)
    yield calls
    push.unbind()


def test_offload_names_the_topic_exactly_once(installed: World, named: List[str]) -> None:
    offload_routes._run("S1", False)
    assert named == [C.PUSH_TOPIC]


def test_a_dry_run_names_nothing(installed: World, named: List[str]) -> None:
    offload_routes._run("S1", True)
    assert named == []


def test_restore_names_the_topic_exactly_once(installed: World, named: List[str]) -> None:
    offload_routes._run("S1", False)
    named.clear()
    restore_routes.run_restore("S1", None, False)
    assert named == [C.PUSH_TOPIC]


def test_reconcile_names_the_topic_exactly_once(installed: World, named: List[str]) -> None:
    offload_routes._run("S1", False)
    ledger = ledger_of(installed)
    for conv in ID.values():
        ledger.update(conv, state=C.STATE_RESTORING)
    named.clear()
    outcomes = reconcile.reconcile(installed.vault, ledger, offload_routes.claude_homes(installed.sources.claude_roots))
    assert set(outcomes.values()) == {"offloaded"} and named == [C.PUSH_TOPIC]


def test_a_bare_ledger_write_names_it_once_and_an_unbound_push_is_silent(installed: World, named: List[str]) -> None:
    offload_routes._run("S1", False)
    named.clear()
    ledger_of(installed).update(ID["c1"], error="x")
    assert named == [C.PUSH_TOPIC]
    push.unbind()
    ledger_of(installed).update(ID["c1"], error="y")
    assert named == [C.PUSH_TOPIC]


def _endpoint(path: str, method: str) -> Any:
    return next(r.endpoint for r in save_routes.router.routes if getattr(r, "path", "").endswith(path) and method in getattr(r, "methods", ()))


def _stored(monkeypatch: pytest.MonkeyPatch, **setting: Any) -> None:
    monkeypatch.setattr(vault_sources, "plugin_settings", lambda state_dir, plugin_id: dict(setting))


def test_the_offload_route_refuses_while_the_setting_is_off_and_restore_and_the_list_still_work(installed: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vault_sources, "project_names", lambda state: {1: "carnivore"})
    monkeypatch.setattr(list_routes.RUNTIME, "vault", lambda: installed.vault)
    monkeypatch.setattr(list_routes.RUNTIME, "sources", lambda: installed.sources)
    offload = _endpoint("/offload/sessions/{session_uuid}", "POST")
    for off in ({}, {"offloadEnabled": False}, {"offloadEnabled": "true"}):
        _stored(monkeypatch, **off)
        with pytest.raises(HTTPException) as caught:
            asyncio.run(offload("S1", None))
        assert caught.value.status_code == 409 and caught.value.detail["code"] == C.CODE_OFFLOAD_DISABLED
    assert not ledger_of(installed).path.exists()
    _stored(monkeypatch, offloadEnabled=True)
    asyncio.run(offload("S1", None))
    _stored(monkeypatch)
    page = asyncio.run(_endpoint("/offload", "GET")(None, C.PAGE_DEFAULT, None))
    assert page.enabled is False and page.totals.conversations == 3 and [(r.session_uuid, r.title, r.project, r.conversations, r.state) for r in page.rows] == [("S1", "t", "carnivore", 3, "offloaded")]
    back = asyncio.run(_endpoint("/offload/sessions/{session_uuid}/restore", "POST")("S1", None))
    assert {c.status for c in back.conversations} == {"written"}
    assert asyncio.run(_endpoint("/offload", "GET")(None, C.PAGE_DEFAULT, None)).rows == []


def test_the_setting_reads_only_a_real_true() -> None:
    assert settings.enabled_in({"offloadEnabled": True}) and not any(settings.enabled_in({"offloadEnabled": v}) for v in (False, None, "true", 1, "on"))
    assert not settings.enabled_in({})


def test_the_list_groups_by_session_and_keeps_a_stuck_row_visible(installed: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(list_routes.RUNTIME, "vault", lambda: installed.vault)
    monkeypatch.setattr(list_routes.RUNTIME, "sources", lambda: installed.sources)
    offload_routes._run("S1", False)
    ledger = ledger_of(installed)
    ledger.update(ID["c2"], state=C.STATE_FAILED, error="2 file(s) could not be put back: x")
    ledger.update(ID["c3"], group=[])
    rows, totals = list_view_rows(ledger)
    assert [(r.kind, r.state, r.conversations) for r in rows] == [("session", "failed", 2), ("conversation", "offloaded", 1)]
    assert rows[0].error.startswith("2 file(s)") and (totals.rows, totals.conversations) == (2, 3)
    only_failed, _ = list_view_rows(ledger, C.STATE_FAILED)
    assert [r.kind for r in only_failed] == ["session"]
    with pytest.raises(HTTPException) as caught:
        list_routes.list_page("bogus", None, 50)
    assert caught.value.status_code == 400


def list_view_rows(ledger: Ledger, state: str | None = None) -> Any:
    from src.plugins.save.offload import list_view  # noqa: PLC0415

    return list_view.group_rows(ledger.read().values(), {"S1": ("t", 1)}, {1: "carnivore"}, state)


def test_a_page_size_outside_one_to_the_cap_is_refused_on_every_door(installed: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.plugins.save import offload_mcp  # noqa: PLC0415
    from src.plugins.sdk import ToolError  # noqa: PLC0415

    monkeypatch.setattr(list_routes.RUNTIME, "vault", lambda: installed.vault)
    monkeypatch.setattr(list_routes.RUNTIME, "sources", lambda: installed.sources)
    monkeypatch.setattr(vault_sources, "project_names", lambda state: {})
    for bad in (0, -1, C.PAGE_MAX + 1):
        with pytest.raises(HTTPException) as caught:
            list_routes.list_page(None, None, bad)
        assert caught.value.status_code == 400
    assert list_routes.list_page(None, None, C.PAGE_MAX).rows == []
    for bad_arg in ("x", True, 0, -3, 2.5):
        with pytest.raises(ToolError):
            asyncio.run(offload_mcp.save_offload_list(None, None, {"limit": bad_arg}))  # type: ignore[arg-type]
    for bad_cursor in ([1], {"a": 1}, 3):
        with pytest.raises(ToolError):
            asyncio.run(offload_mcp.save_offload_list(None, None, {"cursor": bad_cursor}))  # type: ignore[arg-type]
    assert asyncio.run(offload_mcp.save_offload_list(None, None, {}))  # type: ignore[arg-type]
