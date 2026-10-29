
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.core.mcp import tools
from src.core.mcp.caller import AgentCaller
from src.cplugs.crate import mcp, service
from src.cplugs.host import runtime, state as owner_state
from src.cplugs.sdk import ToolError
from src.cplugs.sdk import crate_format as cf
from tests.python.cplugs.crate.api_world import ApiWorld, export, stop_runner, wait_job
from tests.python.cplugs.crate.crate_world import UUID_A

PANE = AgentCaller("ses_1", "cloude_a", "ses_1")
SESSION = {"scope": "session", "target": UUID_A, "variant": "own"}


@pytest.fixture(autouse=True)
def free_slot():
    stop_runner()
    yield
    stop_runner()


def _manager(api: ApiWorld) -> Any:
    async def infos() -> list:
        return []

    return SimpleNamespace(app=api.app, gate_waited=True, list_session_infos=infos)


def _call(api: ApiWorld, name: str, args: dict) -> tuple:
    result = asyncio.run(tools.call_tool(_manager(api), PANE, name, args))
    text = result["content"][0]["text"]
    return (False, text) if result.get("isError") else (True, json.loads(text))


def test_listed_only_while_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = ApiWorld(tmp_path, monkeypatch)
    names = {d["name"] for d in tools.tool_definitions()}
    assert set(mcp.TOOLS) <= names
    d = runtime.find("crate")
    owner_state.update(api.host.state_dir, d.manifest, None,
                       lambda st: owner_state.CplugState(st.id, enabled=False, grants=st.grants))
    assert not set(mcp.TOOLS) & {d["name"] for d in tools.tool_definitions()}
    ok, text = _call(api, "crate_status", {})
    assert not ok and "off" in text


def test_crate_export_waits_in_the_inbox_with_a_sentence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = mcp.TOOLS["crate_export"]
    assert spec.gate == "inbox" and tuple(spec.dedupe_by) == ("scope", "target", "variant") and spec.prepare
    assert {s.gate for n, s in mcp.TOOLS.items() if n not in ("crate_export", "crate_import", "crate_remove", "crate_import_undo")} <= {"read", "agent"}
    assert mcp.TOOLS["crate_import"].gate == "inbox" and mcp.TOOLS["crate_import"].prepare
    assert mcp.TOOLS["crate_remove"].gate == "inbox" and mcp.TOOLS["crate_remove"].prepare
    assert mcp.TOOLS["crate_import_undo"].gate == "inbox" and mcp.TOOLS["crate_import_undo"].prepare
    api = ApiWorld(tmp_path, monkeypatch)
    ok, plan = _call(api, "crate_export_preview", SESSION)
    assert ok and plan["ok"]
    shown, sentence = asyncio.run(spec.prepare(api.ctx, PANE, {**SESSION, "fingerprint": plan["fingerprint"]}))
    assert shown["fingerprint"] == plan["fingerprint"] and shown["target"] == UUID_A
    assert sentence.startswith("export session") and "own crate" in sentence and f"{plan['files']} files" in sentence
    with pytest.raises(ToolError, match="plan_changed") as stale:
        asyncio.run(spec.prepare(api.ctx, PANE, {**SESSION, "fingerprint": "0" * 64}))
    assert "same label and options" in str(stale.value)
    with pytest.raises(ToolError, match="fingerprint is required"):
        asyncio.run(spec.prepare(api.ctx, PANE, dict(SESSION)))
    with pytest.raises(ToolError, match="blocked"):
        asyncio.run(spec.prepare(api.ctx, PANE, {**SESSION, "encrypt": True, "recipients": [],
                                                 "fingerprint": plan["fingerprint"]}))


