
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.devwidgetlab import capabilities, mcp
from src.cplugs.devwidgetlab.drafts import create, files, service, store
from src.cplugs.devwidgetlab.errors import DraftInvalid, DraftNotFound
from src.cplugs.sdk import ToolError, signed_links
from tests.python.cplugs.devwidgetlab.test_widget_lab_routes import BASE, host_app  # noqa: F401
from tests.python.cplugs.owner import turn_on

CELL = "files/web/src/opscenter/cells/pulse-board/Cell.svelte"


@pytest.fixture(autouse=True)
def _signing(monkeypatch):
    monkeypatch.setattr(signed_links, "settings", SimpleNamespace(load_auth_config=lambda: SimpleNamespace(jwt_secret="test-secret")))


def _draft(tmp_path: Path) -> Path:
    storage = tmp_path / "s"
    create.create_new(storage, "Pulse board", "x", ["home"], ["small"], "tools")
    return storage / "drafts" / "pulse-board"


@pytest.mark.parametrize("rel", ["", "/etc/passwd", "../x", "files/../../x", "files/./x", "a//b", "a\\b", "x\x00y", "files/web/src/../../../x"])
def test_a_path_that_leaves_the_folder_is_refused_for_reads_and_writes(tmp_path: Path, rel: str) -> None:
    folder = _draft(tmp_path)
    with pytest.raises(DraftInvalid):
        files.safe_path(folder, rel)
    with pytest.raises(DraftInvalid):
        files.write_file(folder, rel, "x")
    with pytest.raises(DraftInvalid):
        files.delete_file(folder, rel)


