from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_swsub_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_swsub_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.core import tmux_one_shot as t
from src.core.tmux_backend import SESSION_PREFIX, TmuxBackend
from tests import socket_guard

STAND_IN = r'''
import os, re, sys, time, tty, termios, select
log = sys.argv[1]
fd = sys.stdin.fileno()
tty.setraw(fd)
out = sys.stdout
W = "─" * 60
busy = len(sys.argv) > 2 and sys.argv[2] == "busy"  # mid-turn: Enter queues the text and the box keeps showing it
state = {"raw": "", "box": "", "frozen_until": 0.0, "pasted": 0, "queued": []}
def draw():
    out.write("\x1b[2J\x1b[H" + "stand-in\r\n" + "".join("queued: %s\r\n" % q for q in state["queued"]) + W + " agent ─\r\n")
    out.write("❯ " + state["box"].replace("\n", "\r\n") + "\r\n" + W + "\r\nfooter\r\n")
    out.flush()
out.write("\x1b[?2004h"); draw()
buf = ""
while True:
    now = time.monotonic()
    if state["raw"] and now >= state["frozen_until"]:  # conversion done: collapse to the placeholder
        n = state["raw"].count("\n") + 1
        state["pasted"] += 1
        state["box"] = "[Pasted text #%d +%d lines]" % (state["pasted"] * 20, n)
        state["collapsed"] = state["raw"]; state["raw"] = ""
        draw()
    if select.select([fd], [], [], 0.05)[0]:
        buf += os.read(fd, 65536).decode("utf-8", "replace")
    while buf:
        if buf.startswith("\x1b[200~"):
            if "\x1b[201~" not in buf: break
            body, buf = buf[6:].split("\x1b[201~", 1)
            state["raw"] = body
            state.setdefault("all", []).append(body)
            state["box"] = body; state["frozen_until"] = time.monotonic() + 1.5
            draw()
        elif buf[0] == "\r":
            buf = buf[1:]
            if time.monotonic() < state["frozen_until"] or not state["all"]:
                continue  # swallowed while converting
            with open(log, "a") as f:
                f.write("SUBMIT copies=%d\n" % len(state["all"]) + "".join("BODY:%s\n" % b.replace("\n", "|") for b in state["all"]))
            if busy:
                state["queued"].append(state["all"][-1].strip().splitlines()[-1][-60:])
            else:
                state["box"] = ""
            state["all"] = []; state["raw"] = ""
            draw()
        else:
            buf = buf[1:]
'''


def _lines(n: int) -> str:
    return "\n".join(f"line {i} " + "x" * 200 for i in range(n))


@pytest.fixture
def sock():
    name = socket_guard.derive_test_socket("swsub")
    yield name
    if shutil.which("tmux"):
        os.system(f"{shutil.which('tmux')} -L {name} kill-server >/dev/null 2>&1")


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not on PATH")
def test_long_multiline_message_submits_once_and_second_delivers(sock, tmp_path):
    _run(sock, tmp_path, [])


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not on PATH")
def test_message_to_a_busy_agent_is_reported_delivered_once(sock, tmp_path):
    _run(sock, tmp_path, ["busy"])


def _run(sock, tmp_path, extra):
    name = f"{SESSION_PREFIX}swsub"
    script, log = tmp_path / "standin.py", tmp_path / "log.txt"
    script.write_text(STAND_IN)
    backend = TmuxBackend.for_external(session_name=name, working_dir=Path(tempfile.gettempdir()),
                                       on_output=None, socket_name=sock)
    rc, _, err = backend._run_tmux_sync("new-session", "-d", "-s", name, "-x", "120", "-y", "40",
                                        sys.executable, str(script), str(log), *extra, check=False)
    assert rc == 0, err
    time.sleep(0.8)
    first, second = _lines(8) + "\nfooter-one", "second message here"
    assert len(first) > 1000 and first.count("\n") > 5

    async def go():
        await t.paste_and_submit(backend, first)
        await t.paste_and_submit(backend, second)

    asyncio.run(go())
    time.sleep(0.3)
    text = log.read_text()
    submits = [ln for ln in text.splitlines() if ln.startswith("SUBMIT")]
    assert submits == ["SUBMIT copies=1", "SUBMIT copies=1"], text
    assert text.count("footer-one") == 1 and text.count("second message here") == 1
