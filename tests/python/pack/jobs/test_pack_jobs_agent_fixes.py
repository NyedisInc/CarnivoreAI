
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Optional

import pytest

from src.core.attention import evidence as ev
from src.core.pack.jobs import agent_account, agent_facts, agent_watch, paths, runner, tell
from src.core.pack.jobs.agent_types import AgentSpec, definition_fits
from src.core.pack.jobs.types import JobError, JobRecord

ROW_UUID = "7f3e9c10-aaaa-bbbb-cccc-000000000001"


class RegistryManager:

    def __init__(self, info: Any) -> None:
        self.info = info
        self.asked: List[str] = []

    async def get_session_info(self, session_id: Optional[str] = None) -> Any:
        self.asked.append(str(session_id))
        return self.info if session_id == self.info.session.id else None

    async def list_session_infos(self) -> List[Any]:
        return [self.info]

    def tmux_socket_name(self) -> str:
        return "t"

    def claude_uuid_for_tmux_name(self, name: str) -> Optional[str]:
        return None


def _info(**over: Any) -> Any:
    base = {"session": SimpleNamespace(id="ses_ab12", working_dir="/w", tmux_created_epoch=5), "session_uuid": ROW_UUID, "agent_family": "claude",
            "tmux_session": None, "running_model": None, "launched_with": None}
    base.update(over)
    return SimpleNamespace(**base)


def _facts(monkeypatch: pytest.MonkeyPatch, info: Any, raw_mode: Optional[str] = None) -> agent_facts.CallerFacts:
    from src.core.session_token_usage import account_resolve

    monkeypatch.setattr(account_resolve, "resolve_session_account", lambda *a, **k: None)
    monkeypatch.setattr(agent_facts, "_transcript_facts", lambda sm, i, f: (raw_mode, None))
    app = SimpleNamespace(state=SimpleNamespace(session_manager=RegistryManager(info)))
    return asyncio.run(agent_facts.caller_launch_facts(app, ROW_UUID))


def test_the_row_uuid_is_found_through_the_listing_not_the_registry_key(monkeypatch) -> None:
    info = _info()
    facts = _facts(monkeypatch, info, "acceptEdits")
    assert (facts.family, facts.permission_mode) == ("claude", "acceptEdits")
    assert asyncio.run(agent_facts.info_for_caller(RegistryManager(info), ROW_UUID)) is info
    assert asyncio.run(agent_facts.info_for_caller(RegistryManager(info), "ses_ab12")) is info
    assert asyncio.run(agent_facts.info_for_caller(RegistryManager(info), "uuid-of-nobody")) is None
    assert asyncio.run(agent_facts.info_for_caller(RegistryManager(info), None)) is None

    from src.core.crosstalk import directory

    async def cards(*_a: Any, **_k: Any) -> List[dict]:
        return [{"id": "ses_ab12", "session_uuid": ROW_UUID}]

    monkeypatch.setattr(directory, "list_cards", cards)
    app = SimpleNamespace(state=SimpleNamespace(session_manager=RegistryManager(info)))
    got = asyncio.run(tell.resolve_receiver(app, ROW_UUID))
    assert got is not None and got.id == "ses_ab12" and got.uuid == ROW_UUID
    job = JobRecord(id="job_0123456789ab", caller_session=ROW_UUID)
    assert tell.check_receiver(job.caller_session, got) is got


def test_an_unknown_codex_posture_is_ask_and_bypass_needs_the_launch_record(monkeypatch) -> None:
    for posture in (None, "harness_default", "accept_edits", "ask"):
        launched = {"permissions": posture} if posture else None
        assert _facts(monkeypatch, _info(agent_family="codex", launched_with=launched)).permission_mode == "ask"
    assert _facts(monkeypatch, _info(agent_family="codex", launched_with={"permissions": "skip_all"})).permission_mode == "skip_all"
    assert _facts(monkeypatch, _info(launched_with=None), "bypassPermissions").permission_mode == "default"
    assert _facts(monkeypatch, _info(launched_with={"permissions": "accept_edits"}), "bypassPermissions").permission_mode == "default"
    assert _facts(monkeypatch, _info(launched_with={"permissions": "skip_all"}), "bypassPermissions").permission_mode == "bypassPermissions"
    assert _facts(monkeypatch, _info(launched_with=None), "acceptEdits").permission_mode == "acceptEdits"


def _agents(tmp_path: Path) -> Path:
    folder = tmp_path / "proj" / ".claude" / "agents"
    folder.mkdir(parents=True)
    return folder


def test_a_definition_link_out_of_its_folder_or_a_huge_file_is_refused(tmp_path: Path) -> None:
    folder = _agents(tmp_path)
    secret = tmp_path / "creds"
    secret.write_text("aws_secret_access_key = SHOULD-NEVER-BE-READ")
    (folder / "rev.md").symlink_to(secret)
    with pytest.raises(JobError) as err:
        agent_facts.definition_from_file(folder / "rev.md", "rev")
    assert err.value.code == "bad_request" and "SHOULD-NEVER" not in err.value.detail
    (folder / "real.md").write_text("---\ndescription: d\n---\nbody")
    (folder / "alias.md").symlink_to(folder / "real.md")
    assert agent_facts.definition_from_file(folder / "alias.md", "alias").body == "body"
    (folder / "huge.md").write_bytes(b"x" * (agent_facts.FILE_MAX + 10))
    with pytest.raises(JobError) as big:
        agent_facts.definition_from_file(folder / "huge.md", "huge")
    assert big.value.code == "definition_too_large"


