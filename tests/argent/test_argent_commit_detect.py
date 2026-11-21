
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any, List

from src.core.argent import commits
from src.plugins.sdk import turn_events

ME = "me@example.test"


def _git(repo: Path, *args: str, email: str = ME) -> str:
    env = {"GIT_AUTHOR_NAME": "x", "GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_NAME": "x", "GIT_COMMITTER_EMAIL": email, "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "HOME": str(repo)}
    return subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=True).stdout.strip()


def _commit(repo: Path, name: str, msg: str, email: str = ME) -> str:
    (repo / name).write_text(msg)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", msg, email=email)
    return _git(repo, "rev-parse", "HEAD")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", ME)
    _commit(repo, "seed.txt", "seed")
    (tmp_path / "state").mkdir()
    return repo


def _use(tool_id: str, command: str, cwd: str, agent: str = "") -> str:
    rec = {"type": "assistant", "cwd": cwd, "timestamp": "2099-01-01T00:00:00Z",
           "message": {"content": [{"type": "tool_use", "id": tool_id, "name": "Bash", "input": {"command": command}}]}}
    return json.dumps({**rec, **({"agentId": agent} if agent else {})}) + "\n"


def _result(tool_id: str, text: str, error: bool = False) -> str:
    return json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id, "content": text, "is_error": error}]}}) + "\n"


def _calls(monkeypatch: Any) -> List[tuple]:
    seen: List[tuple] = []
    real = commits._git

    def spy(cwd: str, *args: str) -> Any:
        seen.append(args)
        return real(cwd, *args)

    monkeypatch.setattr(commits, "_git", spy)
    return seen


def _run(tmp_path: Path, repo: Path, main: Path | None, **kw: Any) -> List[commits.Commit]:
    return commits.process_turn_end("t1", "carnivore_api", working_dir=str(repo), transcript=main, state_dir=tmp_path / "state", since=0.0, **kw)


def test_transcript_commit_is_found_with_its_agent_id_and_one_show(tmp_path: Path, monkeypatch: Any) -> None:
    repo = _repo(tmp_path)
    sha = _commit(repo, "a.py", "add a")
    main = tmp_path / "u1.jsonl"
    main.write_text("")
    subs = tmp_path / "u1" / "subagents"
    subs.mkdir(parents=True)
    (subs / "agent-aaaa1111.jsonl").write_text(
        _use("toolu_ok", f'cd {repo} && git commit -m "add a"', str(repo), "aaaa1111") + _result("toolu_ok", f"[main {sha[:7]}] add a\n 1 file changed")
        + _use("toolu_err", "git commit -m nope", str(repo), "aaaa1111") + _result("toolu_err", "[main deadbee] nope", error=True)
        + _use("toolu_hook", "git commit -m hooked", str(repo), "aaaa1111") + _result("toolu_hook", "pre-commit hook failed"))
    seen = _calls(monkeypatch)
    made = _run(tmp_path, repo, main)
    assert [(c.sha, c.sub_agent_id, c.source, c.subject, c.files) for c in made] == [(sha, "aaaa1111", "transcript", "add a", ("a.py",))]
    assert [a[0] for a in seen].count("show") == 1
    rows = commits.recorded("t1", "carnivore_api", state_dir=tmp_path / "state")
    assert [(r["sha"], r["sub_agent_id"], r["file_count"]) for r in rows] == [(sha, "aaaa1111", 1)]
    assert _run(tmp_path, repo, main) == []
    assert len(commits.recorded("t1", "carnivore_api", state_dir=tmp_path / "state")) == 1


def test_call_split_across_two_turn_ends_and_a_foreign_sha_is_dropped(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    sha = _commit(repo, "b.py", "add b")
    main = tmp_path / "u2.jsonl"
    main.write_text(_use("toolu_1", "git commit -m 'add b'", str(repo)))
    assert _run(tmp_path, repo, main) == []
    with open(main, "a") as handle:
        handle.write(_result("toolu_1", f"[main (root-commit) {sha[:7]}] add b"))
        handle.write(_use("toolu_2", "git commit -m ghost", str(repo)) + _result("toolu_2", "[main 1234567] ghost"))
    made = _run(tmp_path, repo, main)
    assert [c.sha for c in made] == [sha]


def test_head_compare_runs_once_per_turn_end_and_finds_only_the_owners_own_new_commits(tmp_path: Path, monkeypatch: Any) -> None:
    repo = _repo(tmp_path)
    seen = _calls(monkeypatch)
    assert _run(tmp_path, repo, None) == []
    assert seen == [("rev-parse", "HEAD")]
    seen.clear()
    assert _run(tmp_path, repo, None) == []
    assert seen == [("rev-parse", "HEAD")]
    other = _commit(repo, "theirs.txt", "pulled from a teammate", email="other@example.test")
    mine = _commit(repo, "mine.txt", "typed in a terminal")
    seen.clear()
    made = _run(tmp_path, repo, None)
    assert [(c.sha, c.source, c.sub_agent_id) for c in made] == [(mine, "head", "")]
    assert other not in [r["sha"] for r in commits.recorded("t1", "carnivore_api", state_dir=tmp_path / "state")]
    assert [a[0] for a in seen].count("rev-parse") == 1 and [a[0] for a in seen].count("log") == 1
    agent = _commit(repo, "c.py", "agent work")
    main = tmp_path / "u3.jsonl"
    main.write_text(_use("toolu_a", "git commit -m 'agent work'", str(repo), "") + _result("toolu_a", f"[main {agent[:7]}] agent work"))
    made = _run(tmp_path, repo, main)
    assert [(c.sha, c.source) for c in made] == [(agent, "transcript")]


def test_not_a_git_folder_costs_one_failed_call_and_records_nothing(tmp_path: Path, monkeypatch: Any) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    (tmp_path / "state").mkdir()
    seen = _calls(monkeypatch)
    assert commits.process_turn_end("t1", "s", working_dir=str(plain), transcript=None, state_dir=tmp_path / "state") == []
    assert seen == [("rev-parse", "HEAD")]


def test_inert_when_off_and_no_timer_when_on(tmp_path: Path, monkeypatch: Any) -> None:
    seen = _calls(monkeypatch)
    turn_events.reset()
    turn_events.publish_turn_end("ses_1")
    assert not commits.is_running() and seen == []

    async def flow() -> None:
        before = len(asyncio.all_tasks())
        commits.start()
        commits.start()
        assert commits.is_running() and len(asyncio.all_tasks()) == before
        await asyncio.sleep(0.05)
        assert seen == []
        commits.stop()
        assert not commits.is_running()
        turn_events.publish_turn_end("ses_1")
        await asyncio.sleep(0.05)
        assert seen == []

    asyncio.run(flow())
    turn_events.reset()
