from __future__ import annotations

import json
import shlex
from pathlib import Path

from src.config.launch_profiles import LaunchProfile
from src.core.cli_command import service
from src.core.computers import terminal_helper
from src.core.launch_profiles.render import render_structured
from src.core.desktop_app.payload_bytecode import bytecode_flags

ROOT = Path(__file__).resolve().parents[3]


def test_flags_follow_the_engine_variables() -> None:
    assert bytecode_flags({"PYTHONPYCACHEPREFIX": "/c d"}) == ["-X", "pycache_prefix=/c d"]
    assert bytecode_flags({"PYTHONDONTWRITEBYTECODE": "1"}) == ["-B"]
    assert bytecode_flags({"PYTHONPYCACHEPREFIX": "/c", "PYTHONDONTWRITEBYTECODE": "1"}) == ["-X", "pycache_prefix=/c"]
    assert bytecode_flags({}) == []


def test_join_helper_command_carries_the_flags_before_dash_i() -> None:
    text = terminal_helper.command_text("/p/python3", "/srv", "/door", ["-X", "pycache_prefix=/c d"])
    assert "exec '/p/python3' '-X' 'pycache_prefix=/c d' -I -c " in text


def test_cli_shim_carries_the_flags(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PYTHONPYCACHEPREFIX", "/c d")
    shim = service.write_shim(tmp_path, root=tmp_path / "srv", python="/p/python3").read_text()
    assert "exec /p/python3 -X 'pycache_prefix=/c d' -m src.tui \"$@\"" in shim.splitlines()
    assert "-X 'pycache_prefix=/c d' -m src.tui" in service.checkout_command(tmp_path, "/p/python3")


def test_codex_supervisor_command_carries_the_flags(monkeypatch) -> None:
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    monkeypatch.delenv("PYTHONPYCACHEPREFIX", raising=False)
    profile = LaunchProfile(id="cx", harness="codex", label="cx")
    command = render_structured(profile, "m", ["--no-alt-screen"], False, extra_flags=["-c", "a=1"],
                                codex_server_args=["-c", "b=2"])
    script = next(t for t in shlex.split(command) if "codex_supervisor" in t)
    words = shlex.split(script)
    assert words[words.index(next(w for w in words if "codex_supervisor" in w)) - 1] == "-B"


def test_payload_build_compiles_under_dash_b() -> None:
    line = next(l for l in (ROOT / "macOS/payload/build-payload.sh").read_text().splitlines() if "compileall" in l and "-m" in l)
    assert " -B " in line
