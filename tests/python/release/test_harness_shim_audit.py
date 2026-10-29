
from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import sys
import warnings
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SHIMMED = ("tccutil", "sfltool", "launchctl", "open", "osascript", "pkill", "killall")
TMUX_SHIM = "tmux"
VALIDATION_PORTS = (8101, 8102, 8103, 8104, 8105)

PYTHON_AUDITED = (
    "tests/test_nuke_sandbox.py",
    "tests/python/release/test_uninstall_contract.py",
)
NODE_AUDITED = (
    "tests/test_launchagent_installer.node.mjs",
    "tests/test_terminal_launcher.node.mjs",
    "tests/node/test_tray_uninstall.node.mjs",
    "tests/node/test_engine_host.node.mjs",
)
SCRIPTS_WITHOUT_ABSOLUTE_SYSTEM_PATHS = ("nuke.sh", "uninstall.sh")
ABSOLUTE = re.compile(r"/(?:usr/bin|bin|usr/sbin|sbin)/(?:tccutil|sfltool|launchctl|open|osascript|pkill|killall)\b")


def _shim_env(tmp_path: Path) -> tuple[dict[str, str], Path]:
    shims = tmp_path / "shims"
    shims.mkdir()
    tmux_shims = tmp_path / "shims-tmux"
    tmux_shims.mkdir()
    log = tmp_path / "shim.log"
    log.write_text("")
    for name in (*SHIMMED, TMUX_SHIM):
        shim = (tmux_shims if name == TMUX_SHIM else shims) / name
        real = shutil.which("tmux") if name == TMUX_SHIM else None
        passthrough = f'case "$*" in *"-L cloude_pytest_"*) exec "{real}" "$@" ;; esac\n' if real else ""
        shim.write_text(f'#!/bin/bash\n{passthrough}printf \'%s\' "{name}" >> "{log}"\nfor a in "$@"; do printf \' %q\' "$a" >> "{log}"; done\nprintf \'\\n\' >> "{log}"\nexit 1\n')
        shim.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLOUDE_NUKE", "CARNIVORE_"))}
    env.update(PATH=f"{shims}{os.pathsep}{tmux_shims}{os.pathsep}{os.environ['PATH']}", AUDIT_SHIM_DIR=str(shims), HOME=str(home), TMPDIR=str(tmp_path))
    return env, log


def _main_checkout() -> Path:
    proc = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    common = Path(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip() else None
    return common.parent if common is not None and common.name == ".git" else REPO_ROOT


def _listeners_on(port: str) -> set[str]:
    proc = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True, check=False)
    return set(proc.stdout.split())


def _live_snapshot() -> dict[str, set[str]]:
    main = _main_checkout()
    port = "8000"
    env_file = main / ".env"
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            if line.startswith("PORT=") and line[5:].strip().strip("'\"").isdigit():
                port = line[5:].strip().strip("'\"")
    snap = {f"listener:{p}": _listeners_on(p) for p in (port, *map(str, VALIDATION_PORTS))}
    electron = re.escape(f"{main}/macOS/node_modules/electron/dist/Electron.app/Contents/")
    snap["electron"] = set(subprocess.run(["pgrep", "-f", f"^{electron}"], capture_output=True, text=True, check=False).stdout.split())
    socket = Path(f"/private/tmp/tmux-{os.getuid()}/cloude")
    holders = subprocess.run(["lsof", "-nP", "-t", str(socket)], capture_output=True, text=True, check=False).stdout if socket.exists() else ""
    snap["tmux:cloude server"] = set(holders.split())
    return snap


@contextlib.contextmanager
def _live_listener_unchanged(rel: str, record_property) -> Iterator[None]:
    before = _live_snapshot()
    yield
    if not any(before.values()):
        warnings.warn(f"{rel}: NOTHING WAS MEASURED, no engine, validation server, dev Electron or cloude tmux server was running before the run", stacklevel=2)
        record_property("live_snapshot", "not measured: nothing was running before the run")
        return
    after = _live_snapshot()
    lost = {label: sorted(pids - after[label]) for label, pids in before.items() if pids - after[label]}
    assert not lost, f"{rel} ended something that was running: {lost}"


def test_the_live_snapshot_check_goes_red_and_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    snaps = iter([{"listener:8000": {"1"}, "electron": {"2"}}, {"listener:8000": {"1"}, "electron": set()}])
    monkeypatch.setattr(sys.modules[__name__], "_live_snapshot", lambda: next(snaps))
    with pytest.raises(AssertionError, match="electron"):
        with _live_listener_unchanged("probe", lambda *a: None):
            pass
    monkeypatch.setattr(sys.modules[__name__], "_live_snapshot", lambda: {"listener:8000": set()})
    with pytest.warns(UserWarning, match="NOTHING WAS MEASURED"):
        with _live_listener_unchanged("probe", lambda *a: None):
            pass


def _run(argv: list[str], env: dict[str, str], cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True, timeout=300, check=False)


def test_the_shims_record_a_call(tmp_path: Path) -> None:
    env, log = _shim_env(tmp_path)
    _run(["launchctl", "list", "canary"], env)
    assert log.read_text().strip() == "launchctl list canary"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed: the node half of the audit did not run")
def test_the_audit_flags_a_test_that_reaches_a_system_binary(tmp_path: Path) -> None:
    env, log = _shim_env(tmp_path)
    probe = tmp_path / "probe.node.mjs"
    probe.write_text("import { execFileSync } from 'node:child_process';\ntry { execFileSync('launchctl', ['list', 'x']); } catch (e) { /* the shim exits 1 */ }\n")
    _run(["node", str(probe)], env)
    assert "launchctl list x" in log.read_text()


@pytest.mark.parametrize("rel", PYTHON_AUDITED)
def test_python_suspects_never_reach_a_system_binary(rel: str, tmp_path: Path, record_property) -> None:
    env, log = _shim_env(tmp_path)
    with _live_listener_unchanged(rel, record_property):
        proc = _run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", rel], env)
    assert log.read_text() == "", f"{rel} reached a system binary:\n{log.read_text()}"
    assert proc.returncode == 0, f"{rel} failed under shims (it depended on a real system binary?):\n{proc.stdout[-2000:]}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed: the node half of the audit did not run")
@pytest.mark.parametrize("rel", NODE_AUDITED)
def test_node_suspects_never_reach_a_system_binary(rel: str, tmp_path: Path, record_property) -> None:
    env, log = _shim_env(tmp_path)
    with _live_listener_unchanged(rel, record_property):
        proc = _run(["node", "--test", rel], env)
    assert log.read_text() == "", f"{rel} reached a system binary:\n{log.read_text()}"
    assert proc.returncode == 0, f"{rel} failed under shims (it depended on a real system binary?):\n{proc.stdout[-2000:]}"


@pytest.mark.parametrize("rel", SCRIPTS_WITHOUT_ABSOLUTE_SYSTEM_PATHS)
def test_no_script_names_a_system_binary_by_absolute_path(rel: str) -> None:
    text = (REPO_ROOT / rel).read_text()
    assert ABSOLUTE.findall(text) == [], f"{rel} bypasses PATH with an absolute system binary path"
