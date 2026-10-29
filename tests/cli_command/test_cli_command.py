
import os
import stat
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import cli_command_routes
from src.core.cli_command import service


def test_shim_content_quotes_every_path(tmp_path):
    root = tmp_path / "it's here"
    text = service.shim_content(root, "/opt/py thon/bin/python3")
    lines = text.splitlines()
    assert lines[0] == "#!/bin/sh"
    assert "PYTHONPATH='" + str(root).replace("'", "'\"'\"'") in text
    assert "exec '/opt/py thon/bin/python3' -m src.tui \"$@\"" in lines


def test_checkout_command_round_trips_paths_with_spaces():
    import shlex
    cmd = service.checkout_command(Path("/Users/a b/Application Support/server"), "/Users/a b/venv/bin/python3")
    assert shlex.split(cmd) == ["cd", "/Users/a b/Application Support/server", "&&", "/Users/a b/venv/bin/python3", "-m", "src.tui"]
    assert shlex.split(service.status_body(Path("/s"))["run_from_checkout"])[:2] == ["cd", str(service.source_root())]


def test_manual_command_quotes_shim_with_spaces():
    import shlex
    assert shlex.split(service.manual_command(Path("/a b/bin/carnivore")))[-3:-1] == ["-sfn", "/a b/bin/carnivore"]


def test_write_shim_is_atomic_and_executable(tmp_path):
    p = service.write_shim(tmp_path, tmp_path / "root", "/usr/bin/python3")
    assert p == tmp_path / "bin" / "carnivore"
    assert stat.S_IMODE(p.stat().st_mode) == 0o755
    assert not (tmp_path / "bin" / "carnivore.tmp").exists()


def test_four_states(tmp_path):
    shim = tmp_path / "state" / "bin" / "carnivore"
    shim.parent.mkdir(parents=True)
    shim.write_text("x")
    link = str(tmp_path / "carnivore")
    assert service.link_state(shim, link) == "missing"
    os.symlink(str(shim), link)
    assert service.link_state(shim, link) == "installed"
    os.unlink(link)
    old = tmp_path / "Carnivore Menubar" / "bin" / "carnivore"
    old.parent.mkdir(parents=True)
    old.write_text("x")
    os.symlink(str(old), link)
    assert service.link_state(shim, link) == "stale"
    os.unlink(link)
    os.symlink(str(tmp_path / "gone"), link)
    assert service.link_state(shim, link) == "stale"
    os.unlink(link)
    other = tmp_path / "other"
    other.write_text("x")
    os.symlink(str(other), link)
    assert service.link_state(shim, link) == "foreign"
    os.unlink(link)
    Path(link).write_text("a regular file")
    assert service.link_state(shim, link) == "foreign"


def test_privileged_command_only_quoted_fixed_paths(tmp_path):
    shim = tmp_path / "it's" / "bin" / "carnivore"
    cmd = service.privileged_command(shim)
    assert cmd == "/bin/mkdir -p /usr/local/bin && /bin/ln -sfn '" + str(shim).replace("'", "'\"'\"'") + "' /usr/local/bin/carnivore"
    script = service.apple_script(cmd)
    assert script.startswith('do shell script "') and script.endswith('" with administrator privileges')


def _unwritable(monkeypatch):
    monkeypatch.setattr(service.os, "access", lambda *a, **k: False)


def test_foreign_is_refused(tmp_path):
    link = tmp_path / "carnivore"
    link.write_text("mine")
    calls = []
    r = service.install(tmp_path / "s", str(link), runner=lambda *a: calls.append(a) or (0, ""))
    assert r["outcome"] == "foreign" and r["state"] == "foreign"
    assert link.read_text() == "mine" and not calls


def test_direct_link_when_writable_and_already_installed(tmp_path):
    link = str(tmp_path / "carnivore")
    r = service.install(tmp_path / "s", link, runner=lambda *a: pytest.fail("no prompt expected"))
    assert r["outcome"] == "installed" and r["state"] == "installed"
    assert service.install(tmp_path / "s", link)["outcome"] == "already_installed"


def test_cancel_timeout_and_success_map(tmp_path, monkeypatch):
    _unwritable(monkeypatch)
    link = str(tmp_path / "carnivore")
    seen = []

    def cancel(script, timeout):
        seen.append((script, timeout))
        return 1, "execution error: User canceled. (-128)"

    assert service.install(tmp_path / "s", link, runner=cancel)["outcome"] == "cancelled"
    assert seen[0][1] == 120

    def slow(script, timeout):
        raise subprocess.TimeoutExpired("osascript", timeout)

    assert service.install(tmp_path / "s", link, runner=slow)["outcome"] == "timed_out"
    assert service.install(tmp_path / "s", link, runner=lambda s, t: (1, "boom"))["outcome"] == "failed"
    assert service.install(tmp_path / "s", link, runner=lambda s, t: (0, ""))["outcome"] == "installed"


def test_routes_refuse_unauthenticated():
    app = FastAPI()
    app.include_router(cli_command_routes.router, prefix="/api/v1")
    c = TestClient(app)
    assert c.get("/api/v1/cli-command").status_code in (401, 403)
    assert c.post("/api/v1/cli-command/install").status_code in (401, 403)


def test_status_body_shape(tmp_path):
    b = service.status_body(tmp_path, str(tmp_path / "carnivore"))
    assert set(b) == {"state", "command", "link_path", "shim_path", "manual_command", "run_from_checkout"}
    assert b["state"] == "missing" and b["command"] == "carnivore tui"
