
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_lo_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_lo_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.config.provider_accounts import ProviderAccount, managed_dir_for
from src.core.provider_ledger import profile_logout, refresh_poke

CLAUDE_BINARY = "/opt/homebrew/bin/claude"
CODEX_BINARY = "/opt/homebrew/bin/codex"


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def managed(provider: str = "claude", account_id: str = "claude1") -> ProviderAccount:
    return ProviderAccount(
        id=account_id, name="Managed", provider=provider, managed=True
    )


def unmanaged(directory: str = "~/.claude") -> ProviderAccount:
    return ProviderAccount(
        id="mine", name="Mine", provider="claude", claude_config_dir=directory
    )


class Runner:

    def __init__(self, outcome: refresh_poke.PokeOutcome) -> None:
        self.outcome = outcome
        self.calls: list = []

    async def __call__(self, argv, env, **kwargs):
        self.calls.append({"argv": list(argv), "env": dict(env), **kwargs})
        return self.outcome


def ran(exit_code: int = 0, timed_out: bool = False) -> refresh_poke.PokeOutcome:
    return refresh_poke.PokeOutcome(
        ran=True,
        exit_code=None if timed_out else exit_code,
        timed_out=timed_out,
        duration_seconds=0.1,
    )




@pytest.mark.asyncio
async def test_a_claude_profile_runs_auth_logout(home) -> None:
    runner = Runner(ran())

    await profile_logout.log_out_profile(
        managed(), run=runner, resolve=lambda name: CLAUDE_BINARY
    )

    assert runner.calls[0]["argv"] == [CLAUDE_BINARY, "auth", "logout"]


@pytest.mark.asyncio
async def test_the_claude_child_is_pointed_at_the_managed_profile(home) -> None:
    runner = Runner(ran())

    await profile_logout.log_out_profile(
        managed(), run=runner, resolve=lambda name: CLAUDE_BINARY
    )

    assert runner.calls[0]["env"]["CLAUDE_CONFIG_DIR"] == managed_dir_for("claude1")


@pytest.mark.asyncio
async def test_the_claude_child_inherits_no_credential(home, monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_REFRESH_TOKEN", "must-not-be-spent")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-be-used")
    runner = Runner(ran())

    await profile_logout.log_out_profile(
        managed(), run=runner, resolve=lambda name: CLAUDE_BINARY
    )

    env = runner.calls[0]["env"]
    assert "CLAUDE_CODE_OAUTH_REFRESH_TOKEN" not in env
    assert "ANTHROPIC_API_KEY" not in env


@pytest.mark.asyncio
async def test_a_codex_profile_runs_codex_logout(home) -> None:
    runner = Runner(ran())

    await profile_logout.log_out_profile(
        managed("codex", "codex1"), run=runner, resolve=lambda name: CODEX_BINARY
    )

    assert runner.calls[0]["argv"] == [CODEX_BINARY, "logout"]


@pytest.mark.asyncio
async def test_the_codex_child_is_pointed_at_its_own_home(home) -> None:
    runner = Runner(ran())

    await profile_logout.log_out_profile(
        managed("codex", "codex1"), run=runner, resolve=lambda name: CODEX_BINARY
    )

    env = runner.calls[0]["env"]
    assert env["CODEX_HOME"] == managed_dir_for("codex1")
    assert "CLAUDE_CONFIG_DIR" not in env


@pytest.mark.asyncio
async def test_each_provider_asks_for_its_own_binary(home) -> None:
    asked: list = []

    def resolve(name: str):
        asked.append(name)
        return "/somewhere/" + name

    await profile_logout.log_out_profile(
        managed("codex", "codex1"), run=Runner(ran()), resolve=resolve
    )

    assert asked == ["codex"]




@pytest.mark.asyncio
async def test_an_unmanaged_row_is_never_logged_out(home) -> None:
    runner = Runner(ran())

    answer = await profile_logout.log_out_profile(
        unmanaged(), run=runner, resolve=lambda name: CLAUDE_BINARY
    )

    assert answer == profile_logout.LOGOUT_SKIPPED
    assert runner.calls == []


@pytest.mark.asyncio
async def test_an_unmanaged_row_naming_its_own_directory_is_still_skipped(
    home,
) -> None:
    runner = Runner(ran())

    answer = await profile_logout.log_out_profile(
        unmanaged(managed_dir_for("claude1")),
        run=runner,
        resolve=lambda name: CLAUDE_BINARY,
    )

    assert answer == profile_logout.LOGOUT_SKIPPED
    assert runner.calls == []




@pytest.mark.asyncio
async def test_exit_zero_is_ok(home) -> None:
    answer = await profile_logout.log_out_profile(
        managed(), run=Runner(ran(0)), resolve=lambda name: CLAUDE_BINARY
    )

    assert answer == profile_logout.LOGOUT_OK


@pytest.mark.asyncio
async def test_a_non_zero_exit_is_a_failure(home) -> None:
    answer = await profile_logout.log_out_profile(
        managed(), run=Runner(ran(1)), resolve=lambda name: CLAUDE_BINARY
    )

    assert answer == profile_logout.LOGOUT_FAILED


@pytest.mark.asyncio
async def test_a_child_that_overran_is_a_failure(home) -> None:
    answer = await profile_logout.log_out_profile(
        managed(), run=Runner(ran(timed_out=True)), resolve=lambda name: CLAUDE_BINARY
    )

    assert answer == profile_logout.LOGOUT_FAILED


@pytest.mark.asyncio
async def test_a_child_that_never_started_is_a_failure(home) -> None:
    outcome = refresh_poke.PokeOutcome(
        ran=False, exit_code=None, timed_out=False, duration_seconds=0.0
    )

    answer = await profile_logout.log_out_profile(
        managed(), run=Runner(outcome), resolve=lambda name: CLAUDE_BINARY
    )

    assert answer == profile_logout.LOGOUT_FAILED


@pytest.mark.asyncio
async def test_no_binary_on_this_machine_is_a_failure_and_spawns_nothing(
    home,
) -> None:
    runner = Runner(ran())

    answer = await profile_logout.log_out_profile(
        managed(), run=runner, resolve=lambda name: None
    )

    assert answer == profile_logout.LOGOUT_FAILED
    assert runner.calls == []


@pytest.mark.asyncio
async def test_the_real_resolver_finds_nothing_under_the_suite_marker(
    home, monkeypatch
) -> None:
    monkeypatch.setenv(refresh_poke.TEST_MODE_ENV, "1")
    runner = Runner(ran())

    answer = await profile_logout.log_out_profile(managed(), run=runner)

    assert answer == profile_logout.LOGOUT_FAILED
    assert runner.calls == []


@pytest.mark.asyncio
async def test_the_child_gets_no_stdin_and_a_bounded_run(home) -> None:
    runner = Runner(ran())

    await profile_logout.log_out_profile(
        managed(), run=runner, resolve=lambda name: CLAUDE_BINARY
    )

    assert runner.calls[0]["timeout"] == refresh_poke.COMMAND_TIMEOUT_SECONDS
