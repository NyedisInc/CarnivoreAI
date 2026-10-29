
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from refresh_decision import CouldNotDetermine, classify_paths  # noqa: E402

SCRIPT = str(Path(__file__).resolve().parent.parent / "scripts" / "refresh_decision.py")




def test_client_only_is_hot_sync():
    assert classify_paths(["client/js/app.js", "client/css/styles.css"]) == "hot-sync"


def test_client_dist_is_hot_sync():
    assert classify_paths(["client/dist/app.js", "client/dist/app.css"]) == "hot-sync"


def test_docs_only_is_hot_sync():
    assert classify_paths(["docs/maintenance-history.md", "docs/DECISIONS.md"]) == "hot-sync"


def test_test_or_verify_script_only_is_hot_sync():
    assert (
        classify_paths(
            ["tests/test_refresh_decision.py", "scripts/verify_sidebar_sync.py"]
        )
        == "hot-sync"
    )


def test_mixed_client_docs_and_scripts_is_hot_sync():
    assert (
        classify_paths(
            [
                "client/index.html",
                "docs/ui-inventory.md",
                "scripts/js_syntax_check.py",
                "tests/test_something.py",
                "CLAUDE.md",
            ]
        )
        == "hot-sync"
    )


def test_new_and_deleted_client_paths_are_hot_sync():
    assert classify_paths(["client/js/new-feature.js", "client/js/old-feature.js"]) == "hot-sync"


def test_root_dev_docs_are_hot_sync():
    assert (
        classify_paths(["CLAUDE.md", "AGENTS.md", "TODO.md", "troubleshooting.md"])
        == "hot-sync"
    )


def test_dot_claude_and_dot_github_are_hot_sync():
    assert (
        classify_paths([".claude/skills/work/SKILL.md", ".github/ISSUE_TEMPLATE/task.yml"])
        == "hot-sync"
    )


def test_review_board_design_paths_are_hot_sync():
    assert classify_paths(["design/boards/20261013-bottom-bar/sidecar.json", "design/boards/README.md"]) == "hot-sync"
    assert classify_paths(["design/boards/x/sidecar.json", "src/cplugs/reviewboard/scan.py"]) == "restart"




def test_any_src_path_is_restart():
    assert classify_paths(["src/core/session_manager.py"]) == "restart"


def test_requirements_txt_is_restart():
    assert classify_paths(["requirements.txt"]) == "restart"


def test_requirements_lock_is_restart():
    assert classify_paths(["requirements.lock"]) == "restart"


def test_requirements_dev_txt_is_restart():
    assert classify_paths(["requirements-dev.txt"]) == "restart"


def test_macos_path_is_restart():
    assert classify_paths(["macOS/bootstrap.js"]) == "restart"


@pytest.mark.parametrize(
    "path",
    [
        "config.example.json",
        ".env.example",
        "setup_auth.py",
        "nuke.sh",
        "scripts/session_journal.py",
    ],
)
def test_shipped_root_files_are_restart(path):
    assert classify_paths([path]) == "restart"


def test_mixed_client_and_src_is_restart():
    assert classify_paths(["client/js/app.js", "src/core/session_manager.py"]) == "restart"


def test_mixed_docs_and_requirements_is_restart():
    assert classify_paths(["docs/DECISIONS.md", "requirements.txt"]) == "restart"


def test_unrecognized_top_level_path_defaults_to_restart():
    assert classify_paths(["some_new_top_level_thing/file.txt"]) == "restart"


def test_migration_like_src_subpath_is_restart():
    assert classify_paths(["src/config/config_migration_v6.py"]) == "restart"




def test_empty_path_list_raises_could_not_determine():
    with pytest.raises(CouldNotDetermine):
        classify_paths([])


