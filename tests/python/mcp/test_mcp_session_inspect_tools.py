
from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.core.mcp import read_tools, session_inspect_tools, tools
from tests.python.mcp.test_mcp_route_adapters import (  # noqa: F401
    ASLEEP, LIVE_UUID, PANE, READ_ONLY, View, world)

SPECS = session_inspect_tools.SPECS
NAMES = [s.name for s in SPECS]


def _call(name: str, args: dict, caller=PANE) -> dict:
    return asyncio.run(tools.call_tool(View(), caller, name, args))


def _record(monkeypatch, route: str, answer=None) -> list:
    seen: list = []
    module, name = route.split(":")

    async def recorder(*args, **kwargs):
        seen.append((args, kwargs))
        return answer if answer is not None else {"ok": True}

    monkeypatch.setattr(f"{module}.{name}", recorder)
    return seen


def test_every_inspection_tool_is_a_read_a_read_token_can_run(world):
    listed = {d["name"] for d in tools.tool_definitions(READ_ONLY)}
    assert set(NAMES) <= listed
    assert not set(NAMES) & tools.WRITE_TOOLS
    assert all(s.gate == "read" for s in SPECS)
    for spec in SPECS:
        args = {"target": "cloude_b", **spec.example} if spec.reach else dict(spec.example)
        assert not _call(spec.name, args, READ_ONLY).get("isError"), spec.name


def test_git_diff_passes_path_and_staged_explicitly(monkeypatch, world):
    seen = _record(monkeypatch, "src.api.session_git_routes:get_session_git_diff")
    assert not _call("session_git_diff_get", {"target": "cloude_b", "path": "src/a.py"}).get("isError")
    assert not _call("session_git_diff_get", {"target": "cloude_b", "path": "src/a.py", "staged": True}).get("isError")
    assert [(a[1], k) for a, k in seen] == [("ses_cloude_b", {"path": "src/a.py", "staged": False}),
                                            ("ses_cloude_b", {"path": "src/a.py", "staged": True})]


def test_skill_fires_passes_a_concrete_limit(monkeypatch, world):
    seen = _record(monkeypatch, "src.api.session_skill_fires_routes:get_session_skill_fires")
    _call("session_skill_fires_list", {"target": "cloude_b"})
    _call("session_skill_fires_list", {"target": "cloude_b", "limit": 7})
    assert [k["limit"] for _, k in seen] == [session_inspect_tools.DEFAULT_SKILL_FIRES, 7]


def test_recent_and_background_pass_their_filters_as_plain_values(monkeypatch, world):
    recent = _record(monkeypatch, "src.api.session_recent_routes:list_recent_sessions")
    background = _record(monkeypatch, "src.api.session_discovery_routes:list_background_sessions")
    _call("session_resume_candidates_list", {})
    _call("session_resume_candidates_list", {"include_archived": True})
    _call("session_background_agents_list", {})
    _call("session_background_agents_list", {"cwd": "/w"})
    assert [k for _, k in recent] == [{"include_archived": False, "include_automated": False},
                                      {"include_archived": True, "include_automated": False}]
    assert [k for _, k in background] == [{"cwd": None}, {"cwd": "/w"}]


def test_local_servers_takes_the_tmux_name_and_conversations_the_uuid(monkeypatch, world):
    servers = _record(monkeypatch, "src.api.session_logs_routes:get_local_servers")
    convs = _record(monkeypatch, "src.api.session_conversations_routes:list_conversations")
    _call("session_local_servers_list", {"target": "cloude_b"})
    _call("session_conversations_list", {"target": ASLEEP})
    assert servers[0][0][1] == "cloude_b"
    assert convs[0][0] == (ASLEEP,)
    _call("session_conversations_list", {"target": "cloude_b"})
    assert convs[1][0] == (LIVE_UUID,)


