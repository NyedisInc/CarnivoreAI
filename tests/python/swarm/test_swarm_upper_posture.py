
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pu_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pu_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.config import settings as _settings  # noqa: F401
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.launch_profiles.resolve import LaunchRequest, resolve_launch
from src.core.launch_profiles.store import LaunchProfileStore
from src.core.swarm import body, definition, delivery, launch, profiles, store, thread_port
from src.core.swarm import body_create
from src.core.swarm.body_create import BodyIdentity


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path, raising=True)
    cfg = tmp_path / "config.json"
    cfg.write_text("{}")
    monkeypatch.setattr(settings, "auth_config_file", str(cfg), raising=False)
    assert ensure_db_migrated(tmp_path).status == "ok"
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        alpha = store.create_agent(conn, slug="alpha", rank="alpha", job="j", display_name="Alpha", repo_dir="/tmp/pu", effort="max")
        task = store.create_agent(conn, slug="loki", rank="task", job="j", display_name="Loki", repo_dir="/tmp/pu-loki",
                                  effort="high", parent_id=alpha["id"])
    cards, started = [], []

    class Port:
        async def post_card(self, key, kind, title, text, ref):
            cards.append((key, title, ref))

    thread_port.register(Port())

    async def fake_start(app_state, agent, mode):
        started.append(agent["id"])
        return BodyIdentity("ses_new", 1, "uuid-x", "cloude_x", 1)

    async def fake_finish(*a, **k):
        with closing(connect(db_path_for(tmp_path), create=False)) as conn:
            store.cas_state(conn, a[1]["id"], "waking", "awake")

    monkeypatch.setattr(body, "_start", fake_start)
    monkeypatch.setattr(body, "finish_start", fake_finish)
    monkeypatch.setattr(delivery, "send_wake_prompt", lambda *a, **k: None)
    yield SimpleNamespace(cfg=cfg, alpha=alpha["id"], task=task["id"], cards=cards, started=started)
    thread_port.register(None)


_ASK = '{"swarm": {"upper_ranks_permissions": "ask"}}'


def test_seed_renders_manual_with_no_skip_flag_and_is_idempotent(env):
    assert profiles.ensure_seed(env.cfg, "ask") is True and profiles.ensure_seed(env.cfg, "ask") is False
    block = LaunchProfileStore(env.cfg).read()
    assert [p.id for p in block.profiles][-1] == "swarm-upper"
    assert [p.id for p in block.profiles if p.default] != ["swarm-upper"] and sum(p.default for p in block.profiles) == 1
    plan = resolve_launch(LaunchRequest(profiles=tuple(block.profiles), agent_type="swarm-upper", explicit=True))
    assert "--permission-mode manual" in plan.command and "skip-permissions" not in plan.command


def test_owner_edited_profile_keeps_its_fields_and_its_posture_follows_the_setting(env):
    profiles.ensure_seed(env.cfg, "skip_all")
    edited = LaunchProfileStore(env.cfg).get("swarm-upper").model_copy(update={"label": "mine", "permissions": "ask"})
    LaunchProfileStore(env.cfg).put(edited)
    assert profiles.ensure_seed(env.cfg, "skip_all") is True and profiles.ensure_seed(env.cfg, "skip_all") is False
    kept = LaunchProfileStore(env.cfg).get("swarm-upper")
    assert kept.label == "mine" and kept.permissions == "skip_all"


def test_upper_rank_wake_refused_once_with_a_card_and_no_body(env):
    env.cfg.write_text(_ASK)
    with closing(connect(db_path_for(env.cfg.parent), create=False)) as conn:
        store.update_agent(conn, env.alpha, launch_profile="claude")
    with pytest.raises(body.BodyError, match="not 'ask'"):
        asyncio.run(body.wake(object(), env.alpha, "manual", "data"))
    assert env.started == [] and len(env.cards) == 1 and env.cards[0][2] == f"wake_refused:{env.alpha}"
    with closing(connect(db_path_for(env.cfg.parent), create=False)) as conn:
        assert store.get_agent(conn, env.alpha)["state"] == "asleep"
        assert conn.execute("SELECT COUNT(*) FROM swarm_wakes").fetchone()[0] == 0


