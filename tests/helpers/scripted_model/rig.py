
from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List

from scripts.feature_capture import CaptureError, Slot
from tests import socket_guard
from tests.helpers.scripted_model.anthropic_sse import RIG_MODEL

SLOT_SOCKET_RE = re.compile(r"^cloude-test\d+$")
KEYCHAIN_PREFIX = "Claude Code-credentials"


def keychain_service_names() -> List[str]:
    out = subprocess.run(["security", "dump-keychain"], capture_output=True, text=True,
                         timeout=120, check=True).stdout
    names = re.findall(r'"svce"<blob>="([^"]*)"', out)
    return sorted(n for n in names if n.startswith(KEYCHAIN_PREFIX))


def claude_script(url: str, config_dir: Path) -> str:
    pins = " ".join(f"ANTHROPIC_DEFAULT_{tier}_MODEL={RIG_MODEL}" for tier in ("HAIKU", "SONNET", "OPUS"))
    env = (f"-u ANTHROPIC_API_KEY ANTHROPIC_BASE_URL={shlex.quote(url)} ANTHROPIC_AUTH_TOKEN=rig {pins} "
           f"CLAUDE_CODE_SUBAGENT_MODEL={RIG_MODEL} CLAUDE_CONFIG_DIR={shlex.quote(str(config_dir))} "
           "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 DISABLE_AUTOUPDATER=1")
    return f'rigclaude() {{ env {env} claude --permission-mode default "$@"; }}'


def codex_script(home: Path) -> str:
    return (f'rigcodex() {{ env CODEX_HOME={shlex.quote(str(home))} RIG_KEY=rig '
            'codex --no-daemon -c check_for_update_on_startup=false "$@"; }')


def seed_claude_config(config_dir: Path, work_dir: Path) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / ".claude.json").write_text(json.dumps({
        "hasCompletedOnboarding": True, "theme": "dark",
        "projects": {str(work_dir.resolve()): {"hasTrustDialogAccepted": True}}}))


def seed_codex_home(home: Path, url: str, work_dir: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.toml").write_text(
        f'check_for_update_on_startup = false\nmodel = "{RIG_MODEL}"\nmodel_provider = "rig"\napproval_policy = "on-request"\n'
        'sandbox_mode = "workspace-write"\n\n[model_providers.rig]\nname = "rig"\n'
        f'base_url = "{url}/v1"\nenv_key = "RIG_KEY"\nwire_api = "responses"\n\n'
        f'[projects."{work_dir.resolve()}"]\ntrust_level = "trusted"\n')


class RigSlot:

    def __init__(self, slot: Slot) -> None:
        if not SLOT_SOCKET_RE.match(slot.socket):
            raise CaptureError(f"refusing socket {slot.socket!r}: not a cloude-test<N> slot socket")
        self.slot = slot

    @classmethod
    def lease(cls) -> "RigSlot":
        return cls(Slot.lease())

    def release(self) -> None:
        self.slot.release()

    def register_wrapper(self, wrapper_id: str, family: str, script: str) -> None:
        profile = {"id": wrapper_id, "harness": family, "label": f"rig {family}", "description": "scripted model rig, test only",
                   "custom_command": {"script": script, "entry": wrapper_id}}
        try:
            self.slot.api("POST", "/api/v1/launch-profiles", {"profile": profile})
        except CaptureError as exc:
            if "409" not in str(exc):
                raise
            self.slot.api("PUT", f"/api/v1/launch-profiles/{wrapper_id}", {"profile": profile})

    def create_session(self, name: str, wrapper_id: str, work_dir: Path) -> str:
        made = self.slot.api("POST", "/api/v1/sessions", {
            "project_name": name, "working_dir": str(work_dir.resolve()), "agent_type": wrapper_id,
            "auto_start_claude": True, "copy_templates": False})
        return made["tmux_session"]

    def pin_rail(self) -> None:
        prefs = self.slot.api("GET", "/api/v1/preferences")
        self.slot.api("PATCH", "/api/v1/preferences", {
            "changes": {"widget_bars": {"v": 1, "rail": {"mode": "pinned"}}}, "expected_revision": prefs["revision"]})

    @contextlib.contextmanager
    def _tmux_allowed(self) -> Iterator[None]:
        was = socket_guard.guard_is_installed()
        socket_guard.remove_subprocess_guard()
        try:
            yield
        finally:
            if was:
                socket_guard.install_subprocess_guard()

    def _tmux(self, *args: str) -> str:
        assert SLOT_SOCKET_RE.match(self.slot.socket) and self.slot.socket != "cloude"
        with self._tmux_allowed():
            done = subprocess.run(["tmux", "-L", self.slot.socket, *args], capture_output=True,
                                  text=True, timeout=20)
        if done.returncode != 0:
            raise CaptureError(f"tmux {args[0]} failed: {done.stderr.strip()}")
        return done.stdout

    def capture(self, tmux_name: str) -> str:
        return self._tmux("capture-pane", "-p", "-t", f"={tmux_name}:")

    def type_line(self, tmux_name: str, text: str) -> None:
        self._tmux("send-keys", "-t", f"={tmux_name}:", "-l", text)
        time.sleep(1.0)
        self._tmux("send-keys", "-t", f"={tmux_name}:", "Enter")

    def wait_for(self, tmux_name: str, needle: str, timeout: float = 60.0) -> str:
        deadline = time.monotonic() + timeout
        pane = ""
        while time.monotonic() < deadline:
            pane = self.capture(tmux_name)
            if needle in pane:
                return pane
            time.sleep(1.0)
        raise AssertionError(f"{tmux_name}: {needle!r} never appeared; last pane:\n{pane}")


QUESTIONS_RAIL_BUTTON = '[data-rail-widget="core.questions"]'


def open_questions(page: Any) -> None:
    page.locator(QUESTIONS_RAIL_BUTTON).click(timeout=30000)


def binary_missing(name: str) -> str:
    return "" if shutil.which(name) else f"{name} is not installed on this machine"
