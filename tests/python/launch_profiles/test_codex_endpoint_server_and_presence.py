
from __future__ import annotations

import asyncio
import json
import shlex
from pathlib import Path

from src.config.launch_profiles import LaunchProfile
from src.core.launch_profiles.render import render_structured
from src.core.tmux_backend import TmuxBackend

THREAD = "01a1011a-f8b7-70e3-919c-1ad472af186b"


def test_codex_endpoint_settings_reach_the_app_server_and_the_tui() -> None:
    profile = LaunchProfile(id="cx", harness="codex", label="cx")
    extra = ["-c", 'model_provider="carnivore-x"', "-c", 'model_providers.carnivore-x.wire_api="responses"']
    command = render_structured(profile, "rig-model", ["--no-alt-screen"], False, extra_flags=extra,
                                codex_server_args=["-c", "mcp_servers.carnivore.url=\"u\""])
    script = next(t for t in shlex.split(command) if "codex_supervisor" in t)
    spec = json.loads(next(t for t in shlex.split(script) if t.startswith("{")))
    assert all(word in spec["server"] for word in extra), spec["server"]
    assert all(word in spec["tui"] for word in extra), spec["tui"]


def test_a_codex_resume_is_looked_up_in_the_rollout_store(tmp_path: Path, monkeypatch) -> None:
    rollout = tmp_path / "sessions" / "2026" / "10" / "03"
    rollout.mkdir(parents=True)
    (rollout / f"rollout-2026-10-03T05-00-00-{THREAD}.jsonl").write_text("{}\n")
    from src.core.attention import codex_gather

    monkeypatch.setattr(codex_gather, "DEFAULT_CODEX_HOME", str(tmp_path))
    backend = TmuxBackend.__new__(TmuxBackend)
    backend.working_dir = tmp_path
    assert asyncio.run(backend._resume_presence(THREAD, "codex"))[0] == "present"
