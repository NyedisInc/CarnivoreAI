
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from src.core.swarm import commit_guard, launch


def _git(repo: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True, timeout=30)


def test_codename_refused_plain_message_passes_and_repo_hook_still_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(launch, "profile_names_chrome", lambda agent: False)
    state, repo = tmp_path / "state", tmp_path / "repo"
    repo.mkdir()
    agent = {"id": 7, "slug": "elmfield", "rank": "task", "effort": "medium", "persona": "Elmfield"}
    argv = launch.swarm_argv(agent, state)
    settings_file = launch.settings_path(state, 7)
    assert argv[argv.index("--settings") + 1] == str(settings_file)
    guard = json.loads(settings_file.read_text())["env"]
    assert guard == commit_guard.guard_env(commit_guard.hooks_dir(state, 7))

    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    assert _git(repo, env, "init", "-q").returncode == 0
    marker = tmp_path / "repo-hook-ran"
    own = repo / ".git" / "hooks" / "commit-msg"
    own.write_text(f'#!/bin/sh\necho ran >> "{marker}"\n')
    own.chmod(0o755)
    env = {**env, **guard}

    refused = _git(repo, env, "commit", "-q", "--allow-empty", "-m", "fix login, by ELMFIELD")
    assert refused.returncode != 0 and "codename" in refused.stderr
    assert not marker.exists()
    passed = _git(repo, env, "commit", "-q", "--allow-empty", "-m", "fix the motherboard probe")
    assert passed.returncode == 0, passed.stderr
    assert marker.read_text() == "ran\n"
    assert _git(repo, env, "config", "--local", "--get", "core.hooksPath").stdout == ""


def test_no_persona_means_no_settings_and_a_cleared_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(launch, "profile_names_chrome", lambda agent: False)
    state = tmp_path / "state"
    agent = {"id": 8, "slug": "fixer", "rank": "task", "effort": "medium", "persona": "Loki"}
    launch.swarm_argv(agent, state)
    assert "--settings" not in launch.swarm_argv({**agent, "persona": None}, state)
    assert "env" not in json.loads(launch.settings_path(state, 8).read_text())
