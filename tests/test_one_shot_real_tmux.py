
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ost_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ost_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core import tmux_one_shot
from src.core.session_one_shot_gate import (
    PANE_DIALOG_OPEN,
    PANE_NOT_AN_AGENT,
    OneShotRefused,
    check_can_paste,
    pane_command_is_agent,
)
from src.core.session_startup_gate import GATE_READY
from src.core.session_status import STATUS_IDLE, STATUS_QUESTION
from src.core.tmux_backend import SESSION_PREFIX, TmuxBackend
from src.core.tmux_one_shot import PasteNotSettledError

from tests import socket_guard

requires_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not on PATH"
)

AGENT_PANE = f"{SESSION_PREFIX}one_shot_agent"
SHELL_PANE = f"{SESSION_PREFIX}one_shot_shell"
SILENT_PANE = f"{SESSION_PREFIX}one_shot_silent"
CODEX_PANE = f"{SESSION_PREFIX}one_shot_codex"

GHOST_PANE = f"{SESSION_PREFIX}one_shot_ghost"

BODY = "alphaone\nbravotwo\ncharliethree"

READ_LOOP = 'while IFS= read -r l; do printf "GOT<%s>\\n" "$l"; done'


@pytest.fixture
def tmux_socket():
    name = socket_guard.derive_test_socket("oneshot")
    yield name
    tmux = shutil.which("tmux")
    if tmux:
        os.system(f"{tmux} -L {name} kill-server >/dev/null 2>&1")


def _backend(name: str, socket_name: str) -> TmuxBackend:
    return TmuxBackend.for_external(
        session_name=name,
        working_dir=Path(tempfile.gettempdir()),
        on_output=None,
        socket_name=socket_name,
    )


def _spawn(backend: TmuxBackend, name: str, *command: str) -> None:
    rc, _, err = backend._run_tmux_sync(
        "new-session", "-d", "-s", name, "-x", "120", "-y", "40", *command,
        check=False,
    )
    assert rc == 0, err.decode("utf-8", errors="replace")


def _capture(backend: TmuxBackend, name: str) -> str:
    rc, out, _ = backend._run_tmux_sync(
        "capture-pane", "-p", "-t", name, check=False
    )
    return out.decode("utf-8", errors="replace") if rc == 0 else ""


def _wait_for_pane(backend: TmuxBackend, name: str, wanted: str) -> str:
    last = ""
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        rc, out, _ = backend._run_tmux_sync(
            "display", "-p", "-t", name, "#{pane_current_command}", check=False
        )
        last = out.decode("utf-8", errors="replace").strip() if rc == 0 else ""
        if pane_command_is_agent(last):
            return last
        time.sleep(0.25)
    return last


def _settle_markers(backend: TmuxBackend, name: str) -> str:
    previous = None
    stable_reads = 0
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        current = _capture(backend, name)
        if current == previous:
            stable_reads += 1
            if stable_reads >= 3:
                return current
        else:
            stable_reads = 0
        previous = current
        time.sleep(0.1)
    return previous or ""




@requires_tmux
def test_a_three_line_body_arrives_as_three_lines_and_exactly_one_enter(
    tmux_socket,
):
    backend = _backend(AGENT_PANE, tmux_socket)
    _spawn(backend, AGENT_PANE, "sh", "-c", READ_LOOP)

    ready = False
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        rc, out, _ = backend._run_tmux_sync(
            "display", "-p", "-t", AGENT_PANE, "#{pane_dead}", check=False
        )
        if rc == 0 and out.decode().strip() == "0":
            ready = True
            break
        time.sleep(0.2)
    assert ready, "the stand-in pane never came up alive"

    asyncio.run(tmux_one_shot.paste_and_submit(backend, BODY))

    screen = _settle_markers(backend, AGENT_PANE)
    assert "GOT<alphaone>" in screen, screen
    assert "GOT<bravotwo>" in screen, screen
    assert "GOT<charliethree>" in screen, (
        "the final line never completed, so the single Enter never arrived:\n"
        + screen
    )
    assert "GOT<>" not in screen, (
        "an EMPTY line was submitted, which means more than one Enter was "
        "sent:\n" + screen
    )
    assert screen.count("GOT<") == 3, (
        f"expected exactly three submitted lines, got {screen.count('GOT<')}:\n"
        + screen
    )


@requires_tmux
def test_a_pane_that_never_changes_gets_no_enter_at_all(tmux_socket):
    backend = _backend(SILENT_PANE, tmux_socket)
    _spawn(backend, SILENT_PANE, "sh", "-c", "stty -echo; cat > /dev/null")
    time.sleep(1.0)

    before = _capture(backend, SILENT_PANE)
    with pytest.raises(PasteNotSettledError):
        asyncio.run(tmux_one_shot.paste_and_submit(backend, BODY))
    assert _capture(backend, SILENT_PANE) == before, (
        "the pane changed after all, so this test no longer exercises the "
        "timeout it was written for"
    )