def test_cli_empty_stdin_exits_2():
    result = subprocess.run(
        [sys.executable, SCRIPT, "classify"],
        input="",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2, result.stderr


def test_cli_client_only_prints_hot_sync_and_exits_0():
    result = subprocess.run(
        [sys.executable, SCRIPT, "classify"],
        input="client/js/app.js\nclient/css/styles.css\n",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "hot-sync"


def test_cli_src_path_prints_restart_and_exits_0():
    result = subprocess.run(
        [sys.executable, SCRIPT, "classify"],
        input="src/core/session_manager.py\n",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "restart"


def test_cli_blank_lines_and_whitespace_are_ignored():
    result = subprocess.run(
        [sys.executable, SCRIPT, "classify"],
        input="\n  \nclient/js/app.js\n\n",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "hot-sync"




def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"})


def test_refresh_refuses_a_checkout_behind_origin(tmp_path):
    origin, clone, other = tmp_path / "o.git", tmp_path / "c", tmp_path / "x"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "master", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True, capture_output=True)
    (clone / "scripts").mkdir()
    (clone / "scripts" / "refresh_decision.py").write_text("")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-qm", "one")
    _git(clone, "push", "-q", "origin", "HEAD:master")
    subprocess.run(["git", "clone", "-q", str(origin), str(other)], check=True, capture_output=True)
    (other / "later").write_text("x")
    _git(other, "add", "-A")
    _git(other, "commit", "-qm", "rebuild generated files")
    _git(other, "push", "-q", "origin", "HEAD:master")
    script = Path(__file__).resolve().parent.parent / "scripts" / "refresh-local-install.sh"
    r = subprocess.run(
        ["bash", str(script), "--repo-root", str(clone), "--server-dir", str(tmp_path / "srv"), "--dry-run"],
        capture_output=True, text=True,
        env={**os.environ, "CLOUDE_TRUNK_REMOTE": "origin"},
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "behind origin/master" in r.stderr



_STALE_NPM_STUB = """#!/bin/bash
# Stand-in for `npm start`: a stale writer puts OLD back into the derived copy
# (the shape of a surviving Electron respawning python), then serves health.
printf OLD > "$STUB_SERVER_DIR/src/marker.py"
echo $$ > "$STUB_PID_FILE"
exec python3 -c '
import http.server, os
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(b"{\\"version\\":\\"9.9.9\\"}")
    def log_message(self, *a): pass
http.server.HTTPServer(("127.0.0.1", int(os.environ["STUB_PORT"])), H).serve_forever()
'
"""


def test_restart_fails_when_the_derived_copy_is_stale_after_restart(tmp_path):
    import json
    import os
    import signal
    import socket

    real = Path(__file__).resolve().parent.parent
    repo, server, binpath = tmp_path / "repo", tmp_path / "server", tmp_path / "bin"
    (repo / "scripts").mkdir(parents=True)
    (repo / "macOS").mkdir()
    (repo / "src").mkdir()
    (server / "src").mkdir(parents=True)
    binpath.mkdir()
    (repo / "macOS" / "engine").mkdir()
    for rel in (
        "scripts/refresh_decision.py",
        "macOS/bootstrap.js",
        "macOS/engine/fs-perms.js",
        "macOS/engine/payload-select.js",
        "macOS/python-lock.js",
    ):
        (repo / rel).write_text((real / rel).read_text())
    (repo / "macOS" / "package.json").write_text(json.dumps({"version": "9.9.9", "dependencies": {}}))
    (repo / "src" / "marker.py").write_text("NEW")
    (server / "src" / "marker.py").write_text("OLD")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "one")
    _git(repo, "checkout", "-q", "--detach")
    npm = binpath / "npm"
    npm.write_text(_STALE_NPM_STUB)
    npm.chmod(0o755)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    pid_file = tmp_path / "stub.pid"
    env = {**os.environ, "PATH": f"{binpath}:{os.environ['PATH']}", "STUB_SERVER_DIR": str(server),
           "STUB_PID_FILE": str(pid_file), "STUB_PORT": str(port),
           "HOTSYNC_TMUX_SOCKET": "never-created-1391", "HOTSYNC_HEALTH_TIMEOUT": "20",
           "HOTSYNC_OLD_GONE_TIMEOUT": "5", "HOTSYNC_POLL_INTERVAL": "1"}
    script = real / "scripts" / "refresh-local-install.sh"
    try:
        r = subprocess.run(
            ["bash", str(script), "--repo-root", str(repo), "--server-dir", str(server), "--port", str(port)],
            capture_output=True, text=True, env=env, timeout=90,
        )
    finally:
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text().strip()), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass
    assert r.returncode == 1, r.stdout + r.stderr
    assert "does not match" in r.stderr, r.stderr
    assert not (server / ".refresh-sha").exists()