def test_identity_is_refused_and_age_above_quick_needs_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    identity, recipient = cf.generate()
    api = ApiWorld(tmp_path, monkeypatch)
    with api.client() as client:
        done = export(api, client, {**SESSION, "encrypt": True, "recipients": [recipient]})
    bundle_id = done.result["bundle_id"]
    for name, args in (("crate_check", {"bundle_id": bundle_id, "identity": identity}),
                       ("crate_bundles_list", {"bundle_id": bundle_id, "identity": identity}),
                       ("crate_export_preview", {**SESSION, "identity": identity})):
        ok, text = _call(api, name, args)
        assert not ok and "identity is refused" in text and identity not in text, name
    ok, text = _call(api, "crate_check", {"bundle_id": bundle_id, "level": "full"})
    assert not ok and text.startswith("needs_identity")
    ok, text = _call(api, "crate_unpack", {"bundle_id": bundle_id, "conversation_id": "aaaaaaaa-x"})
    assert not ok and text.startswith("needs_identity")
    ok, started = _call(api, "crate_check", {"bundle_id": bundle_id, "level": "quick"})
    assert ok and started["job_id"]
    assert wait_job(api, started["job_id"]).state == "done"


def test_answers_are_scrubbed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = ApiWorld(tmp_path, monkeypatch)
    token = "ghp_" + "Ab3dE5gH7jK9mN1pQ3sT5vW7yZ9bC1dE3fG5"

    async def leaky(ctx: Any) -> dict:
        return {"note": f"the folder is named {token}"}

    monkeypatch.setattr(service, "summary", leaky)
    ok, answer = _call(api, "crate_status", {})
    assert ok and token not in json.dumps(answer)


def test_every_owned_route_maps_to_a_tool() -> None:
    d = runtime.find("crate")
    owned = set(d.manifest.owns.routes)
    served = {r.path.removeprefix("/cplugs/crate") for r in d.router.routes}
    assert owned == served == set(mcp.ROUTE_TOOLS) | mcp.NO_TOOL_ROUTES
    assert set(mcp.ROUTE_TOOLS.values()) <= set(mcp.TOOLS)
    assert set(d.manifest.surfaces.mcp_tools) == set(mcp.TOOLS)


def test_bundles_list_keeps_one_projects_crates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = ApiWorld(tmp_path, monkeypatch)
    ok, answer = _call(api, "crate_bundles_list", {"project": api.world.p1})
    assert ok and {b["bundle_id"] for b in answer["bundles"]} == {"crate-a", "crate-p"}
    ok, answer = _call(api, "crate_bundles_list", {"project": api.world.p2})
    assert ok and [b["bundle_id"] for b in answer["bundles"]] == ["crate-d"]
    for bad in (0, True, "18"):
        ok, text = _call(api, "crate_bundles_list", {"project": bad})
        assert not ok and "project must be a project id" in text, bad
    ok, text = _call(api, "crate_bundles_list", {"project": 999999})
    assert not ok and text.startswith("project_not_found")


def test_a_plan_changed_job_failure_says_to_preview_with_the_same_label_and_options() -> None:
    from src.cplugs.crate import service, writer
    failure = service.job_failure(writer.ExportRefused("plan_changed", object()))
    assert failure.code == "plan_changed" and "same label and options" in failure.detail


def test_crate_remove_says_what_the_card_approves_and_moves_to_the_trash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.cplugs.crate import folders, removal

    trash = tmp_path / "trash"
    trash.mkdir()
    monkeypatch.setattr(removal, "home_trash", lambda: trash)
    api = ApiWorld(tmp_path, monkeypatch)
    name = "crate-20261019T000000Z-session-fromanothermac.crate"
    (folders.resolve(api.env, "primary") / name).write_bytes(b"x")
    spec = mcp.TOOLS["crate_remove"]
    shown, sentence = asyncio.run(spec.prepare(api.ctx, PANE, {"folder": "primary", "name": name, "also_second": True}))
    assert "Trash" in sentence and name in sentence and "second folder" in sentence and shown["also_second"] is True
    with pytest.raises(ToolError):
        asyncio.run(spec.prepare(api.ctx, PANE, {"folder": "primary"}))
    with pytest.raises(ToolError):
        asyncio.run(spec.prepare(api.ctx, PANE, {"folder": "primary", "name": name, "identity": "x"}))
    result = asyncio.run(spec.handler(api.ctx, PANE, shown))
    assert (trash / name).read_bytes() == b"x" and result
