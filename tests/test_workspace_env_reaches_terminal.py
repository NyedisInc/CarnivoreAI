
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_wsenv_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_wsenv_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.config import settings
from src.core.session_manager import SessionManager
from src.core.sessions.hook_token_authority import HookTokenAuthority
from src.core.tmux_backend import TmuxBackend
from tests.socket_guard import derive_test_socket

requires_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None, reason="tmux not on PATH"
)


@pytest.fixture
def tmux_socket():
    name = derive_test_socket("wsenv")
    yield name
    tmux = shutil.which("tmux")
    if tmux:
        subprocess.run(
            [tmux, "-L", name, "kill-server"],
            capture_output=True,
            check=False,
        )


@pytest.fixture
def workspace_config(tmp_path, monkeypatch):
    path = tmp_path / "config.json"

    def _write(workspace: dict) -> Path:
        path.write_text(
            json.dumps({"projects": [], "agents": {}, "workspace": workspace})
        )
        settings._auth_config_cache = None
        return path

    monkeypatch.setattr(settings, "auth_config_file", str(path))
    settings._auth_config_cache = None
    yield _write
    settings._auth_config_cache = None


def _spawn_and_capture(socket_name: str, shell_snippet: str, work_dir: Path) -> str:
    out_path = work_dir / f"env-{uuid.uuid4().hex[:8]}.txt"
    manager = SessionManager.__new__(SessionManager)
    manager.hook_tokens = HookTokenAuthority(lambda: work_dir)
    session_id = f"wsenv-{uuid.uuid4().hex[:6]}"
    spawn_env = manager.get_env_for_spawn(session_id)

    backend = TmuxBackend(
        session_id=session_id,
        working_dir=work_dir,
        on_output=None,
        socket_name=socket_name,
    )

    async def _inner():
        await backend.start(
            command=f"/bin/sh -c 'OUT={out_path}; {shell_snippet}; sleep 20'",
            env=spawn_env,
        )

    try:
        asyncio.run(_inner())
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if out_path.exists() and out_path.read_text().strip():
                return out_path.read_text()
            time.sleep(0.2)
    finally:
        asyncio.run(backend.stop())

    raise AssertionError(
        f"the spawned pane never wrote {out_path}, so whether the "
        "environment arrived could not be evaluated. This is not a pass."
    )


@requires_tmux
def test_a_saved_env_var_reaches_a_newly_spawned_terminal(
    tmux_socket, workspace_config, tmp_path
):
    workspace_config({"env": {"CC_E2E_MARKER": "arrived-97531"}})
    captured = _spawn_and_capture(tmux_socket, 'printenv > "$OUT"', tmp_path)
    assert "CC_E2E_MARKER=arrived-97531" in captured


@requires_tmux
def test_the_development_root_reaches_a_newly_spawned_terminal(
    tmux_socket, workspace_config, tmp_path
):
    root = tmp_path / "projects"
    root.mkdir()
    workspace_config({"development_root": str(root)})
    captured = _spawn_and_capture(tmux_socket, 'printenv > "$OUT"', tmp_path)
    assert f"CLOUDE_DEV_ROOT={root}" in captured


@requires_tmux
def test_the_default_shell_is_what_dollar_shell_expands_to_in_the_pane(
    tmux_socket, workspace_config, tmp_path
):
    workspace_config({"default_shell": "/bin/sh"})
    captured = _spawn_and_capture(
        tmux_socket, 'printf "expanded=%s\\n" "$SHELL" > "$OUT"', tmp_path
    )
    assert "expanded=/bin/sh" in captured


@requires_tmux
def test_a_config_cannot_shadow_the_apps_own_control_variables(
    tmux_socket, workspace_config, tmp_path
):
    workspace_config({"env": {"CLOUDECODE_SESSION_ID": "hijacked"}})
    captured = _spawn_and_capture(tmux_socket, 'printenv > "$OUT"', tmp_path)
    assert "CLOUDECODE_SESSION_ID=hijacked" not in captured
    assert "CLOUDECODE_SESSION_ID=wsenv-" in captured


def _value_for(captured: str, name: str) -> str:
    prefix = f"{name}="
    for line in captured.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):]
    raise AssertionError(f"{name} not found in captured environment:\n{captured}")


@requires_tmux
def test_a_spawned_panes_environment_carries_both_spellings(tmux_socket, tmp_path):
    captured = _spawn_and_capture(tmux_socket, 'printenv > "$OUT"', tmp_path)

    for suffix in ("SESSION_ID", "HOOK_TOKEN", "HOOK_URL"):
        legacy_value = _value_for(captured, f"CLOUDECODE_{suffix}")
        current_value = _value_for(captured, f"CARNIVORE_{suffix}")
        assert current_value == legacy_value, (
            f"CARNIVORE_{suffix} ({current_value!r}) does not match "
            f"CLOUDECODE_{suffix} ({legacy_value!r})"
        )


@requires_tmux
def test_a_change_reaches_the_next_terminal_and_not_the_previous_one(
    tmux_socket, workspace_config, tmp_path
):
    workspace_config({"env": {"CC_E2E_PHASE": "first"}})
    before = _spawn_and_capture(tmux_socket, 'printenv > "$OUT"', tmp_path)

    workspace_config({"env": {"CC_E2E_PHASE": "second"}})
    after = _spawn_and_capture(tmux_socket, 'printenv > "$OUT"', tmp_path)

    assert "CC_E2E_PHASE=first" in before
    assert "CC_E2E_PHASE=second" in after
    assert "CC_E2E_PHASE=second" not in before
