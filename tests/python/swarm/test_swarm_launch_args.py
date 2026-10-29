
from __future__ import annotations

import os
import tempfile
from contextlib import closing

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pl_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pl_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.api import recreate_routes as rr  # noqa: E402
from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_migration import ensure_db_migrated  # noqa: E402
from src.core.swarm import launch, store  # noqa: E402
from src.core.swarm.launch import with_swarm_args  # noqa: E402
from src.core.session_agent_infer import PER_RUN_FLAGS  # noqa: E402
from src.core.session_recreate_presence import TMUX_GONE, TmuxPresence  # noqa: E402
from src.core.session_sleep import REFUSED_NO_CONVERSATION, sleep_refusal  # noqa: E402

CONV = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path, raising=True)
    monkeypatch.setattr(rr, "_socket_name", lambda: "cloude", raising=True)
    monkeypatch.setattr(rr, "_measure_presence", lambda n, s: TmuxPresence(outcome=TMUX_GONE, detail="x"), raising=True)
    assert ensure_db_migrated(tmp_path).status == "ok"
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        ids = {}
        for key, conv in (("plain", CONV), ("feature", CONV + "-f"), ("project", CONV + "-p")):
            conn.execute(
                "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, working_dir, "
                "claude_session_uuid, title, origin, lifecycle, created_at, updated_at) VALUES (?, 'cloude', ?, 1788821572, "
                "'/Users/x/proj', ?, 't', 'created', 'stopped', '2026-03-01T00:00:00Z', '2026-09-08T00:00:00Z')",
                (f"uuid-{key}", f"cloude_{key}", conv),
            )
            ids[key] = conn.execute("SELECT id FROM sessions WHERE session_uuid = ?", (f"uuid-{key}",)).fetchone()[0]
        alpha = store.create_agent(conn, slug="alpha", rank="alpha", job="j", display_name="a", repo_dir="/tmp/pk", effort="max")
        for key, rank, slug in (("feature", "feature", "loki"), ("project", "project", "hq")):
            agent = store.create_agent(conn, slug=slug, rank=rank, job="j", display_name=slug, repo_dir=f"/tmp/pk-{slug}",
                                       effort="high", parent_id=alpha["id"], project_id=None)
            store.set_session_row(conn, agent["id"], ids[key])
            ids[key + "_agent"] = agent["id"]
    return tmp_path, ids


def test_swarm_row_recreate_leads_with_agent_and_effort_fresh_drops_resume(env):
    gathered = rr._gather("uuid-feature")["extra_args"]
    assert gathered[:4] == ["--agent", "loki", "--effort", "high"]
    assert "--resume" in gathered and gathered.index("--resume") > 3 and "--restricted" not in gathered
    fresh = rr._gather("uuid-feature", fresh=True)["extra_args"]
    assert fresh == ["--agent", "loki", "--effort", "high", "--no-chrome"]
    with closing(connect(db_path_for(env[0]), create=False)) as conn:
        assert conn.execute("SELECT claude_session_uuid FROM sessions WHERE session_uuid = 'uuid-feature'").fetchone()[0]


def test_command_carries_the_swarm_flags_before_resume(env):
    from src.config import settings

    extra = rr._gather("uuid-feature")["extra_args"]
    command = settings.get_agent_command("claude", model="opus", extra_args=extra)
    assert command.index("--agent") < command.index("--effort") < command.index("--resume")


def test_plain_row_is_unchanged(env):
    assert rr._gather("uuid-plain")["extra_args"] == ["--resume", CONV, "--name", "t"]
    assert launch.swarm_launch_args(env[1]["plain"]) == []
    assert with_swarm_args(env[1]["plain"], None) is None
    assert with_swarm_args(None, ["--x"]) == ["--x"]


def test_upper_rank_lockdown_and_restart_seam(env):
    tmp_path, ids = env
    args = launch.swarm_launch_args(ids["project"])
    assert args[:4] == ["--agent", "hq", "--effort", "high"]
    assert args[4:7] == ["--setting-sources", "project,local", "--strict-mcp-config"]
    assert args[7:9] == ["--tools", "Read,Grep,Glob"]
    assert args[9:] == ["--settings", str(tmp_path / "swarm" / "settings" / f"{ids['project_agent']}.json"),
                        "--add-dir", str(tmp_path / "swarm" / "desk" / str(ids["project_agent"])), "--no-chrome"]
    seam = launch.with_swarm_args_for_tmux("cloude", "cloude_project", ["--resume", CONV])
    assert seam[:2] == ["--agent", "hq"] and seam[-2:] == ["--resume", CONV]
    assert launch.with_swarm_args_for_tmux("cloude", "cloude_plain", None) is None


def test_per_run_flags_and_sleep_fresh_ok():
    assert {"--agent", "--effort", "--settings", "--tools", "--setting-sources", "--strict-mcp-config", "--add-dir"} <= PER_RUN_FLAGS
    row = {"lifecycle": "running", "tmux_name": "cloude_x", "tmux_created_epoch": 1, "tmux_socket": "cloude",
           "claude_session_uuid": None, "agent_family": "claude"}
    refused = sleep_refusal(row)
    assert refused is not None and refused.code == REFUSED_NO_CONVERSATION
    assert sleep_refusal(row, fresh_ok=True) is None


def test_unreadable_datastore_fails_closed_instead_of_starting_a_plain_claude(env, monkeypatch):
    tmp_path, ids = env
    path = db_path_for(tmp_path)

    def broken(*a, **k):
        raise launch.DatastoreUnreadableError("cannot open")

    monkeypatch.setattr(launch, "connect", broken)
    with pytest.raises(launch.SwarmLaunchUnreadable):
        launch.swarm_launch_args(ids["feature"])
    with pytest.raises(launch.SwarmLaunchUnreadable):
        launch.with_swarm_args_for_tmux("cloude", "cloude_feature", ["--resume", "x"])
    monkeypatch.setattr(launch, "db_path_for", lambda state: tmp_path / "absent" / "cloude.db")
    assert launch.swarm_launch_args(ids["feature"]) == []
    assert path.exists()