def test_upper_rank_wakes_on_the_seeded_profile_and_task_rank_is_unaffected(env):
    first = asyncio.run(body.wake(object(), env.alpha, "manual", "data"))
    assert first.started and env.started == [env.alpha]
    assert json.loads(env.cfg.read_text())["launch_profiles"]["profiles"][-1]["id"] == "swarm-upper"
    other = asyncio.run(body.wake(object(), env.task, "manual", "data"))
    assert other.started and env.cards == []
    assert profiles.posture_refusal({"rank": "task", "harness": "claude", "launch_profile": "nope"}, Path("/nonexistent")) is None


def _repo(tmp_path: Path, name: str, content: str) -> str:
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    (repo / ".claude" / name).write_text(content)
    return str(repo)


def test_upper_argv_has_the_proven_flag_set_and_keeps_carnivore_mcp(tmp_path, monkeypatch):
    from src.config.agent_command import single_name_flag

    argv = launch.launch_args_for_agent({"id": 3, "slug": "loki", "rank": "project", "effort": "high"}, tmp_path)
    assert "--restricted" not in argv
    assert argv[argv.index("--setting-sources") + 1] == "project,local" and "--strict-mcp-config" in argv
    assert launch.launch_args_for_agent({"id": 4, "slug": "t", "rank": "task", "effort": "low"}, tmp_path) == \
        ["--agent", "t", "--effort", "low", "--no-chrome"]
    from src.config import mcp_launch, settings
    monkeypatch.setattr(mcp_launch, "registration_url", lambda pane, enabled, port: mcp_launch.mcp_url(8000))
    command = settings.get_agent_command("claude", extra_args=argv, pane_launch=True)
    assert "--strict-mcp-config" in command and "--mcp-config=" in command and "carnivore" in command
    assert single_name_flag(["--resume", "u", "--name", "A", "--name", "A"]) == ["--resume", "u", "--name", "A"]
    assert single_name_flag(["--resume", "u", "--name", "A", "--name", "B"]) == ["--resume", "u", "--name", "B"]
    resumed = settings.get_agent_command("claude", extra_args=["--resume", "u", "--name", "A", "--name", "A"], pane_launch=True)
    assert resumed.count("--name") == 1


@pytest.mark.parametrize("rank", ["project", "company", "alpha"])
def test_each_upper_rank_launch_carries_its_tool_limits(tmp_path, rank):
    repo = tmp_path / "repo"
    repo.mkdir()
    agent = {"id": 7, "slug": "loki", "rank": rank, "effort": "high", "repo_dir": str(repo), "memory_scope": "project"}
    body_create.write_settings(tmp_path, agent)
    argv = launch.launch_args_for_agent(agent, tmp_path)
    assert argv[argv.index("--tools") + 1].split(",") == ["Read", "Grep", "Glob"]
    assert argv[argv.index("--settings") + 1] == str(launch.settings_path(tmp_path, 7))
    perms = json.loads(launch.settings_path(tmp_path, 7).read_text())["permissions"]
    assert perms["allow"] == ["mcp__carnivore"] and not any(r.startswith(("Edit", "Write")) for r in perms["allow"])
    assert {"Edit", "Write", "MultiEdit", "NotebookEdit"} <= set(perms["deny"])
    creates = {"mcp__carnivore__session_create", "mcp__carnivore__swarm_spawn", "mcp__carnivore__agent_spawn",
               "mcp__carnivore__swarm_card_create"}
    if rank == "project":
        assert not creates & set(perms["deny"])
    else:
        assert creates <= set(perms["deny"]) and "mcp__carnivore__swarm_suggest" not in perms["deny"]
    assert definition.tools_for_rank(rank) == ("Read", "Grep", "Glob", "mcp__carnivore")


