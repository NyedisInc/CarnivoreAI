
from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_int_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_int_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core.tmux_backend import TmuxBackend  # noqa: E402
from src.core.tmux_discovery import tmux_argv_prefix  # noqa: E402

AGENT = textwrap.dedent('''
    work="$1"
    stty raw -echo
    touch "$work/ready"
    head -c 1 > "$work/got.bin"
    exec sleep 600
''')


def _new_session(socket: str, name: str, command: str) -> None:
    subprocess.run(tmux_argv_prefix(socket) + ["-f", "/dev/null", "new-session", "-d",
                                               "-s", name, "-x", "80", "-y", "24", command],
                   check=True, capture_output=True, timeout=15)


@pytest.fixture
def panes(tmp_path, tmux_test_socket):
    agent_sh = tmp_path / "agent.sh"
    agent_sh.write_text(AGENT)
    agent_name = f"int_{uuid.uuid4().hex[:8]}"
    plain_name = f"int_plain_{uuid.uuid4().hex[:8]}"
    _new_session(tmux_test_socket, agent_name,
                 f"bash -c 'exec -a claude /bin/bash \"$0\" \"$1\"' '{agent_sh}' '{tmp_path}'")
    _new_session(tmux_test_socket, plain_name, "/bin/sleep 600")
    deadline = time.monotonic() + 15
    while not (tmp_path / "ready").exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert (tmp_path / "ready").exists(), "the stand-in agent never started"
    time.sleep(0.2)
    yield SimpleNamespace(agent=agent_name, plain=plain_name, socket=tmux_test_socket,
                          got=tmp_path / "got.bin", work=tmp_path)
    for name in (agent_name, plain_name):
        subprocess.run(tmux_argv_prefix(tmux_test_socket) + ["kill-session", "-t", f"={name}"],
                       capture_output=True, timeout=15)


class _Manager:

    def __init__(self, rows: dict, socket: str, work: Path) -> None:
        self._rows = rows
        self._socket = socket
        self._work = work
        self.sent: list = []

    async def get_session_info(self, session_id=None):
        return self._rows.get(session_id)

    def tmux_socket_name(self) -> str:
        return self._socket

    async def send_input(self, data: str, session_id=None) -> bool:
        row = self._rows[session_id]
        backend = TmuxBackend.for_external(row.tmux_session, self._work,
                                           socket_name=self._socket)
        await backend.attach_existing()
        try:
            await backend.write(data.encode("utf-8"))
        finally:
            backend._reader_task.cancel()
        self.sent.append((session_id, data))
        return True


def _row(tmux: str, family: str = "claude", status: str = "working") -> SimpleNamespace:
    return SimpleNamespace(agent_family=family, tmux_session=tmux, activity_status=status,
                           subagents_running=2, background_open=1, session=None)


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


def test_refusals_type_nothing_then_escape_reaches_the_pane(panes):
    rows = {
        "ses_live": _row(panes.agent),
        "ses_shell": _row(panes.agent, family="shell"),
        "ses_dead": _row(panes.agent, status="dead"),
        "ses_plain": _row(panes.plain),
        "ses_gone": _row(f"int_gone_{uuid.uuid4().hex[:8]}"),
    }
    manager = _Manager(rows, panes.socket, panes.work)
    client = _client(manager)

    def interrupt(session_id: str, body=None):
        return client.post(f"/api/v1/sessions/{session_id}/interrupt",
                           json={"confirm": True} if body is None else body)

    assert interrupt("ses_live", {}).status_code == 422
    assert interrupt("ses_live", {"confirm": False}).status_code == 422
    remote = interrupt("remote:studio:" + panes.agent)
    assert remote.status_code == 409 and remote.json()["detail"]["code"] == "remote_host"
    assert interrupt("ses_nobody").status_code == 404
    for session_id, code in (("ses_shell", "not_an_agent"), ("ses_dead", "session_dead"),
                             ("ses_plain", "no_agent_process"), ("ses_gone", "session_gone")):
        answer = interrupt(session_id)
        assert answer.status_code == 409, (session_id, answer.text)
        assert answer.json()["detail"]["code"] == code, (session_id, answer.text)
    time.sleep(0.3)
    assert manager.sent == []
    assert not panes.got.exists() or panes.got.read_bytes() == b"", "a refusal typed into the pane"

    answer = interrupt("ses_live")
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["sent"] is True and body["key"] == "escape"
    assert body["activity_status"] == "working" and body["agent_pid"] > 1
    deadline = time.monotonic() + 5
    while (not panes.got.exists() or not panes.got.read_bytes()) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert panes.got.read_bytes() == b"\x1b"
    assert manager.sent == [("ses_live", "\x1b")]
