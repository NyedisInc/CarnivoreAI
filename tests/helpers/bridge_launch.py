
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from src.config import settings
from src.core.config_migration import migrate_config_file

UUID = "439ac4a6-7ef4-4386-8b6b-1b838712cf87"
PORT = 8123

CONFIG = {
    "config_version": 5,
    "projects": [],
    "mcp": {"enabled": True, "channels": True},
    "agents": {
        "wrappers": [
            {"id": "keyc", "family": "claude", "label": "keyc",
             "script": 'claude "$@"', "default": True, "accepts_model": False},
        ],
    },
}


def use_bridge_config(tmp_path: Path, monkeypatch) -> Path:
    config = tmp_path / "config.json"
    config.write_text(json.dumps(CONFIG, indent=2))
    assert migrate_config_file(config)["migrated"] is True
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(settings, "auth_config_file", str(config))
    monkeypatch.setattr(settings, "state_dir_override", str(state))
    monkeypatch.setattr(settings, "_auth_config_cache", None)
    monkeypatch.setattr(settings, "port", PORT)
    settings.ensure_wrapper_defaults()
    return tmp_path


def argv_of(command: str, tmp_path: Path) -> list:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    record = tmp_path / "argv-claude.txt"
    fake = fake_bin / "claude"
    fake.write_text(f"#!/bin/sh\n: > '{record}'\nfor a in \"$@\"; do printf '%s\\n' \"$a\" >> '{record}'; done\n")
    fake.chmod(0o755)
    subprocess.run(["/bin/sh", "-c", command], check=True, timeout=30,
                   env={"HOME": str(tmp_path), "PATH": f"{fake_bin}:/usr/bin:/bin"})
    return record.read_text().splitlines()


def assert_bridge(argv: list, *, resumed: bool = True) -> None:
    configs = [a for a in argv if a.startswith("--mcp-config={")]
    assert configs, f"no inline carnivore registration on the command line: {argv!r}"
    server = json.loads(configs[0].split("=", 1)[1])["mcpServers"]["carnivore"]
    assert server["type"] == "stdio" and server["args"][0].endswith("src/core/mcp_bridge/stdio_bridge.py")
    assert server["env"]["CLOUDECODE_HOOK_TOKEN"] == "${CLOUDECODE_HOOK_TOKEN}", "a secret value reached argv"
    assert "--dangerously-load-development-channels=server:carnivore" in argv
    if resumed:
        assert argv.count("--resume") == 1 and argv[argv.index("--resume") + 1] == UUID, argv


def capture_commands(monkeypatch, run_instead: str = "sleep 45") -> list:
    real = type(settings).get_agent_command
    seen: list = []

    def capture(self, agent_type, *args, **kwargs):
        seen.append((agent_type, real(self, agent_type, *args, **kwargs)))
        return run_instead

    monkeypatch.setattr(type(settings), "get_agent_command", capture)
    return seen


def tmux(socket: str, *args: str) -> str:
    return subprocess.run(["tmux", "-L", socket, *args], capture_output=True, text=True, check=True).stdout


def seed_row(state: Path, socket: str, name: str, epoch: int, *, lifecycle_source: str = "") -> str:
    from contextlib import closing

    from src.core.db import connect, db_path_for
    from src.core.db_migration import ensure_db_migrated
    from src.core.db_models import SESSION_ORIGIN_OBSERVED
    from src.core.session_identity import record_instance

    ensure_db_migrated(state, 4, "0.8.2")
    with closing(connect(db_path_for(state))) as conn:
        record_instance(conn, socket=socket, name=name, epoch=epoch, origin=SESSION_ORIGIN_OBSERVED)
        conn.execute("UPDATE sessions SET claude_session_uuid = ?, agent_type = 'keyc' WHERE tmux_name = ?", (UUID, name))
        if lifecycle_source:
            conn.execute("UPDATE sessions SET lifecycle = 'stopped', lifecycle_source = ? WHERE tmux_name = ?",
                         (lifecycle_source, name))
        conn.commit()
        return str(conn.execute("SELECT session_uuid FROM sessions WHERE tmux_name = ?", (name,)).fetchone()[0])


def pane(socket: str, name: str, command: str, *, dead: bool) -> int:
    tmux(socket, "new-session", "-d", "-s", name, "-x", "80", "-y", "24", command,
         ";", "set-option", "-w", "remain-on-exit", "on")
    epoch = int(tmux(socket, "display-message", "-p", "-t", f"={name}:", "#{session_created}").strip())
    deadline = time.monotonic() + 6
    while dead and time.monotonic() < deadline:
        if tmux(socket, "display-message", "-p", "-t", f"={name}:", "#{pane_dead}").strip() == "1":
            break
        time.sleep(0.1)
    return epoch


def unchecked_transcripts(monkeypatch) -> None:
    from src.core.session_transcript_presence import CONVERSATION_UNCHECKED, ConversationPresence

    monkeypatch.setattr("src.core.session_transcript_presence.conversation_presence",
                        lambda *a, **k: ConversationPresence(outcome=CONVERSATION_UNCHECKED, detail="test"))
