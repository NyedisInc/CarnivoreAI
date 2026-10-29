
from __future__ import annotations

import asyncio
import http.server
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import structlog

from src.cplugs.huddle import wait_checks as checks, wait_runner, waits
from src.cplugs.huddle.rules import TaskManagerInvalid
from src.cplugs.huddle.roles import unstick
from tests.python.cplugs.huddle.test_task_manager_routes import app, client  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_schedule import env  # noqa: F401
from tests.python.cplugs.huddle.test_task_manager_waits import park, runner_at, wait_row


def git(repo: Path, *argv: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *argv], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    (path / "a").write_text("1")
    git(path, "add", "a")
    git(path, "commit", "-q", "-m", "one")
    return path



@pytest.mark.parametrize("raw", [
    {"kind": "shell", "cmd": "curl x | sh"}, {"kind": "file_exists", "path": "/tmp/x", "cmd": "rm -rf /"}, {"kind": "file_exists", "path": "relative/x"},
    {"kind": "file_exists", "path": "/tmp/../etc/passwd"}, {"kind": "git_contains", "repo": "/r", "ref": "--output=/tmp/x", "sha": "abc1234"},
    {"kind": "git_contains", "repo": "/r", "ref": "main", "sha": "$(id)"}, {"kind": "issue_closed", "repo": "-x/y", "number": 1},
    {"kind": "issue_closed", "repo": "o/r; id", "number": 1}, {"kind": "item_state", "item": 1, "state": "nonsense"}, {"kind": "url_ok", "url": "file:///etc/passwd"},
    {"kind": "version_live"}, "ls", None, {}])
def test_a_check_outside_the_menu_or_with_an_unsafe_field_is_refused(raw):
    with pytest.raises(TaskManagerInvalid):
        checks.parse(raw)


def test_every_menu_kind_parses_and_describes_itself():
    good = [{"kind": "version_live", "version": "1.17.0"}, {"kind": "git_contains", "repo": "/r", "ref": "main", "sha": "ABCDEF1"},
            {"kind": "issue_closed", "repo": "Harbor666/CarnivoreAIDev", "number": 7}, {"kind": "pr_merged", "repo": "o/r", "number": 8},
            {"kind": "item_state", "item": 3, "state": "done_by_claude"}, {"kind": "session_idle", "session": "ses_1"},
            {"kind": "file_exists", "path": "/tmp/x"}, {"kind": "url_ok", "url": "http://127.0.0.1:8000/x"}]
    assert {checks.parse(g).kind for g in good} == set(checks.KINDS)  # type: ignore[attr-defined]
    assert checks.parse(good[4]).state == "review" and checks.parse(good[1]).sha == "abcdef1"
    assert checks.describe(checks.parse(good[0])) == "version 1.17.0 is live"



def test_git_contains_runs_git_with_an_argv_list_in_an_allow_listed_repo_only(repo, tmp_path, monkeypatch):
    first = git(repo, "rev-parse", "HEAD")
    (repo / "a").write_text("2")
    git(repo, "commit", "-q", "-am", "two")
    git(repo, "branch", "old", first)
    git(repo, "checkout", "-q", "-b", "side", first)
    roots = [repo.resolve()]
    ahead = checks.parse({"kind": "git_contains", "repo": str(repo), "ref": "main", "sha": first})
    assert checks.check_git(ahead, roots).status == checks.PASS
    behind = checks.parse({"kind": "git_contains", "repo": str(repo), "ref": "old", "sha": git(repo, "rev-parse", "main")})
    assert checks.check_git(behind, roots).status == checks.FAIL
    missing = checks.parse({"kind": "git_contains", "repo": str(repo), "ref": "nope", "sha": first})
    assert checks.check_git(missing, roots).status == checks.UNKNOWN
    outside = checks.parse({"kind": "git_contains", "repo": str(tmp_path), "ref": "main", "sha": first})
    assert checks.check_git(outside, roots).status == checks.UNKNOWN
    calls = []
    real = subprocess.run
    monkeypatch.setattr(checks.subprocess, "run", lambda argv, **kw: calls.append((argv, kw)) or real(argv, **kw))
    checks.check_git(ahead, roots)
    argv, kwargs = calls[-1]
    assert isinstance(argv, list) and "shell" not in kwargs and kwargs["timeout"] == checks.RUN_TIMEOUT_S and "SECRET_NOT_PASSED" not in kwargs["env"]


