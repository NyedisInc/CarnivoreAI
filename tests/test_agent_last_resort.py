
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_lr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_lr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.config import AgentsConfig, Settings
from src.config.mcp import McpConfig
from src.config.session import SessionConfig
from src.core.agent_families import AGENT_FAMILIES, get_family
from src.core.agent_last_resort import (
    guarded_launch_script,
    missing_tool_message,
)
from src.core.agent_wrappers import AgentWrapper, EXAMPLE_WRAPPERS

TOOL_FAMILIES = [
    ("codex", "codex"),
    ("hermes", "hermes"),
    ("openclaw", "openclaw"),
]



def _settings_with(tmp_path, **agent_overrides) -> Settings:
    settings = Settings(
        default_working_dir=os.environ["DEFAULT_WORKING_DIR"],
        log_directory=str(tmp_path),
    )
    cfg = SimpleNamespace(agents=AgentsConfig(**agent_overrides), session=SessionConfig(), mcp=McpConfig(),
                          launch_profiles=None, byoai=None)
    object.__setattr__(settings, "load_auth_config", lambda: cfg)
    return settings


@pytest.mark.parametrize("family_name", [f.name for f in AGENT_FAMILIES if f.seeded])
def test_no_wrapper_yields_a_runnable_command(tmp_path, family_name):
    settings = _settings_with(tmp_path, wrappers=[])
    model = "some/model" if get_family(family_name).needs_model else None
    command = settings.get_agent_command(family_name, model=model)
    assert command.strip() != ""
    subprocess.run(
        ["/bin/sh", "-n", "-c", command],
        check=True, capture_output=True, text=True,
    )
    family = get_family(family_name)
    inner = shlex.split(command)[2]
    sourced = [tok for tok in shlex.split(inner.replace(";", " ")) if tok.endswith(".zsh")]
    if family_name in ("claude", "codex", "shell"):
        assert sourced == [] and family.default_script in inner
        return
    assert [Path(p).name for p in sourced] == [f"{family.default_wrapper_id}.zsh"]
    assert Path(sourced[0]).read_text() == family.default_script


def test_the_shell_standard_wrapper_runs_when_SHELL_is_unset():
    resolved = subprocess.run(
        ["/bin/sh", "-c", 'unset SHELL; printf %s "${SHELL:-/bin/sh}"'],
        capture_output=True, text=True, check=True,
    )
    assert resolved.stdout == "/bin/sh"
    assert '"${SHELL:-/bin/sh}" -i' in get_family("shell").default_script


def test_guarded_script_execs_the_tool_when_present(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    tool = fake_bin / "codex"
    tool.write_text("#!/bin/sh\necho RAN_CODEX\n")
    tool.chmod(0o755)

    script = guarded_launch_script("codex", "codex", "codex")
    result = subprocess.run(
        ["/bin/sh", "-c", script],
        capture_output=True, text=True,
        env={"PATH": f"{fake_bin}:/usr/bin:/bin"},
    )
    assert result.stdout.strip() == "RAN_CODEX"
    assert "is not installed" not in result.stderr


def test_guarded_script_prints_every_hint_line_to_stderr(tmp_path):
    empty_bin = tmp_path / "empty"
    empty_bin.mkdir()
    script = guarded_launch_script("codex", "codex", "codex")
    result = subprocess.run(
        ["/bin/sh", "-c", script],
        capture_output=True, text=True, input="",
        env={"PATH": str(empty_bin)},
    )
    for line in missing_tool_message("codex", "codex").split("\n"):
        assert line in result.stderr


def test_guarded_script_is_valid_shell_for_every_tool_family():
    for family_name, binary in TOOL_FAMILIES:
        script = guarded_launch_script(binary, binary, family_name)
        subprocess.run(
            ["/bin/sh", "-n", "-c", script],
            check=True, capture_output=True, text=True,
        )


def test_message_carries_no_apostrophes():
    for family, binary in TOOL_FAMILIES:
        assert "'" not in missing_tool_message(binary, family)



def test_no_example_collides_with_a_seeded_standard_wrapper():
    seeded = {f.default_wrapper_id for f in AGENT_FAMILIES}
    for raw in EXAMPLE_WRAPPERS:
        assert raw["id"] not in seeded, raw["id"]


def test_example_wrappers_all_validate():
    for raw in EXAMPLE_WRAPPERS:
        AgentWrapper(**raw)


def test_non_claude_examples_do_not_touch_the_keychain():
    for raw in EXAMPLE_WRAPPERS:
        if raw["family"] == "claude":
            continue
        assert "security find-generic-password" not in raw["script"]
