from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest


os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_agent_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_agent_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from pydantic import ValidationError

from src.config import (
    AgentsConfig,
    AuthConfig,
    ProjectConfig,
    Settings,
    settings,
)
from src.models import (
    AttachableSession,
    CreateSessionRequest,
    Session,
    SessionInfo,
    SessionStats,
    SessionStatus,
)
from src.core.session_manager import backfill_agent_type
from tests.helpers.wrapper_seeds import launches




@pytest.mark.parametrize(
    "agent_type",
    ["claude", "codex", "hermes", "openclaw", None],
)
def test_session_agent_type_round_trip(agent_type):
    s = Session(
        id="ses_abc12345",
        working_dir="/tmp/foo",
        agent_type=agent_type,
    )
    dumped = s.model_dump()
    assert dumped["agent_type"] == agent_type

    reloaded = Session(**dumped)
    assert reloaded.agent_type == agent_type
    assert reloaded.id == s.id


def test_session_agent_type_defaults_to_none_when_omitted():
    s = Session(id="ses_xyz", working_dir="/tmp/bar")
    assert s.agent_type is None


def test_session_info_agent_type_round_trip():
    s = Session(id="ses_1", working_dir="/tmp", agent_type="codex")
    info = SessionInfo(session=s, agent_type="codex", stats=SessionStats())
    dumped = info.model_dump()
    assert dumped["agent_type"] == "codex"
    reloaded = SessionInfo(**dumped)
    assert reloaded.agent_type == "codex"


def test_attachable_session_agent_type_round_trip():
    row = AttachableSession(
        name="cloude_test",
        created_by_cloude=True,
        created_at_epoch=1700000000,
        window_count=1,
        agent_type="hermes",
    )
    dumped = row.model_dump()
    assert dumped["agent_type"] == "hermes"
    reloaded = AttachableSession(**dumped)
    assert reloaded.agent_type == "hermes"

    row_none = AttachableSession(
        name="cloude_test2",
        created_by_cloude=False,
        created_at_epoch=1700000000,
        window_count=1,
    )
    assert row_none.agent_type is None




def test_agents_config_carries_wrappers_only():
    cfg = AgentsConfig(claude_command="claude-foo", codex_command="codex --x")
    assert cfg.wrappers == []
    assert not hasattr(cfg, "claude_command")
    assert not hasattr(cfg, "codex_command")




def _settings_with_agents(agents_cfg: AgentsConfig):
    s = Settings(
        default_working_dir=os.environ["DEFAULT_WORKING_DIR"],
        log_directory=os.environ["LOG_DIRECTORY"],
    )
    fake_auth = settings.load_auth_config().model_copy(update={"agents": agents_cfg})
    object.__setattr__(s, "load_auth_config", lambda: fake_auth)
    return s


def _sources(command: str) -> str:
    import re

    match = re.search(r"source ([^ ]+\.zsh)(?: |$)", command.replace("'", ""))
    if match:
        return Path(match.group(1)).name
    names = [n for n in ("claude.zsh", "codex-default.zsh", "shell-default.zsh") if launches(command, n)]
    assert len(names) == 1, command
    return names[0]


@pytest.mark.parametrize(
    "agent_type,script",
    [
        ("codex", "codex-default.zsh"),
        ("CODEX", "codex-default.zsh"),
        ("hermes", "hermes-default.zsh"),
        ("OpenClaw", "openclaw-default.zsh"),
        ("shell", "shell-default.zsh"),
        ("claude", "claude.zsh"),
        ("totally-bogus", "claude.zsh"),
        (None, "claude.zsh"),
        ("", "claude.zsh"),
    ],
)
def test_every_type_launches_its_familys_standard_wrapper(agent_type, script):
    s = _settings_with_agents(AgentsConfig())
    assert _sources(s.get_agent_command(agent_type)) == script


def test_get_agent_command_tolerates_auth_config_failure():
    s = Settings(
        default_working_dir=os.environ["DEFAULT_WORKING_DIR"],
        log_directory=os.environ["LOG_DIRECTORY"],
    )

    def boom():
        raise FileNotFoundError("auth config missing")

    object.__setattr__(s, "load_auth_config", boom)
    assert _sources(s.get_agent_command("codex")) == "codex-default.zsh"
    assert _sources(s.get_agent_command("claude")) == "claude.zsh"


def test_the_codex_standard_launch_carries_no_alt_screen():
    s = _settings_with_agents(AgentsConfig())
    assert s.get_agent_command("codex").endswith("_ --no-alt-screen")


def test_a_model_is_one_literal_argument_to_a_model_wrapper():
    import subprocess

    from src.core.shell_init import RC_SOURCE

    s = _settings_with_agents(AgentsConfig())
    marker = Path(tempfile.mkdtemp(prefix="cc_pwn_")) / "pwned"
    payload = f"foo; touch {marker}; echo"
    cmd = s.get_agent_command("local", model=payload)
    probed = cmd.replace(
        RC_SOURCE,
        'cldl() { echo "ARGC:$#|GOT:[$1]"; }',
    )
    assert probed != cmd, "the rc source was not where it was expected"
    proc = subprocess.run(["/bin/sh", "-c", probed],
                          capture_output=True, text=True, timeout=10)
    assert proc.stdout.strip() == f"ARGC:1|GOT:[{payload}]", proc.stderr
    assert not marker.exists()