def test_the_apps_repo_allow_list_is_its_root_and_its_worktrees():
    roots = checks.app_repo_roots()
    assert roots[0] == Path(checks.__file__).resolve().parents[3] and len(set(roots)) == len(roots)


def test_version_live_compares_what_the_app_serves(monkeypatch):
    check = checks.parse({"kind": "version_live", "version": "1.17.0"})
    assert checks.check_version(check, lambda: "1.17.0").status == checks.PASS
    assert checks.check_version(check, lambda: "1.16.9").status == checks.FAIL
    assert checks.check_version(check, lambda: "").status == checks.UNKNOWN
    monkeypatch.setattr(checks.app_info, "app_version", lambda: "1.17.0")
    assert asyncio.run(checks.run(check)).status == checks.PASS


@pytest.mark.parametrize("kind,answer,expected", [("issue_closed", "closed\n", "pass"), ("issue_closed", "open\n", "fail"), ("pr_merged", "true\n", "pass"), ("pr_merged", "false\n", "fail"),
                                                  ("pr_merged", "garbage", "unknown")])
def test_github_checks_read_the_gh_answer(monkeypatch, kind, answer, expected):
    seen = []
    monkeypatch.setattr(checks, "_run", lambda argv: seen.append(argv) or subprocess.CompletedProcess(argv, 0, answer, ""))
    check = checks.parse({"kind": kind, "repo": "o/r", "number": 5})
    assert checks.check_github(check).status == expected
    assert seen[0][:2] == ["gh", "api"] and seen[0][2] == ("repos/o/r/pulls/5" if kind == "pr_merged" else "repos/o/r/issues/5")


def test_github_with_no_auth_or_no_gh_reports_unknown_and_never_passes(monkeypatch):
    check = checks.parse({"kind": "issue_closed", "repo": "o/r", "number": 5})
    monkeypatch.setattr(checks, "_run", lambda argv: subprocess.CompletedProcess(argv, 4, "closed\n", "gh: not logged in"))
    assert checks.check_github(check).status == checks.UNKNOWN
    def gone(argv):
        raise FileNotFoundError("gh")
    monkeypatch.setattr(checks, "_run", gone)
    assert checks.check_github(check).status == checks.UNKNOWN


def test_file_exists_and_url_ok_and_session_idle(tmp_path, monkeypatch):
    target = tmp_path / "ready"
    check = checks.parse({"kind": "file_exists", "path": str(target)})
    assert checks.check_file(check).status == checks.FAIL
    target.write_text("x")
    assert checks.check_file(check).status == checks.PASS
    link = tmp_path / "dangling"
    link.symlink_to(tmp_path / "missing")
    assert checks.check_file(checks.parse({"kind": "file_exists", "path": str(link)})).status == checks.FAIL

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200 if self.path == "/up" else 302)
            self.send_header("Location", "http://example.com/")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        assert checks.check_url(checks.parse({"kind": "url_ok", "url": f"http://127.0.0.1:{port}/up"})).status == checks.PASS
        assert checks.check_url(checks.parse({"kind": "url_ok", "url": f"http://127.0.0.1:{port}/redirect"})).status == checks.FAIL
    finally:
        server.shutdown()

    infos = [SimpleNamespace(session=SimpleNamespace(id="ses_1"), activity_status="idle"), SimpleNamespace(session=SimpleNamespace(id="ses_2"), activity_status="working"),
             SimpleNamespace(session=SimpleNamespace(id="ses_3"), activity_status=None)]

    class Ops:
        async def list(self):
            return infos

        async def durable_keys(self, rows):
            return {"ses_1": "u-1"}

    idle = lambda s: asyncio.run(checks.check_session(checks.parse({"kind": "session_idle", "session": s}), Ops())).status  # noqa: E731
    assert (idle("ses_1"), idle("u-1"), idle("ses_2"), idle("ses_3"), idle("ses_9")) == ("pass", "pass", "fail", "unknown", "unknown")


