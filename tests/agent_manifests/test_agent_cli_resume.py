
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.config.launch_profiles import AgentDefinition, LaunchProfile
from src.core.launch_profiles import agent_resume, bundle_guard, restart_seam
from src.core.launch_profiles.store import LaunchProfileStore
from src.core.session_output.escape_notices import NOTICES
from src.core.session_output.escape_scanner import EscapeScanner

PROFILE = {"id": "oc", "harness": "custom", "label": "opencode", "custom_command": {"script": 'opencode "$@"'},
           "agent": {"process": "opencode", "rules": "opencode", "resume": "opencode --session {id}"}}


def test_resume_is_quoted_gated_flagged_and_swapped_in_on_restart(tmp_path):
    with pytest.raises(ValidationError):
        AgentDefinition(resume="sh -c {cmd}")
    with pytest.raises(ValidationError):
        AgentDefinition(resume="/bin/sh x")
    agent = LaunchProfile.model_validate(PROFILE).agent
    with pytest.raises(agent_resume.ResumePrefixNotApproved) as refused:
        agent_resume.resume_command(agent, "abc", [])
    assert refused.value.prefix == "opencode"
    assert agent_resume.resume_command(agent, "abc", ["opencode"]) == "opencode --session abc"
    assert agent_resume.resume_command(agent, "x;rm -rf ~", ["opencode"]) is None

    bundle = {"profiles": [PROFILE], "approved_resume_prefixes": ["opencode"]}
    assert bundle_guard.review(bundle)[0]["resume_command"] is True
    assert {"kind": "resume_command", "text": "opencode --session {id}"} in bundle_guard.review(bundle)[0]["parts"]
    assert bundle_guard.merge_block({"profiles": []}, bundle)["approved_resume_prefixes"] == []

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"launch_profiles": {"revision": 1, "profiles": [PROFILE]}}))
    events = EscapeScanner().feed(b"\x1b]3008;event=idle;id=sess-42\x07")
    NOTICES._queue.extend(("ses_r", e) for e in events)
    NOTICES.drain()
    NOTICES.on_observation("ses_r", "dead", "custom", "carnivore_oc")
    assert NOTICES.resume_id_for_tmux("carnivore_oc") == "sess-42"
    settings = SimpleNamespace(auth_config_file=str(config))
    replayed = restart_seam.ReplayedLaunch(command="opencode", record=json.dumps({"profile": "oc"}))
    with pytest.raises(agent_resume.ResumePrefixNotApproved):
        asyncio.run(restart_seam._with_agent_resume(settings, replayed, "carnivore_oc", "oc"))
    LaunchProfileStore(config).approve_resume_prefix("opencode")
    swapped = asyncio.run(restart_seam._with_agent_resume(settings, replayed, "carnivore_oc", "oc"))
    assert swapped.command == "opencode --session sess-42"


def test_unapproved_prefix_raises_an_approvals_card_that_approves_it(tmp_path, monkeypatch):
    from src.api import launch_profiles_routes, resume_prefix_card
    from src.core.mcp import pending

    config = tmp_path / "config.json"
    config.write_text(json.dumps({"launch_profiles": {"revision": 1, "profiles": [PROFILE]}}))
    monkeypatch.setattr(launch_profiles_routes, "_config_path", lambda: config)
    store = pending.PendingActions()
    monkeypatch.setattr(pending, "_store", store)

    preview = asyncio.run(resume_prefix_card.refused(None, agent_resume.ResumePrefixNotApproved("opencode")))
    assert preview.status_code == 409 and json.loads(preview.body)["approval_id"] is None and not store.list()

    exc = agent_resume.ResumePrefixNotApproved("opencode", tmux_name="carnivore_oc", ask=True)
    body = json.loads(asyncio.run(resume_prefix_card.refused(None, exc)).body)
    assert body["code"] == "resume_prefix_not_approved" and body["approval_id"].startswith("act_")
    assert json.loads(asyncio.run(resume_prefix_card.refused(None, exc)).body)["approval_id"] == body["approval_id"]
    item = store.get(body["approval_id"])
    assert (item.action, item.args, item.beast_eligible) == ("approve_resume_prefix", {"prefix": "opencode"}, False)

    denied = json.loads(asyncio.run(resume_prefix_card.refused(None, agent_resume.ResumePrefixNotApproved(
        "other", tmux_name="carnivore_oc", ask=True))).body)["approval_id"]
    assert store.deny(denied).status == pending.DENIED
    assert LaunchProfileStore(config).read().approved_resume_prefixes == []

    done = asyncio.run(store.approve(body["approval_id"]))
    assert done.status == pending.APPROVED and not done.result.get("isError")
    assert LaunchProfileStore(config).read().approved_resume_prefixes == ["opencode"]
