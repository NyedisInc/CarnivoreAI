
from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import textwrap
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_bgw_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_bgw_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core.conversation_writers import read_process_table  # noqa: E402
from src.core.tmux_discovery import tmux_argv_prefix  # noqa: E402

TASK_ID = "btest0001"

AGENT = textwrap.dedent('''
    work="$1"
    mkdir -p "$work/tasks"
    /bin/sh -c 'sleep 600 & wait' > "$work/tasks/%s.output" 2>&1 &
    shell=$!
    sleep 600 &
    keeper=$!
    sleep 0.3
    printf '{"agent": %%d, "shell": %%d, "keeper": %%d}' $$ "$shell" "$keeper" > "$work/info.tmp"
    mv "$work/info.tmp" "$work/info.json"
    wait
''' % TASK_ID)


def _alive(pid: int) -> bool:
    done = subprocess.run(["/bin/ps", "-o", "stat=", "-p", str(pid)],
                          capture_output=True, text=True, check=False)
    state = done.stdout.strip()
    return bool(state) and not state.startswith("Z")


def _start(pid: int) -> str:
    return " ".join(read_process_table().rows[pid].lstart.split())


@pytest.fixture
def pane(tmp_path, tmux_test_socket):
    agent_sh = tmp_path / "agent.sh"
    agent_sh.write_text(AGENT)
    pane_sh = tmp_path / "pane.sh"
    pane_sh.write_text(
        "#!/bin/bash\n"
        f"bash -c 'exec -a claude /bin/bash \"$0\" \"$@\"' '{agent_sh}' '{tmp_path}' &\n"
        "wait\n"
    )
    name = f"bgw_{uuid.uuid4().hex[:8]}"
    prefix = tmux_argv_prefix(tmux_test_socket)
    subprocess.run(prefix + ["-f", "/dev/null", "new-session", "-d", "-s", name,
                             "-x", "80", "-y", "24", f"/bin/bash {pane_sh}"],
                   check=True, capture_output=True, timeout=15)
    info_path = tmp_path / "info.json"
    deadline = time.monotonic() + 15
    while not info_path.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert info_path.exists(), "the stand-in agent never started"
    info = json.loads(info_path.read_text())
    table = read_process_table()
    grandchild = table.children.get(info["shell"], [None])[0]
    assert grandchild is not None and "sleep 600" in table.rows[grandchild].command
    stranger = subprocess.Popen(["/bin/sleep", "600"])
    yield SimpleNamespace(name=name, socket=tmux_test_socket, agent=info["agent"],
                          shell=info["shell"], grandchild=grandchild, stranger=stranger.pid)
    stranger.kill()
    stranger.wait(timeout=5)
    subprocess.run(prefix + ["kill-session", "-t", f"={name}"], capture_output=True, timeout=15)
    for pid in (info["agent"], info["keeper"], info["shell"], grandchild):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


class _Manager:

    def __init__(self, name: str, socket: str) -> None:
        self._name = name
        self._socket = socket

    async def get_session_info(self, session_id=None):
        if session_id != "ses_bgw":
            return None
        return SimpleNamespace(agent_family="claude", tmux_session=self._name, session=None)

    def tmux_socket_name(self) -> str:
        return self._socket

    def claude_uuid_for_tmux_name(self, tmux_name: str):
        return None


def _client(manager):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.auth import require_auth
    from src.api.routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    app.state.session_manager = manager
    return TestClient(app)


def _stop(client, pid: int, start: str):
    return client.post(f"/api/v1/sessions/ses_bgw/background-work/{pid}/terminate",
                       json={"start": start})


def test_refusals_then_the_one_real_stop(pane):
    client = _client(_Manager(pane.name, pane.socket))

    listed = client.get("/api/v1/sessions/ses_bgw/background-work")
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["state"] == "ok"
    rows = {row["pid"]: row for row in body["processes"]}
    assert set(rows) == {pane.shell}, rows
    assert rows[pane.shell]["task_id"] == TASK_ID
    assert rows[pane.shell]["children"] == 1
    assert "sleep 600" in (rows[pane.shell]["summary"] or "")

    refusals = [
        (pane.stranger, _start(pane.stranger), "not_descendant"),
        (pane.agent, _start(pane.agent), "agent_process"),
        (pane.shell, "Thu Jan 1 00:00:00 2026", "start_mismatch"),
        (-1, "Thu Jan 1 00:00:00 2026", "invalid_pid"),
    ]
    pane_pid = int(subprocess.run(
        tmux_argv_prefix(pane.socket) + ["list-panes", "-s", "-t", f"={pane.name}:",
                                         "-F", "#{pane_pid}"],
        capture_output=True, text=True, check=True).stdout.split()[0])
    refusals.append((pane_pid, _start(pane_pid), "pane_process"))
    for pid, start, code in refusals:
        answer = _stop(client, pid, start)
        assert answer.status_code == 403, (pid, code, answer.text)
        assert answer.json()["detail"]["code"] == code, (pid, answer.text)
    for pid in (pane.stranger, pane.agent, pane.shell, pane.grandchild, pane_pid):
        assert _alive(pid), f"pid {pid} was signalled by a refused request"

    answer = _stop(client, pane.shell, rows[pane.shell]["start"])
    assert answer.status_code == 200, answer.text
    result = answer.json()
    assert result["outcome"] == "terminated", result
    assert pane.shell in result["term"] and pane.grandchild in result["term"]
    assert result["survivors"] == []
    assert not _alive(pane.shell) and not _alive(pane.grandchild)
    assert _alive(pane.agent) and _alive(pane.stranger)

    again = _stop(client, pane.shell, rows[pane.shell]["start"])
    assert again.status_code == 200 and again.json()["outcome"] == "already_gone"
