
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from tests.python.deepsearch.helpers import build_world, drain, go_ready, mount, rec, scan, teardown
from tests.python.deepsearch.helpers import switch as set_plugin
from tests.python.transcript_source.helpers import CONV, FOLDER

from fastapi.testclient import TestClient  # noqa: E402

from src.core.mcp import tools  # noqa: E402
from src.core.mcp.caller import AgentCaller  # noqa: E402

OTHER = "b33d7b05-a5e2-4173-8904-e48ff9b18778"
SECRET = "ghp_" + "aB3xY9" * 6
PANE = AgentCaller("ses_1", "cloude_a", "ses_1")


def _tool(i: int, command: str) -> bytes:
    return (json.dumps({"type": "assistant", "uuid": f"t-{i}", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": f"x{i}", "name": "Bash", "input": {"command": command}}]}}) + "\n").encode()


@pytest.fixture()
def world(tmp_path, monkeypatch):
    built = build_world(tmp_path, monkeypatch)
    with open(built["main"], "ab") as handle:
        handle.write(rec(5, f"please find zebrafind for me, key {SECRET}"))
    (built["corpus"] / FOLDER / f"{OTHER}.jsonl").write_bytes(b"".join(_tool(i, f"grep zebrafind f{i}") for i in range(5)))
    app = mount(built, monkeypatch)
    scan(built)
    drain(built)
    go_ready(built)
    built["app"] = app
    yield built
    teardown()


def test_results_are_grouped_by_conversation_and_tool_output_is_not_indexed(world):
    with TestClient(world["app"]) as client:
        body = client.get("/api/v1/deepsearch/search", params={"q": "zebrafind", "per_group": 2}).json()
        assert body["total_conversations"] == 1 and body["total_matches"] == 1
        (said,) = body["groups"]
        assert said["conversation_id"] == CONV and said["by_kind"] == {"user": 1}
        assert said["session"] == "wombat work" and said["session_uuid"] == "sess-uuid-1"
        assert "\x02zebrafind\x03" in said["hits"][0]["snippet"]
        assert SECRET not in said["hits"][0]["snippet"] and "****" in said["hits"][0]["snippet"]
        body_prefix = client.get("/api/v1/deepsearch/search", params={"q": SECRET[4:12]}).json()
        assert body_prefix["total_conversations"] == 0
        assert body["ingest"]["state"] == "running" and body["ingest"]["coverage"]["backlog_files"] == 0
        assert body["ingest"]["cache"]["state"] == "ready"
        tools_only = client.get("/api/v1/deepsearch/search", params={"q": "zebrafind", "kinds": "tool"}).json()
        assert tools_only["groups"] == []
        bad = client.get("/api/v1/deepsearch/search", params={"q": "zebrafind", "kinds": "thinking"})
        assert bad.status_code == 422 and bad.json()["detail"]["code"] == "deepsearch_invalid"


def test_the_route_keeps_answering_with_save_off_and_a_stored_off_switch(world):
    with TestClient(world["app"]) as client:
        assert client.get("/api/v1/deepsearch/status").json()["state"] == "running"
        set_plugin(world["state"], "save", False)
        answered = client.get("/api/v1/deepsearch/search", params={"q": "zebrafind"}).json()
        assert answered["ingest"]["state"] == "running" and answered["total_conversations"] == 1
        assert client.get("/api/v1/deepsearch/status").status_code == 200


def test_conversation_search_keeps_its_name_is_always_on_and_is_scrubbed(world):
    manager = SimpleNamespace(app=world["app"], gate_waited=True, list_session_infos=lambda: [])
    assert "conversation_search" in {d["name"] for d in tools.tool_definitions()}
    result = asyncio.run(tools.call_tool(manager, PANE, "conversation_search", {"q": "zebrafind", "per_group": 1}))
    assert not result.get("isError"), result
    text = result["content"][0]["text"]
    body = json.loads(text)
    assert [g["conversation_id"] for g in body["groups"]] == [CONV] and SECRET not in text
    assert asyncio.run(tools.call_tool(manager, PANE, "conversation_search", {}))["isError"] is True
    assert "conversation_search" in {d["name"] for d in tools.tool_definitions()}