@pytest.mark.parametrize("name,args", [
    ("session_skill_fires_list", {"target": "cloude_b", "limit": 0}),
    ("session_skill_fires_list", {"target": "cloude_b", "limit": 51}),
    ("session_skill_fires_list", {"target": "cloude_b", "limit": True}),
    ("session_git_diff_get", {"target": "cloude_b", "path": 7}),
    ("session_git_diff_get", {"target": "cloude_b", "path": ""}),
    ("session_git_diff_get", {"target": "cloude_b", "path": "x" * (session_inspect_tools.MAX_DIFF_PATH_CHARS + 1)}),
    ("session_background_agents_list", {"cwd": 5}),
])
def test_a_bad_argument_is_refused_before_any_route_runs(world, name, args):
    answer = _call(name, args)
    assert answer["isError"] is True and world == []


SECRET = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


def _canned(spec) -> object:
    if spec.name == "session_prompts_list":
        return SimpleNamespace(prompts=[f"use {SECRET}"])
    if spec.name == "session_conversations_list":
        return {"session_uuid": "s", "previous": [{"first_prompt": f"use {SECRET}"}], "previous_count": 1}
    return {"input_tokens": 12, "note": f"use {SECRET}"}


def _args(spec) -> dict:
    return {"target": "cloude_b", **spec.example} if spec.reach else dict(spec.example)


def test_every_inspection_spec_declares_redaction() -> None:
    assert all(s.redact for s in SPECS)


@pytest.mark.parametrize("spec", SPECS, ids=NAMES)
def test_every_answer_is_redacted_and_keeps_its_keys(monkeypatch, world, spec):
    async def route(*args, **kwargs):
        return _canned(spec)

    module, name = spec.route.split(":")
    monkeypatch.setattr(f"{module}.{name}", route)
    answer = _call(spec.name, _args(spec))
    assert not answer.get("isError"), answer
    text = answer["content"][0]["text"]
    assert SECRET not in text and "****" in text


def test_the_redactor_never_runs_on_the_event_loop(monkeypatch, world) -> None:
    seen: list = []
    real = read_tools.scrub

    def spy(value, drop_token_keys=True):
        seen.append(threading.current_thread())
        return real(value, drop_token_keys)

    monkeypatch.setattr(read_tools, "scrub", spy)
    assert not _call("session_pane_facts_get", {"target": "cloude_b"}).get("isError")
    assert seen and all(t is not threading.main_thread() for t in seen)


def test_an_error_text_is_redacted_too(monkeypatch, world) -> None:
    async def refuse(*args, **kwargs):
        raise HTTPException(status_code=404, detail=f"no such file {SECRET}")

    monkeypatch.setattr("src.api.session_pane_facts_routes.get_session_pane_facts", refuse)
    answer = _call("session_pane_facts_get", {"target": "cloude_b"})
    assert answer["isError"] is True and SECRET not in answer["content"][0]["text"]


def test_prompts_and_conversations_are_cut_to_the_newest_limit(monkeypatch, world) -> None:
    async def prompts(*args, **kwargs):
        return SimpleNamespace(prompts=[f"p{i}" for i in range(50)])

    async def convs(*args, **kwargs):
        return {"session_uuid": "s", "previous": [{"conversation_id": f"c{i}"} for i in range(30)], "previous_count": 30}

    monkeypatch.setattr("src.api.session_prompt_texts_routes.get_prompt_texts", prompts)
    monkeypatch.setattr("src.api.session_conversations_routes.list_conversations", convs)
    out = json.loads(_call("session_prompts_list", {"target": "cloude_b"})["content"][0]["text"])
    assert out["total"] == 50 and out["prompts"] == [f"p{i}" for i in range(30, 50)]
    out = json.loads(_call("session_prompts_list", {"target": "cloude_b", "limit": 2})["content"][0]["text"])
    assert out["prompts"] == ["p48", "p49"]
    out = json.loads(_call("session_conversations_list", {"target": "cloude_b", "limit": 3})["content"][0]["text"])
    assert [c["conversation_id"] for c in out["previous"]] == ["c0", "c1", "c2"] and out["previous_count"] == 30
    for tool in ("session_prompts_list", "session_conversations_list"):
        assert _call(tool, {"target": "cloude_b", "limit": session_inspect_tools.MAX_ROWS + 1})["isError"] is True


