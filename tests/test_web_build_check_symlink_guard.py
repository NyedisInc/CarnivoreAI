import os
import shutil
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_SCRIPT = REPO_ROOT / "scripts" / "web-build-check.sh"


def _build_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "web").mkdir(parents=True)
    (repo / "client" / "dist").mkdir(parents=True)
    dst = repo / "scripts" / "web-build-check.sh"
    shutil.copy(REAL_SCRIPT, dst)
    dst.chmod(dst.stat().st_mode | stat.S_IEXEC)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    return repo


def _fake_npm_bin(tmp_path, call_log):
    bindir = tmp_path / "fakebin"
    bindir.mkdir()
    npm = bindir / "npm"
    npm.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$@" >> "{call_log}"\n'
        "exit 0\n"
    )
    npm.chmod(npm.stat().st_mode | stat.S_IEXEC)
    return bindir


def _run(repo, bindir):
    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    return subprocess.run(
        ["bash", str(repo / "scripts" / "web-build-check.sh")],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_symlinked_node_modules_refused_before_any_npm_call(tmp_path):
    repo = _build_repo(tmp_path)
    real_target = tmp_path / "shared-node-modules"
    real_target.mkdir()
    (repo / "web" / "node_modules").symlink_to(real_target)

    call_log = tmp_path / "npm-calls.log"
    bindir = _fake_npm_bin(tmp_path, call_log)

    result = _run(repo, bindir)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "symlink" in result.stderr.lower()
    logged = call_log.read_text() if call_log.exists() else ""
    assert logged == "", f"npm was invoked despite the symlink guard: {logged!r}"


def test_negative_control_a_real_directory_reaches_npm(tmp_path):
    repo = _build_repo(tmp_path)
    (repo / "web" / "node_modules").mkdir()

    call_log = tmp_path / "npm-calls.log"
    bindir = _fake_npm_bin(tmp_path, call_log)

    _run(repo, bindir)

    assert call_log.exists(), "expected npm to be invoked with a real node_modules dir"
    assert "ci" in call_log.read_text()


def test_web_dir_outside_the_repo_is_refused(tmp_path):
    repo = _build_repo(tmp_path)
    outside = tmp_path / "outside-web"
    outside.mkdir()

    web_link = repo / "web"
    shutil.rmtree(web_link)
    web_link.symlink_to(outside)

    call_log = tmp_path / "npm-calls.log"
    bindir = _fake_npm_bin(tmp_path, call_log)

    result = _run(repo, bindir)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "outside" in result.stderr.lower()
    logged = call_log.read_text() if call_log.exists() else ""
    assert logged == "", f"npm was invoked despite web/ resolving outside the repo: {logged!r}"