def test_a_symlink_is_never_followed_at_any_depth(tmp_path: Path) -> None:
    folder = _draft(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    os.symlink(outside, folder / "files" / "link")
    os.symlink(outside / "secret.txt", folder / "captures" / "leak.txt")
    for rel in ("files/link/secret.txt", "captures/leak.txt", "files/link"):
        with pytest.raises(DraftInvalid):
            files.read_file(folder, rel)
    with pytest.raises(DraftInvalid):
        files.write_file(folder, "files/link/web/src/x.ts", "x")
    with pytest.raises(DraftInvalid):
        files.write_file(folder, "captures/leak.txt", "overwrite")
    assert (outside / "secret.txt").read_text() == "secret" and sorted(p.name for p in outside.iterdir()) == ["secret.txt"]
    listed = [f["path"] for f in files.list_files(folder)]
    assert "captures/leak.txt" not in listed and not any(p.startswith("files/link") for p in listed)
    os.symlink(outside, tmp_path / "linkroot")
    with pytest.raises(DraftInvalid):
        files.safe_path(tmp_path / "linkroot", "BRIEF.md")


@pytest.mark.parametrize("rel", ["draft.json", "OVERRIDES.md", "build/site/index.html", "build/build.json", "files", "files/client/js/app.js", "files/src/main.py",
                                 "notes.txt", "captures"])
def test_a_generated_or_unowned_file_cannot_be_written(tmp_path: Path, rel: str) -> None:
    folder = _draft(tmp_path)
    before = (folder / "draft.json").read_text()
    with pytest.raises(DraftInvalid):
        files.write_file(folder, rel, "{}")
    with pytest.raises(DraftInvalid):
        files.delete_file(folder, rel)
    assert (folder / "draft.json").read_text() == before


def test_files_are_read_written_and_deleted_inside_the_folder_and_the_note_follows(tmp_path: Path) -> None:
    folder = _draft(tmp_path)
    assert files.write_file(folder, CELL, "<p>new body</p>") == {"path": CELL, "bytes": 15, "created": False}
    assert files.read_file(folder, CELL)["content"] == "<p>new body</p>"
    added = "files/web/src/opscenter/cells/pulse-board/Row.svelte"
    assert files.write_file(folder, added, "<p/>")["created"] is True
    assert "adds `web/src/opscenter/cells/pulse-board/Row.svelte`" in (folder / "OVERRIDES.md").read_text()
    files.delete_file(folder, added)
    assert "Row.svelte" not in (folder / "OVERRIDES.md").read_text()
    with pytest.raises(DraftNotFound):
        files.read_file(folder, added)
    assert files.write_file(folder, "captures/a.txt", "x")["path"] == "captures/a.txt"
    with pytest.raises(DraftInvalid):
        files.write_file(folder, "widget.json", "[1]")
    with pytest.raises(DraftInvalid):
        files.write_file(folder, CELL, "x" * (files.MAX_BYTES + 1))
    (folder / "captures" / "bin.dat").write_bytes(b"\xff\xfe")
    with pytest.raises(DraftNotFound):
        files.read_file(folder, "captures/bin.dat")
    assert {"path": "BRIEF.md", "bytes": (folder / "BRIEF.md").stat().st_size} in files.list_files(folder)


def _ctx(storage: Path) -> Any:
    async def start_in_folder(working_dir: str, label: str, prompt: str) -> str:
        return "ses_00000001"

    return SimpleNamespace(storage=SimpleNamespace(path=storage), sessions=SimpleNamespace(start_in_folder=start_in_folder))


def test_every_tool_is_the_twin_of_one_route_and_reaches_the_function_the_route_calls(host_app, monkeypatch) -> None:  # noqa: F811
    app, host = host_app
    turn_on(host, "devwidgetlab")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    storage = host.state_dir / "cplugs" / "devwidgetlab"
    reached: Dict[str, list] = {}

    def spy(name: str) -> None:
        real = getattr(service, name)
        if asyncio.iscoroutinefunction(real):
            async def wrapped(*a: Any, **k: Any) -> Any:
                reached.setdefault(name, []).append(a[1:])
                return await real(*a, **k)
        else:
            def wrapped(*a: Any, **k: Any) -> Any:
                reached.setdefault(name, []).append(a[1:])
                return real(*a, **k)
        monkeypatch.setattr(service, name, wrapped)

    for name in ("list_drafts", "create_draft", "get_draft", "files_list", "file_get", "file_set", "file_delete", "build_draft", "hand_to_claude", "discard_draft"):
        spy(name)
    monkeypatch.setattr(service.preview, "require_buildable", lambda storage: store.REPO)
    monkeypatch.setattr(service.preview, "_run", lambda folder, repo: asyncio.sleep(0))

    def tool(name: str, args: dict) -> Any:
        result = asyncio.run(mcp.TOOLS[name].handler(_ctx(storage), SimpleNamespace(), args))
        return json.loads(result["content"][0]["text"])

    new = {"kind": "new", "name": "Pulse board", "what": "x"}
    with TestClient(app) as client:
        assert tool("widget_lab_draft_create", new)["slug"] == "pulse-board" and reached["create_draft"][0][0]["name"] == "Pulse board"
        assert client.post(f"{BASE}/drafts", json={**new, "name": "Other thing"}).status_code == 200 and len(reached["create_draft"]) == 2
        assert tool("widget_lab_drafts_list", {})["drafts"] and reached["list_drafts"]
        assert client.get(f"{BASE}/drafts").json()["available"] is True and len(reached["list_drafts"]) == 2
        assert tool("widget_lab_draft_get", {"slug": "pulse-board"})["widget"] == "core.pulse-board"
        assert client.get(f"{BASE}/drafts/pulse-board").json()["widget"] == "core.pulse-board" and len(reached["get_draft"]) == 2
        assert [f["path"] for f in tool("widget_lab_draft_files_list", {"slug": "pulse-board"})["files"]] == [f["path"] for f in client.get(f"{BASE}/drafts/pulse-board/files").json()["files"]]
        assert len(reached["files_list"]) == 2
        assert tool("widget_lab_draft_file_set", {"slug": "pulse-board", "path": CELL, "content": "<p>via tool</p>"})["bytes"] == 15
        assert client.get(f"{BASE}/drafts/pulse-board/file", params={"path": CELL}).json()["content"] == "<p>via tool</p>"
        assert tool("widget_lab_draft_file_get", {"slug": "pulse-board", "path": CELL})["content"] == "<p>via tool</p>"
        assert len(reached["file_get"]) == 2 and len(reached["file_set"]) == 1
        assert client.put(f"{BASE}/drafts/pulse-board/file", json={"path": CELL, "content": "<p>via route</p>"}).json()["bytes"] == 16 and len(reached["file_set"]) == 2
        assert client.delete(f"{BASE}/drafts/pulse-board/file", params={"path": "../x"}).status_code == 400
        assert tool("widget_lab_draft_file_delete", {"slug": "pulse-board", "path": CELL})["deleted"] is True
        assert client.delete(f"{BASE}/drafts/pulse-board/file", params={"path": CELL}).status_code == 404 and len(reached["file_delete"]) == 3
        assert tool("widget_lab_draft_rebuild", {"slug": "pulse-board"})["state"] == "building" and len(reached["build_draft"]) == 1
        assert tool("widget_lab_draft_spawn", {"slug": "pulse-board"})["session"] == "ses_00000001" and len(reached["hand_to_claude"]) == 1
        assert client.post(f"{BASE}/drafts/pulse-board/hand-to-claude").status_code in (200, 502) and len(reached["hand_to_claude"]) == 2
        assert tool("widget_lab_draft_delete", {"slug": "pulse-board"})["discarded"]
        assert client.delete(f"{BASE}/drafts/other-thing").status_code == 200 and len(reached["discard_draft"]) == 2
        assert tool("widget_lab_drafts_list", {})["drafts"] == []


def test_a_tool_refuses_in_the_routes_own_words(tmp_path: Path, monkeypatch) -> None:
    ctx = _ctx(tmp_path / "s")

    def call(name: str, args: dict) -> Any:
        return asyncio.run(mcp.TOOLS[name].handler(ctx, SimpleNamespace(), args))

    with pytest.raises(ToolError, match=r"refused \(draft_invalid\)"):
        call("widget_lab_draft_create", {"kind": "new", "name": "x", "hosts": ["sidebar"]})
    with pytest.raises(ToolError, match=r"refused \(draft_not_found\)"):
        call("widget_lab_draft_get", {"slug": "nothing-here"})
    with pytest.raises(ToolError, match=r"refused \(draft_invalid\)"):
        call("widget_lab_draft_get", {})
    assert call("widget_lab_draft_create", {"kind": "new", "name": "Pulse board"})
    with pytest.raises(ToolError, match=r"refused \(draft_invalid\)"):
        call("widget_lab_draft_file_set", {"slug": "pulse-board", "path": "../../escape.txt", "content": "x"})
    with pytest.raises(ToolError):
        call("widget_lab_draft_file_set", {"slug": "pulse-board", "path": "BRIEF.md", "content": 5})
    assert not (tmp_path / "escape.txt").exists() and not (tmp_path / "s" / "escape.txt").exists()
    monkeypatch.setattr(store, "SCRIPT", Path("/nonexistent/capture_one.py"))
    for name, args in (("widget_lab_draft_get", {"slug": "pulse-board"}), ("widget_lab_draft_create", {"kind": "new", "name": "Other"}),
                       ("widget_lab_draft_file_set", {"slug": "pulse-board", "path": "BRIEF.md", "content": "x"}), ("widget_lab_draft_rebuild", {"slug": "pulse-board"}),
                       ("widget_lab_draft_spawn", {"slug": "pulse-board"}), ("widget_lab_draft_delete", {"slug": "pulse-board"})):
        with pytest.raises(ToolError, match=r"refused \(no_checkout\)"):
            call(name, args)


def test_the_tools_follow_the_naming_scheme_and_writes_need_the_agent_gate() -> None:
    assert set(mcp.TOOLS) == set(capabilities.TABLE) and len(mcp.TOOLS) == 10
    reads = {"widget_lab_drafts_list", "widget_lab_draft_get", "widget_lab_draft_files_list", "widget_lab_draft_file_get"}
    for name, spec in mcp.TOOLS.items():
        assert name.startswith("widget_lab_") and spec.gate == ("read" if name in reads else "agent"), name


def test_the_create_tool_takes_a_category_and_every_host_and_the_draft_carries_them(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path / "s")

    def call(args: dict) -> Any:
        result = asyncio.run(mcp.TOOLS["widget_lab_draft_create"].handler(ctx, SimpleNamespace(), args))
        return json.loads(result["content"][0]["text"])

    made = call({"kind": "new", "name": "Load board", "category": "monitoring", "hosts": ["home", "drawer", "popout"]})
    assert made["manifest"]["category"] == "monitoring"
    assert made["manifest"]["hosts"] == ["home", "drawer", "popout"]
    assert call({"kind": "new", "name": "Plain board"})["manifest"]["category"] == "tools"
    schema = mcp.TOOLS["widget_lab_draft_create"].properties
    assert schema["category"]["enum"] == ["overview", "sessions", "catalog", "monitoring", "tools", "live"]
    assert schema["hosts"]["items"]["enum"] == ["home", "terminal", "drawer", "popout"]
    with pytest.raises(ToolError, match=r"refused \(draft_invalid\)"):
        call({"kind": "new", "name": "Odd board", "category": "bogus"})
