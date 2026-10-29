
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
import pytest

from src.core.agent_wrappers import AgentWrapper, render_wrapper_invocation

UUID = "0199aa11-bbbb-cccc-dddd-eeeeeeeeeeee"
FORK_ARGS = ["--resume", UUID, "--fork-session"]


def _wrapper(**kw):
    base = dict(
        id="cld", label="cld", script="cld() { command claude \"$@\"; }",
        entry="cld", default=True, accepts_model=False, family="claude",
    )
    base.update(kw)
    return AgentWrapper(**base)




def test_fork_args_reach_a_wrapper_as_positionals(tmp_path):
    out = render_wrapper_invocation(_wrapper(), tmp_path, extra_args=FORK_ARGS)
    assert out.endswith(f" _ --resume {UUID} --fork-session")


def test_the_throwaway_zero_is_emitted_even_with_no_model(tmp_path):
    out = render_wrapper_invocation(_wrapper(), tmp_path, extra_args=FORK_ARGS)
    assert " _ " in out, "no $0 slot: the first fork argument would be swallowed"
    assert out.index(" _ ") < out.index("--resume")


def test_a_model_and_fork_args_coexist_in_order(tmp_path):
    out = render_wrapper_invocation(
        _wrapper(accepts_model=True), tmp_path, model="vendor/m-1",
        extra_args=FORK_ARGS,
    )
    assert out.endswith(f" _ vendor/m-1 --resume {UUID} --fork-session")


def test_a_modelless_wrapper_still_receives_the_fork_args(tmp_path):
    import json

    from src.config import Settings

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "config_version": 3,
        "agents": {
            "claude_command": "",
            "wrappers": [_wrapper(accepts_model=False).model_dump()],
        },
        "projects": [],
    }))
    s = Settings(
        default_working_dir=str(tmp_path),
        log_directory=str(tmp_path / "logs"),
        totp_secret="x",
        jwt_secret="y",
        auth_config_file=str(config_path),
    )

    out = s.get_agent_command("cld", model="vendor/m-1", extra_args=FORK_ARGS)
    assert "vendor/m-1" not in out, "a modelless wrapper was handed a model"
    assert f"--resume {UUID} --fork-session" in out


def test_no_extra_args_is_byte_identical_to_before(tmp_path):
    plain = render_wrapper_invocation(_wrapper(), tmp_path)
    assert " _ " not in plain
    assert plain == render_wrapper_invocation(_wrapper(), tmp_path, extra_args=[])


@pytest.mark.parametrize("hostile", [
    "; rm -rf /", "`whoami`", "$(id)", "~/secret", "a b", "'quoted'",
    "$IFS", "\n newline", "--not-a-flag=$(id)",
])
def test_a_hostile_uuid_cannot_break_out(tmp_path, hostile):
    import shlex

    w = render_wrapper_invocation(
        _wrapper(), tmp_path, extra_args=["--resume", hostile]
    )
    w_tokens = shlex.split(w)
    assert w_tokens[-3:] == ["_", "--resume", hostile], w_tokens[-3:]