def test_repo_settings_that_allow_edit_refuse_naming_the_file(env, tmp_path):
    env.cfg.write_text(_ASK)
    repo = _repo(tmp_path, "settings.local.json", '{"permissions": {"allow": ["Edit(src/**)"]}}')
    agent = {"rank": "project", "harness": "claude", "launch_profile": None, "repo_dir": repo}
    why = profiles.posture_refusal(agent, env.cfg)
    env.cfg.write_text("{}")
    assert profiles.posture_refusal(agent, env.cfg) is None
    assert why and "settings.local.json" in why and "Edit(src/**)" in why
    assert "mcp__other" in profiles.repo_settings_refusal(_repo_again(tmp_path, '{"permissions": {"allow": ["mcp__other__x"]}}'))


def _repo_again(tmp_path: Path, content: str) -> str:
    repo = tmp_path / "repo2"
    (repo / ".claude").mkdir(parents=True)
    (repo / ".claude" / "settings.json").write_text(content)
    return str(repo)


def test_repo_settings_allowing_only_bash_let_the_wake_proceed(env, tmp_path):
    repo = _repo(tmp_path, "settings.local.json",
                 '{"permissions": {"allow": ["Bash(npm test:*)", "mcp__carnivore__notify"], "defaultMode": "acceptEdits"}}')
    assert profiles.posture_refusal({"rank": "project", "harness": "claude", "launch_profile": None, "repo_dir": repo}, env.cfg) is None
    assert profiles.repo_settings_refusal(str(tmp_path / "no-such-repo")) is None


def test_malformed_repo_settings_refuse_and_the_wake_posts_one_card(env, tmp_path):
    repo = _repo(tmp_path, "settings.json", "{not json")
    env.cfg.write_text(_ASK)
    with closing(connect(db_path_for(env.cfg.parent), create=False)) as conn:
        store.update_agent(conn, env.alpha, repo_dir=repo)
    with pytest.raises(body.BodyError, match="cannot be read or parsed"):
        asyncio.run(body.wake(object(), env.alpha, "manual", "data"))
    assert env.started == [] and len(env.cards) == 1 and env.cards[0][2] == f"wake_refused:{env.alpha}"


def test_read_only_mcp_allows_pass_but_writes_and_wildcards_still_refuse(env, tmp_path):
    ok = ["mcp__filesystem__directory_tree", "mcp__filesystem__read_file", "mcp__context7__resolve-library-id",
          "mcp__brave-search__brave_web_search", "Bash(npm test:*)"]
    repo = _repo(tmp_path, "settings.local.json", json.dumps({"permissions": {"allow": ok}}))
    assert profiles.repo_settings_refusal(repo) is None
    for bad in ("mcp__filesystem__write_file", "mcp__filesystem__move_file", "mcp__filesystem__edit_file",
                "mcp__filesystem__*", "mcp__filesystem", "Edit(src/**)"):
        r = _repo_again(tmp_path / bad.replace("/", "_").replace("*", "w").replace("(", "_").replace(")", "_"),
                        json.dumps({"permissions": {"allow": ok + [bad]}}))
        assert bad in (profiles.repo_settings_refusal(r) or ""), bad


def test_upper_ranks_launch_with_prompts_off_and_a_task_agent_keeps_its_mode(env, tmp_path):
    from src.config import settings

    def command(agent):
        assert profiles.posture_refusal(agent, env.cfg) is None
        settings.drop_auth_config_cache()
        return settings.get_agent_command(profiles.effective_profile(agent) or agent["harness"],
                                          extra_args=launch.swarm_argv(agent, tmp_path), pane_launch=True)

    for rank in ("alpha", "company", "project"):
        built = command({"id": 7, "slug": "up", "rank": rank, "effort": "high", "harness": "claude",
                         "launch_profile": None, "repo_dir": str(tmp_path)})
        assert "--dangerously-skip-permissions" in built and "--permission-mode manual" not in built, rank
    store_ = LaunchProfileStore(env.cfg)
    store_.put(store_.get("claude").model_copy(update={"id": "cld", "label": "cld", "default": False,
                                                       "permissions": "harness_default"}))
    task = command({"id": 8, "slug": "t", "rank": "task", "effort": "low", "harness": "claude", "launch_profile": "cld",
                    "repo_dir": str(tmp_path)})
    assert "--dangerously-skip-permissions" not in task and "--permission-mode" not in task
