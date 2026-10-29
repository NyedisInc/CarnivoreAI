
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.cplugs.save import mcp as save_mcp
from src.cplugs.save.routes import router
from src.cplugs.sdk import ToolError


def test_every_import_route_has_a_tool_and_every_tool_is_named_by_a_route() -> None:
    owned = {r.path.removeprefix(router.prefix) if router.prefix else r.path for r in router.routes if "/imports" in r.path}
    paths = {p[p.index("/imports"):] for p in owned}
    assert paths == set(save_mcp.ROUTE_TOOLS) and set(save_mcp.ROUTE_TOOLS.values()) == set(save_mcp.TOOLS)
    assert all(t.gate == "inbox" for n, t in save_mcp.TOOLS.items() if n in ("save_import", "save_import_remove", "save_import_decide"))
    assert set(save_mcp.TOOLS["save_import_preview"].pane_only_args) >= {"archives", "folders", "recovered_root"}


def test_an_apply_card_is_refused_for_a_fingerprint_no_preview_answered() -> None:
    with pytest.raises(ToolError, match="fingerprint is required"):
        asyncio.run(save_mcp._apply_prepare(None, None, {"fingerprint": "f" * 64, "folders": [{"path": str(Path("/tmp"))}]}))


def test_an_apply_card_replayed_after_a_restart_still_finds_its_preview(rig_state, monkeypatch) -> None:
    from src.cplugs.save import import_service as svc
    from src.cplugs.save.vault.old_sources import preview_store

    fingerprint, counts = "a" * 64, _COUNTS
    monkeypatch.setattr(svc.tf, "state_dir", lambda: str(rig_state))
    svc._PREVIEWS.clear()
    svc._PREVIEWS[fingerprint] = counts
    preview_store.save(rig_state, svc._PREVIEWS)
    assert (preview_store.path_of(rig_state).stat().st_mode & 0o777) == 0o600
    svc._PREVIEWS.clear()
    _body, sentence = asyncio.run(save_mcp._apply_prepare(None, None, {"fingerprint": fingerprint}))
    assert "file the old archive in the backup vault" in sentence
    preview_store.path_of(rig_state).write_text("{not json")
    with pytest.raises(ToolError, match="fingerprint is required"):
        asyncio.run(save_mcp._apply_prepare(None, None, {"fingerprint": fingerprint}))


@pytest.fixture
def rig_state(tmp_path: Path) -> Path:
    return tmp_path


_COUNTS = {"conversations": {"to_import": 2}, "points": {"total": 2, "kept": 0}, "files": 4, "bytes": 10, "hidden_from_search": 0, "no_project": 0,
           "extras": {"files": 2}}