@pytest.mark.parametrize(
    "agent_type",
    ["claude", "codex", "hermes", "openclaw"],
)
def test_project_config_accepts_known_agent_types(agent_type):
    p = ProjectConfig(
        name="x", path="/tmp", description="d", agent_type=agent_type
    )
    assert p.agent_type == agent_type


def test_project_config_rejects_unknown_agent_type():
    with pytest.raises(ValidationError):
        ProjectConfig(
            name="x",
            path="/tmp",
            description="d",
            agent_type="invalid_type",
        )


def test_project_config_defaults_to_claude():
    p = ProjectConfig(name="x", path="/tmp")
    assert p.agent_type == "claude"




def test_create_session_request_explicit_agent_type():
    req = CreateSessionRequest(agent_type="codex")
    assert req.agent_type == "codex"


def test_create_session_request_none_agent_type():
    req = CreateSessionRequest(agent_type=None)
    assert req.agent_type is None


def test_create_session_request_missing_agent_type_defaults_none():
    req = CreateSessionRequest()
    assert req.agent_type is None


def test_create_session_request_accepts_arbitrary_string():
    req = CreateSessionRequest(agent_type="future_agent")
    assert req.agent_type == "future_agent"




def test_create_session_request_model_none_by_default():
    req = CreateSessionRequest()
    assert req.model is None


@pytest.mark.parametrize(
    "model",
    ["openai/gpt-5.6-sol", "qwen/qwen3.8-max", "a", "a" * 120, "~anthropic/x"],
)
def test_create_session_request_model_accepts_valid_ids(model):
    req = CreateSessionRequest(model=model)
    assert req.model == model


@pytest.mark.parametrize(
    "model",
    [
        "foo; rm -rf /",
        "foo`whoami`",
        "foo$(whoami)",
        "foo bar",
        "foo\nbar",
        "a" * 121,
        "",
    ],
)
def test_create_session_request_model_rejects_invalid_ids(model):
    with pytest.raises(ValidationError):
        CreateSessionRequest(model=model)


def test_session_model_field_round_trip():
    s = Session(
        id="ses_abc", working_dir="/tmp", agent_type="claude", model="openai/gpt-5.6-sol"
    )
    dumped = s.model_dump()
    assert dumped["model"] == "openai/gpt-5.6-sol"
    reloaded = Session(**dumped)
    assert reloaded.model == "openai/gpt-5.6-sol"


def test_session_model_field_defaults_to_none():
    s = Session(id="ses_abc", working_dir="/tmp")
    assert s.model is None




def test_legacy_session_json_loads_cleanly():
    legacy = {
        "id": "ses_legacy01",
        "pty_pid": None,
        "working_dir": "/tmp/legacy",
        "status": "running",
        "created_at": "2024-01-01T00:00:00",
        "last_activity": "2024-01-01T00:01:00",
        "tunnels": [],
    }
    s = Session(**legacy)
    assert s.agent_type is None
    assert s.id == "ses_legacy01"
    assert s.status == SessionStatus.RUNNING


def test_legacy_session_json_with_extra_unknown_field_loads():
    legacy = {
        "id": "ses_future",
        "working_dir": "/tmp/x",
        "future_field": "ignored",
    }
    s = Session(**legacy)
    assert s.id == "ses_future"
    assert s.agent_type is None




def test_backfill_owned_session_gets_claude():
    s = Session(id="ses_owned1", working_dir="/tmp", agent_type=None)
    n = backfill_agent_type(s)
    assert n == 1
    assert s.agent_type == "claude"


def test_backfill_adopted_session_stays_none():
    s = Session(id="adopted:cloude_userone", working_dir="/tmp", agent_type=None)
    n = backfill_agent_type(s)
    assert n == 0
    assert s.agent_type is None


def test_backfill_returns_zero_when_already_set():
    s = Session(id="ses_owned1", working_dir="/tmp", agent_type="codex")
    n = backfill_agent_type(s)
    assert n == 0
    assert s.agent_type == "codex"


def test_backfill_idempotent_on_second_call():
    s = Session(id="ses_owned2", working_dir="/tmp", agent_type=None)
    n1 = backfill_agent_type(s)
    n2 = backfill_agent_type(s)
    assert n1 == 1
    assert n2 == 0
    assert s.agent_type == "claude"


def test_backfill_returns_zero_for_none_session():
    n = backfill_agent_type(None)
    assert n == 0


def test_backfill_owned_set_none_falls_back_to_id_prefix():
    owned_session = Session(id="ses_normal", working_dir="/tmp", agent_type=None)
    n = backfill_agent_type(owned_session)
    assert n == 1
    assert owned_session.agent_type == "claude"

    adopted_session = Session(
        id="adopted:something", working_dir="/tmp", agent_type=None
    )
    n2 = backfill_agent_type(adopted_session)
    assert n2 == 0
    assert adopted_session.agent_type is None


def test_backfill_handles_all_known_agent_types_unchanged():
    for at in ["claude", "codex", "hermes", "openclaw"]:
        s = Session(id=f"ses_{at}", working_dir="/tmp", agent_type=at)
        assert backfill_agent_type(s) == 0
        assert s.agent_type == at
