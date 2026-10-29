
from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.approvals.auto_answer.press import AckRefused, route_answer
from src.core.approvals.extract import CHROME_DECLINE_LABEL, extract_dialog
from tests.socket_guard import TEST_SOCKET_NAME

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None or shutil.which("sh") is None, reason="tmux or sh not on PATH")
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "startup_screens" / "chrome_extension.txt"


def _tmux(*args: str) -> str:
    return subprocess.run(["tmux", "-u", "-L", TEST_SOCKET_NAME, *args], capture_output=True, text=True, check=True, timeout=10).stdout


class _Manager:

    def __init__(self, name: str) -> None:
        self.name = name

    def tmux_socket_name(self) -> str:
        return TEST_SOCKET_NAME

    async def get_session_info(self, _sid: str):
        return SimpleNamespace(tmux_session=self.name, session=SimpleNamespace(id="ses_1"), agent_family="claude")

    async def send_input(self, data: str, session_id: str) -> None:
        assert data == "\r", data
        _tmux("send-keys", "-t", f"={self.name}:", "Enter")


def _wait(path: Path, present: bool, seconds: float = 4.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if path.exists() == present:
            return True
        time.sleep(0.1)
    return path.exists() == present


def test_the_seam_presses_a_fresh_fingerprint_and_refuses_a_stale_one(tmp_path: Path) -> None:
    name = "autoanswer_" + uuid.uuid4().hex[:8]
    mark = tmp_path / "pressed"
    _tmux("new-session", "-d", "-s", name, "-x", "120", "-y", "30", f"cat '{FIXTURE}'; IFS= read x; echo got > '{mark}'; sleep 30")
    try:
        time.sleep(0.6)
        manager = _Manager(name)
        answer = route_answer(SimpleNamespace(attention_watcher=None), lambda: manager)
        fresh = extract_dialog(FIXTURE.read_text(), "claude").fingerprint

        with pytest.raises(AckRefused):
            asyncio.run(answer("ses_1", "0" * 64, CHROME_DECLINE_LABEL))
        assert _wait(mark, True, 1.0) is False

        asyncio.run(answer("ses_1", fresh, CHROME_DECLINE_LABEL))
        assert _wait(mark, True)
    finally:
        subprocess.run(["tmux", "-L", TEST_SOCKET_NAME, "kill-session", "-t", f"={name}"], capture_output=True, check=False)