def test_a_definition_the_launch_cannot_carry_is_refused_by_the_caller_before_any_card(tmp_path: Path) -> None:
    folder = _agents(tmp_path)
    (folder / "quotes.md").write_text("---\ndescription: d\n---\n" + "'" * 3000)
    with pytest.raises(JobError) as err:
        agent_facts.definition_from_file(folder / "quotes.md", "quotes")
    assert err.value.code == "definition_too_large"
    (folder / "ok.md").write_text("---\ndescription: d\n---\n" + "x" * 7000)
    found = agent_facts.definition_from_file(folder / "ok.md", "ok")
    assert definition_fits("ok", found.definition_json)
    AgentSpec(task="t", family="claude", permission_mode="default", agent_type="ok", definition_json=found.definition_json)


def test_the_model_check_is_the_repos_own() -> None:
    for bad in ("--continue", "-p", "a..b", "m[1m]", "x" * 65):
        with pytest.raises(ValueError):
            AgentSpec(task="t", family="claude", permission_mode="default", model=bad)
        assert agent_facts._clean_model(bad) is None
    assert AgentSpec(task="t", family="claude", permission_mode="default", model="claude-sonnet-4-5:200k").model == "claude-sonnet-4-5:200k"


def _obs(waiting_for: Optional[str]) -> Any:
    return SimpleNamespace(verdict=ev.AttentionVerdict(ev.STATE_NEEDS_USER, ev.REASON_INPUT, ev.TIER_REGISTRY, detail="waits"),
                           evidence=SimpleNamespace(dialog=None, startup_screen=None, registry=SimpleNamespace(waiting_for=waiting_for)),
                           cycle=1, stale=False)


def test_a_sandbox_or_worker_request_is_the_owners_not_a_callers() -> None:
    for waiting in ("sandbox request", "worker request"):
        got = agent_watch.classify(_obs(waiting))
        assert (got.kind, got.qkind) == ("owner", "permission")
    for waiting in ("input needed", "dialog open", None):
        assert agent_watch.classify(_obs(waiting)).kind == "ask"


def test_a_codex_rollout_is_found_only_in_the_workers_sessions_folder(tmp_path: Path) -> None:
    conv = "0190aaaa-bbbb-cccc-dddd-eeeeffff0001"
    home = tmp_path / "codex"
    day = home / "sessions" / "2026" / "11" / "16"
    day.mkdir(parents=True)
    own = day / f"rollout-2026-11-16T10-00-00-{conv}.jsonl"
    own.write_text("{}\n")
    assert agent_watch.transcript_path("codex", conv, None, str(home)) == own.resolve()
    outside = tmp_path / "other-project.jsonl"
    outside.write_text("{}\n")
    own.unlink()
    own.symlink_to(outside)
    assert agent_watch.transcript_path("codex", conv, None, str(home)) is None
    assert agent_watch.transcript_path("codex", "../../etc/*", None, str(home)) is None
    assert agent_watch.transcript_path("codex", None, None, str(home)) is None


def test_a_known_caller_never_borrows_another_senders_relayed_codex_login(tmp_path: Path, monkeypatch) -> None:
    other = tmp_path / "relay-of-c"
    other.mkdir()
    mine = tmp_path / "relay-of-a"
    mine.mkdir()
    monkeypatch.setattr(agent_account.codex_target, "find_codex_relay_profile", lambda key: str(other))
    monkeypatch.setattr(agent_account.codex_target, "codex_relay_profile_dir", lambda key, caller: str(mine) if caller == "iid-has" else str(tmp_path / "none"))
    monkeypatch.setattr(agent_account.codex_target, "codex_relay_env", lambda profile: {"CODEX_HOME": str(profile)})
    monkeypatch.setattr(agent_account.codex_follow, "follow_active_account", lambda cfg: "followed")
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"accounts": []}))
    assert agent_account.resolve_target_account("codex", "work", "iid-has", cfg).extra_env == {"CODEX_HOME": str(mine)}
    assert agent_account.resolve_target_account("codex", "work", "iid-none", cfg).how != "relay"
    assert agent_account.resolve_target_account("codex", "work", None, cfg).extra_env == {"CODEX_HOME": str(other)}


def test_the_command_job_script_follows_the_one_push_block_source(monkeypatch) -> None:
    real = paths.push_block_env()
    monkeypatch.setattr(paths, "_NO_PUSH_PREFIXES", (*paths._NO_PUSH_PREFIXES, "ftp://"))
    script = runner._RUN_SH.format(job_id="'j'", cwd="'c'", cap=1, push_block=runner._push_block_exports())
    assert "export GIT_CONFIG_COUNT=7" in script and "GIT_CONFIG_VALUE_6=ftp://" in script
    assert real["GIT_CONFIG_COUNT"] == "6"
    monkeypatch.undo()
    assert script.count("export GIT_CONFIG_KEY_") == 7
    assert runner._RUN_SH.format(job_id="'j'", cwd="'c'", cap=1, push_block=runner._push_block_exports()).count("export GIT_CONFIG_KEY_") == 6


def test_project_settings_ride_in_the_snapshot_is_a_known_open_decision() -> None:
    spec = AgentSpec(task="t", family="claude", permission_mode="default")
    from src.core.pack.jobs import agent_launch
    from src.core.pack.jobs.agent_account import AccountPick

    plan = agent_launch.build_launch(spec, Path("/x"), "job_0123456789ab", AccountPick(None))
    assert not any("setting" in a for a in plan.extra_args)
