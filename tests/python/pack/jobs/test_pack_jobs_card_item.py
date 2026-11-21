
from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.core.mcp import pack_jobs_tools as pjt
from src.core.mcp import pending
from src.core.pack.jobs import agent_account, agent_facts
from src.core.pack.jobs.agent_account import HOW_WORDS, resolve_target_account
from src.core.pack.jobs.agent_launch import build_launch
from src.core.pack.jobs.agent_types import AgentSpec
from src.core.pack.jobs.engine_agent import AgentMixin, AgentRequest, agent_spec
from src.core.pack.jobs.types import JobState
from tests.python.pack.jobs.test_pack_jobs_agent_tools import JOB, agent_world  # noqa: F401
from tests.python.pack.jobs.test_pack_jobs_surface import CALLER, run, world  # noqa: F401

PROMPT = "review the parser\x1b[31m with care\x00 and <b>never</b> push\nsecond line"


def _prepared(tmp_path: Path, family: str, agent: str = "rev") -> AgentRequest:
    prof = tmp_path / "prof" / "agents"
    prof.mkdir(parents=True)
    (prof / "rev.md").write_text(f"---\nname: rev\ndescription: reviews\n---\n{PROMPT}\n")

    async def facts(_s: Any) -> agent_facts.CallerFacts:
        return agent_facts.CallerFacts(family, "work", "default", None, str(tmp_path / "prof"))

    eng = AgentMixin()
    eng._agent_init(facts, None)
    req = AgentRequest(command="", folder=str(tmp_path), task="review the parser", agent_type=agent, caller_session="u")
    asyncio.run(eng._agent_prepare(req))
    return req


def _card(agent_world, req: AgentRequest, rec_state=JobState.WAITING_APPROVAL):  # noqa: F811
    eng, manager, _ = agent_world

    async def propose(r: Any):
        rec = eng.put(rec_state, family=req.launch["family"], permission_mode="default", agent_type="rev")
        rec.caller_session = r.caller_session
        r.launch = req.launch
        rec.request_json = json.dumps({"request": dataclasses.asdict(r)})
        return rec

    eng.propose = propose
    run(pjt.delegate(manager, CALLER, {"task": "review the parser", "agent_type": "rev"}))
    return pending.get_store().list()[0]


def test_a_claude_card_carries_the_definition_row_and_it_is_the_launch_text(agent_world, tmp_path):  # noqa: F811
    req = _prepared(tmp_path, "claude")
    item = _card(agent_world, req)
    row = next(r for r in item["display"]["detail"] if r["key"] == "definition")
    assert row["file"] == "rev.md" and "/" not in row["file"]
    spec = agent_spec(req)
    plan = build_launch(spec, tmp_path, JOB, SimpleNamespace(extra_env={}, account_id=None, how="relay", label="x"))
    sent = json.loads(plan.extra_args[plan.extra_args.index("--agents") + 1])["rev"]["prompt"]
    assert sent == PROMPT.strip() and row["value"] == "review the parser with care and <b>never</b> push\nsecond line"
    assert "\x1b" not in row["value"] and "\x00" not in row["value"] and "<b>never</b>" in row["value"]
    assert [c["key"] for c in item["display"]["consequences"]] == ["delegate_agent_runs", "delegate_copy", "delegate_mode_ask"]


def test_a_codex_task_and_a_task_with_no_definition_show_no_such_row(agent_world, tmp_path):  # noqa: F811
    codex = _card(agent_world, _prepared(tmp_path, "codex"))
    assert "definition" not in [r["key"] for r in codex["display"]["detail"]]
    assert "## Your role" in {r["key"]: r["value"] for r in codex["display"]["detail"]}["task"]
    assert pjt.definition_shown({"family": "claude", "definition_json": None, "definition_file": None}) is None
    assert pjt.definition_shown({"family": "claude"}) is None


def test_a_reattached_call_shows_the_same_card(agent_world, tmp_path):  # noqa: F811
    eng, manager, _ = agent_world
    req = _prepared(tmp_path, "claude")
    first = _card(agent_world, req)

    async def again(r: Any):
        return eng.rows[JOB]

    eng.propose = again
    run(pjt.delegate(manager, CALLER, {"task": "review the parser", "agent_type": "rev"}))
    items = pending.get_store().list()
    assert len(items) == 1 and items[0]["display"] == first["display"]


def _identity(monkeypatch, local: Any) -> None:
    monkeypatch.setattr(agent_account.move_account, "launch_for", lambda k, s, c: {"account_id": k, "extra_env": None})
    monkeypatch.setattr(agent_account, "_claude_identity", lambda a, c: local)


@pytest.mark.parametrize("caller,local,how", [("a@x.co", "a@x.co", "same"), ("a@x.co", "b@x.co", "local"), ("a@x.co", None, "local"),
                                              ("", "a@x.co", "local"), (None, "b@x.co", "same")])
def test_same_means_the_identity_matches(monkeypatch, tmp_path, caller, local, how):
    _identity(monkeypatch, local)
    pick = resolve_target_account("claude", "work", "iid-a", tmp_path / "config.json", caller)
    assert pick.how == how and pick.account_id == "work" and HOW_WORDS[pick.how]


def test_a_codex_login_is_never_called_same_and_the_words_match_the_catalog():
    assert agent_account._local_how("a@x.co", None) == "local"
    catalog = (Path(__file__).parents[4] / "client/js/i18n/catalog.en.js").read_text()
    for how, words in HOW_WORDS.items():
        assert f"'approvals.display.c.delegate_how_{how}': '{words.replace(chr(39), chr(92) + chr(39))}'" in catalog


def test_the_identity_rides_the_spec_only_when_asked():
    req = AgentRequest(command="", folder="/f", task="t", launch={"family": "claude", "permission_mode": "default", "task": "t", "account_identity": "a@x.co"})
    assert agent_spec(req).model_dump().get("account_identity") is None and "account_identity" not in agent_spec(req).model_dump()
    assert agent_spec(req, True).model_dump()["account_identity"] == "a@x.co"
    assert AgentSpec(task="t", family="claude", permission_mode="default").model_dump().get("account_identity") is None


def test_the_tool_lists_of_a_definition_ride_in_the_same_row_as_its_prompt() -> None:
    raw = json.dumps({"description": "d", "prompt": "p", "tools": ["Read", "Grep"], "disallowedTools": ["Bash"]})
    assert pjt.definition_shown({"definition_json": raw, "definition_file": "rev.md"}) == {"file": "rev.md", "prompt": "p\n\ntools: Read, Grep\n\ndisallowed tools: Bash"}
    assert pjt.definition_shown({"definition_json": '{"prompt": "p"}', "definition_file": "rev.md"})["prompt"] == "p"
