
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
REAL_SCRIPT = REPO / "scripts" / "web-build-check.sh"
OUTPUTS = ["app.js", "app.css", "style-guide.js", "popout.js", "popout.css", "pair.js", "pair.css",
           "widget-preview.js", "widget-preview.css", "widget-lab/widget-lab.js", "widget-lab/widget-lab.css"]


def _exe(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _repo(tmp_path: Path, outputs: list[str]) -> Path:
    repo = tmp_path / "repo"
    (repo / "web" / "node_modules").mkdir(parents=True)
    for name in outputs:
        out = repo / "client" / "dist" / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("x")
    shutil.copy(REAL_SCRIPT, repo / "scripts_copy.sh")
    (repo / "scripts").mkdir()
    shutil.move(repo / "scripts_copy.sh", repo / "scripts" / "web-build-check.sh")
    _exe(repo / "scripts" / "design" / "check_top_down.sh", "#!/bin/sh\nexit 0\n")
    for cmd in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"]):
        subprocess.run(["git", *cmd], cwd=repo, check=True, capture_output=True)
    return repo


def _run(repo: Path, tmp_path: Path, fail_status: bool, build_creates: list[str]) -> subprocess.CompletedProcess:
    real_git = shutil.which("git")
    bindir = tmp_path / "bin"
    creates = "".join(f'mkdir -p "$(dirname client/dist/{n})"; echo x > client/dist/{n}\n' for n in build_creates)
    _exe(bindir / "npm", f"#!/bin/sh\ncd \"{repo}\"\n{creates}exit 0\n")
    guard = 'if [ "$1" = status ]; then exit 128; fi\n' if fail_status else ""
    _exe(bindir / "git", f'#!/bin/sh\n{guard}exec "{real_git}" "$@"\n')
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", CLOUDE_WEB_CHECK_NO_INSTALL="1")
    return subprocess.run(["bash", str(repo / "scripts" / "web-build-check.sh")], cwd=repo, env=env,
                          capture_output=True, text=True, timeout=60)


def test_green_control_reaches_bundle_current(tmp_path: Path) -> None:
    repo = _repo(tmp_path, OUTPUTS)
    done = _run(repo, tmp_path, fail_status=False, build_creates=[])
    assert done.returncode == 0, done.stdout + done.stderr
    assert "BUNDLE CURRENT" in done.stdout


def test_a_failing_git_status_is_cannot_evaluate_not_a_clean_bundle(tmp_path: Path) -> None:
    repo = _repo(tmp_path, OUTPUTS)
    done = _run(repo, tmp_path, fail_status=True, build_creates=[])
    assert done.returncode == 2, done.stdout + done.stderr
    assert "CANNOT EVALUATE" in done.stderr
    assert "BUNDLE CURRENT" not in done.stdout


def test_a_widget_lab_bundle_the_build_never_emitted_is_named(tmp_path: Path) -> None:
    repo = _repo(tmp_path, [n for n in OUTPUTS if not n.startswith("widget-lab/")])
    done = _run(repo, tmp_path, fail_status=False, build_creates=[])
    assert done.returncode == 2, done.stdout + done.stderr
    assert "widget-lab/widget-lab.js" in done.stderr