@requires_tmux
def test_a_pane_that_cannot_be_captured_before_the_paste_gets_nothing(tmux_socket):
    live = _backend(AGENT_PANE, tmux_socket)
    _spawn(live, AGENT_PANE, "sh", "-c", READ_LOOP)

    ghost = _backend(GHOST_PANE, tmux_socket)
    calls = []
    real_run = ghost._run_tmux

    async def recording(*args, **kwargs):
        rc, out, err = await real_run(*args, **kwargs)
        calls.append((args[0] if args else "", rc))
        return (rc, out, err)

    ghost._run_tmux = recording

    with pytest.raises(PasteNotSettledError):
        asyncio.run(tmux_one_shot.paste_and_submit(ghost, BODY))

    assert calls, "no tmux command ran at all, so this test proves nothing"
    assert calls[0][0] == "capture-pane", (
        f"the first command was {calls[0][0]!r}; the pre-paste capture is "
        "supposed to come before anything else"
    )
    assert calls[0][1] != 0, (
        "the capture SUCCEEDED against a session that was never created, so "
        "this test no longer exercises the unreadable pane it was written for"
    )
    assert not any(name == "load-buffer" for name, _ in calls), (
        f"a body was loaded into a buffer after an unmeasurable pane: {calls}"
    )
    assert not any(name == "send-keys" for name, _ in calls), (
        f"an Enter was sent into a pane that could not be read at all: {calls}"
    )




class _SerialisationProbe:

    def __init__(self, name: str) -> None:
        self.tmux_session = name
        self.slug = name
        self.log = []
        self._captures = 0
        self._in_flight = None

    async def _run_tmux(self, *args, check=True, **kwargs):
        self._captures += 1
        return (0, f"screen {self._captures}".encode(), b"")

    async def _write_via_paste_buffer(
        self, data: bytes, *, bracketed: bool = False
    ) -> None:
        body = data.decode("utf-8")
        self._in_flight = body
        self.log.append(("paste", body))
        await asyncio.sleep(0.02)

    async def _write_via_hex_keys(self, data: bytes) -> None:
        self.log.append(("enter", self._in_flight))


def test_two_one_shots_on_one_pane_are_serialised_not_interleaved():

    async def drive():
        probe = _SerialisationProbe(f"{SESSION_PREFIX}one_shot_serial")
        await asyncio.gather(
            tmux_one_shot.paste_and_submit(probe, "first body"),
            tmux_one_shot.paste_and_submit(probe, "second body"),
        )
        return probe.log

    log = asyncio.run(drive())

    assert len(log) == 4, log
    assert [kind for kind, _ in log] == ["paste", "enter", "paste", "enter"], (
        "the two one-shots interleaved, so both bodies were in the pane's one "
        f"shared paste buffer at the same time: {log}"
    )
    assert log[0][1] == log[1][1], log
    assert log[2][1] == log[3][1], log
    assert {log[0][1], log[2][1]} == {"first body", "second body"}, log




@requires_tmux
def test_a_real_shell_pane_is_refused_pane_not_an_agent(tmux_socket):
    backend = _backend(SHELL_PANE, tmux_socket)
    _spawn(backend, SHELL_PANE, "sh", "-c", "exec sh -i")
    time.sleep(1.0)

    row = next(
        (r for r in backend.list_pane_status_all().sessions
         if r["name"] == SHELL_PANE),
        None,
    )
    assert row is not None, "the shell pane is not in the live listing"
    assert row["pane_current_command"] in ("sh", "zsh", "bash"), (
        f"tmux reported {row['pane_current_command']!r} for a bare shell, so "
        "KNOWN_SHELL_COMMANDS no longer covers what a shell pane reports"
    )

    before = _capture(backend, SHELL_PANE)
    with pytest.raises(OneShotRefused) as caught:
        check_can_paste(
            pane_current_command=row["pane_current_command"],
            pane_dead=row["pane_dead"],
            agent_type="claude",
            activity_status=STATUS_IDLE,
            startup_gate=GATE_READY,
        )
    assert caught.value.code == PANE_NOT_AN_AGENT
    assert _capture(backend, SHELL_PANE) == before, "something reached the pane"


@requires_tmux
def test_a_session_waiting_on_the_user_refuses_a_real_agent_pane(tmux_socket):
    backend = _backend(AGENT_PANE, tmux_socket)
    _spawn(backend, AGENT_PANE, "sh", "-c", READ_LOOP)
    time.sleep(1.0)

    row = next(
        (r for r in backend.list_pane_status_all().sessions
         if r["name"] == AGENT_PANE),
        None,
    )
    assert row is not None, "the stand-in pane is not in the live listing"

    before = _capture(backend, AGENT_PANE)
    with pytest.raises(OneShotRefused) as caught:
        check_can_paste(
            pane_current_command="2.1.266",
            pane_dead=row["pane_dead"],
            agent_type="claude",
            activity_status=STATUS_QUESTION,
            startup_gate=GATE_READY,
        )
    assert caught.value.code == PANE_DIALOG_OPEN
    assert _capture(backend, AGENT_PANE) == before, "something reached the pane"


@requires_tmux
@pytest.mark.skipif(
    shutil.which("codex") is None, reason="codex not installed on this machine"
)
def test_a_real_codex_pane_reports_a_command_the_gate_accepts(tmux_socket):
    backend = _backend(CODEX_PANE, tmux_socket)
    _spawn(backend, CODEX_PANE, shutil.which("codex"))
    command = _wait_for_pane(backend, CODEX_PANE, "codex")

    assert command, "the codex pane never reported a current command"
    assert pane_command_is_agent(command) is True, (
        f"a live codex pane reported {command!r}, which the gate classifies "
        "as a shell - the one-shot gate would now refuse every Codex session"
    )