def test_subagents_are_cut_to_the_newest_limit_and_the_counts_stay_whole(monkeypatch, world) -> None:
    async def route(*args, **kwargs):
        return {"state": "ok", "counts": {"total": 60, "listed": 60, "running": 1},
                "subagents": [{"id": f"a{i}"} for i in range(60)]}

    monkeypatch.setattr("src.api.subagent_routes.get_session_subagents", route)
    out = json.loads(_call("session_subagents_list", {"target": "cloude_b"})["content"][0]["text"])
    assert [a["id"] for a in out["subagents"]] == [f"a{i}" for i in range(50)]
    assert out["counts"]["total"] == 60
    assert out["returned"] == 50 and out["truncated"] is True
    out = json.loads(_call("session_subagents_list", {"target": "cloude_b", "limit": 2})["content"][0]["text"])
    assert [a["id"] for a in out["subagents"]] == ["a0", "a1"]
    for bad in (0, session_inspect_tools.MAX_SUBAGENT_ROWS + 1, True, "3"):
        assert _call("session_subagents_list", {"target": "cloude_b", "limit": bad})["isError"] is True


def test_git_diff_without_a_path_answers_the_changed_file_list(monkeypatch, world) -> None:
    listing = _record(monkeypatch, "src.api.session_git_routes:get_session_git_status", {"state": "ok", "files": []})
    diff = _record(monkeypatch, "src.api.session_git_routes:get_session_git_diff")
    assert not _call("session_git_diff_get", {"target": "cloude_b"}).get("isError")
    assert len(listing) == 1 and listing[0][0][1] == "ses_cloude_b" and diff == []


def test_a_credential_straddling_the_error_cut_is_starred_whole(monkeypatch, world) -> None:
    async def refuse(*args, **kwargs):
        raise HTTPException(status_code=404, detail="x" * 290 + SECRET)

    monkeypatch.setattr("src.api.session_pane_facts_routes.get_session_pane_facts", refuse)
    text = _call("session_pane_facts_get", {"target": "cloude_b"})["content"][0]["text"]
    assert "ghp_" not in text and "a1B2" not in text


def test_concurrent_answers_are_redacted_one_at_a_time(monkeypatch, world) -> None:
    import time

    state = {"now": 0, "max": 0}
    lock = threading.Lock()
    real = read_tools.scrub

    inner = threading.local()

    def slow(value, drop_token_keys=True):
        if getattr(inner, "busy", False):
            return real(value, drop_token_keys)
        inner.busy = True
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(0.05)
        out = real(value, drop_token_keys)
        inner.busy = False
        with lock:
            state["now"] -= 1
        return out

    monkeypatch.setattr(read_tools, "scrub", slow)

    async def four() -> list:
        return await asyncio.gather(*(tools.call_tool(View(), PANE, "session_pane_facts_get", {"target": "cloude_b"}) for _ in range(4)))

    answers = asyncio.run(four())
    assert not any(a.get("isError") for a in answers) and state["max"] == 1


def test_staged_without_a_path_is_refused_not_ignored(monkeypatch, world) -> None:
    listing = _record(monkeypatch, "src.api.session_git_routes:get_session_git_status")
    assert _call("session_git_diff_get", {"target": "cloude_b", "staged": True})["isError"] is True
    assert listing == []


def test_a_quiet_running_subagent_is_never_cut_below_newer_finished_ones(monkeypatch, world) -> None:
    async def route(*args, **kwargs):
        rows = [{"id": f"d{i}", "status": "done"} for i in range(60)] + [{"id": "quiet", "status": "running"}]
        return {"state": "ok", "counts": {"total": 61, "listed": 61, "running": 1}, "subagents": rows}

    monkeypatch.setattr("src.api.subagent_routes.get_session_subagents", route)
    out = json.loads(_call("session_subagents_list", {"target": "cloude_b", "limit": 3})["content"][0]["text"])
    assert [a["id"] for a in out["subagents"]] == ["quiet", "d0", "d1"]
    assert out["returned"] == 3 and out["truncated"] is True
    whole = json.loads(_call("session_subagents_list", {"target": "cloude_b", "limit": 200})["content"][0]["text"])
    assert whole["returned"] == 61 and whole["truncated"] is False