def test_url_ok_refuses_a_non_loopback_host_and_sends_nothing(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("a request left for a host off the allow-list")

    monkeypatch.setattr(checks.urllib.request, "build_opener", forbidden)
    for url in ("https://example.com/health", "http://192.168.1.20/x", "http://localhost.evil.com/x", "http://10.0.0.1:8000/"):
        assert checks.check_url(checks.parse({"kind": "url_ok", "url": url})).status == checks.UNKNOWN
    assert checks.host_allowed("http://127.0.0.1:8000/") and checks.host_allowed("http://[::1]/") and checks.host_allowed("http://localhost:1/")
    assert checks.host_allowed("https://build.example.com/x", ["build.example.com"]) and not checks.host_allowed("https://other.example.com/", ["build.example.com"])



def test_backoff_doubles_from_one_minute_to_thirty():
    assert [waits.backoff_s(n) for n in range(1, 8)] == [60, 120, 240, 480, 960, 1800, 1800]


def test_a_timed_check_runs_with_backoff_is_logged_and_a_pass_clears_the_wait(client, env, tmp_path, monkeypatch):  # noqa: F811
    told = []

    async def tell(ctx, run, key, list_key):
        told.append(key)
        return {"status": "sent"}

    monkeypatch.setattr(unstick, "send_session", tell)
    target = tmp_path / "built"
    item = env.add(client)["id"]
    park(env.store, item, wait_check={"kind": "file_exists", "path": str(target)})
    base = time.time()
    first = wait_runner.WaitRunner(env.ctx, clock=lambda: base)
    with structlog.testing.capture_logs() as logs:
        assert asyncio.run(first.run_checks()) == 1
        assert asyncio.run(first.run_checks()) == 0
    row = wait_row(env.store, item)
    assert row["check_runs"] == 1 and row["check_result"] == "fail" and 59 <= row["check_next_at"] - base <= 61 and env.store.item(item)["state"] == "waiting"
    runs = [entry for entry in logs if entry["event"] == "task_manager_wait_check_run"]
    assert len(runs) == 1 and runs[0]["check"] == "file_exists" and runs[0]["result"] == "fail" and runs[0]["item"] == item
    target.write_text("done")
    assert asyncio.run(wait_runner.WaitRunner(env.ctx, clock=lambda: base + 61).run_checks()) == 1
    cleared = env.store.item(item)
    assert cleared["state"] == "open" and any(m["text"] == f"cleared: {target} exists" for m in cleared["thread"]) and told == ["u-1"]
    assert wait_row(env.store, item)["status"] == "cleared" and wait_row(env.store, item)["token_hash"] == ""


def test_an_unknown_check_never_clears_and_backs_off_like_a_failure(client, env, monkeypatch):  # noqa: F811
    item = env.add(client)["id"]
    park(env.store, item, wait_check={"kind": "issue_closed", "repo": "o/r", "number": 9})
    monkeypatch.setattr(checks, "_run", lambda argv: subprocess.CompletedProcess(argv, 1, "", "no auth"))
    assert asyncio.run(wait_runner.WaitRunner(env.ctx).run_checks()) == 1
    row = wait_row(env.store, item)
    assert row["check_result"] == "unknown" and row["status"] == "active" and env.store.item(item)["state"] == "waiting"


def test_an_event_check_is_not_on_the_timer_and_the_scheduler_sleeps_to_the_next_deadline(client, env):  # noqa: F811
    item = env.add(client)["id"]
    park(env.store, item, wait_check={"kind": "item_state", "item": item + 1, "state": "review"})
    row = wait_row(env.store, item)
    assert row["check_kind"] == "item_state" and row["check_next_at"] is None and asyncio.run(wait_runner.WaitRunner(env.ctx).run_checks()) == 0
    assert abs(waits.WaitStore(env.store).next_due() - row["deadline"]) < 1
    assert asyncio.run(runner_at(env, 0).run_pass(events=False)) == 0
