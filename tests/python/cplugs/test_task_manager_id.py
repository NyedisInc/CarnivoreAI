
from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import pytest

from src.plugins.host import runtime

PEER_INSTALL = "abcdef1234567890"
PROJECT_UID = "project-uid-1"


def _task_manager() -> Any:
    found = [d for d in runtime.definitions() if "task_manager_add" in d.manifest.surfaces.mcp_tools]
    assert len(found) == 1, [d.id for d in found]
    return found[0]


def test_the_task_manager_manifest_id_is_taskmanager() -> None:
    tm = _task_manager()
    assert tm.id == "taskmanager"
    assert tm.manifest.renamed_from == "huddle"
    assert set(tm.manifest.renamed_from_keeps) == {"strings", "widgets"}


def test_no_shipped_plugin_has_the_old_id() -> None:
    assert all(d.id != "huddle" for d in runtime.definitions())
    assert runtime.canonical_id("huddle") == "taskmanager"


@pytest.fixture
def replica_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from src.config import settings
    from src.core import db

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path)
    with closing(sqlite3.connect(str(db.db_path_for(tmp_path)))) as conn:
        conn.executescript("CREATE TABLE project_replicas (project_uid TEXT, install_id TEXT);")
        conn.execute("INSERT INTO project_replicas VALUES (?, ?)", (PROJECT_UID, PEER_INSTALL))
        conn.commit()
    return tmp_path


def test_a_peer_task_manager_add_reaches_the_plugin(replica_state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.api.federation_pack_span_routes import BoardBody, board_verb
    from src.core.mcp import tools

    ran: List[str] = []

    async def call_tool(view: Any, caller: Any, name: str, args: Any) -> dict:
        ran.append(name)
        return {"ok": True}

    monkeypatch.setattr(tools, "call_tool", call_tool)
    principal = SimpleNamespace(is_peer=True, grant=SimpleNamespace(peer_install_id=PEER_INSTALL))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_manager=None)))
    body = BoardBody(project_uid=PROJECT_UID, args={"title": "from the other Mac"})
    answer = asyncio.run(board_verb("task_manager_add", body, request=request, principal=principal))
    assert answer == {"result": {"ok": True}} and ran == ["task_manager_add"]
