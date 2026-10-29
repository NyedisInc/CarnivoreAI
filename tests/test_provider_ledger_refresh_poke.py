
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest
import structlog

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_poke_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_poke_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.provider_ledger import refresh_poke

PROFILE = "/Users/nobody/.carnivore/accounts/claude1"

BINARY = "/opt/homebrew/bin/claude"

MUST_NOT_REACH_THE_CHILD = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_API_KEY",
    "CLAUDE_CODE_OAUTH_REFRESH_TOKEN",
    "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR",
    "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
    "CLAUDE_CODE_GATEWAY_TOKEN_FILE_DESCRIPTOR",
    "CLAUDE_CODE_WEBSOCKET_AUTH_FILE_DESCRIPTOR",
    "CLAUDE_CODE_HOST_CREDS_FILE",
    "CLAUDE_CODE_HOST_AUTH_ENV_VAR",
    "CLAUDE_SESSION_INGRESS_TOKEN_FILE",
    "ANTHROPIC_IDENTITY_TOKEN",
    "ANTHROPIC_IDENTITY_TOKEN_FILE",
    "CLAUDE_CODE_SESSION_ACCESS_TOKEN",
    "CLAUDE_TRUSTED_DEVICE_TOKEN",
    "CLAUDE_BRIDGE_OAUTH_TOKEN",
    "CLAUDE_CODE_HFI_BEARER_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_USE_MANTLE",
    "CLAUDE_CODE_USE_GATEWAY",
    "CLAUDE_CODE_USE_ANTHROPIC_AWS",
    "CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD",
    "AWS_BEARER_TOKEN_BEDROCK",
    "ANTHROPIC_AWS_API_KEY",
    "ANTHROPIC_FOUNDRY_API_KEY",
    "ANTHROPIC_FOUNDRY_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_API_HOST",
    "ANTHROPIC_BEDROCK_BASE_URL",
    "ANTHROPIC_BEDROCK_MANTLE_BASE_URL",
    "ANTHROPIC_VERTEX_BASE_URL",
    "ANTHROPIC_FOUNDRY_BASE_URL",
    "ANTHROPIC_AWS_BASE_URL",
    "ANTHROPIC_GOOGLE_CLOUD_BASE_URL",
    "ANTHROPIC_UNIX_SOCKET",
    "CLAUDE_CODE_API_BASE_URL",
    "CLAUDE_CODE_CUSTOM_OAUTH_URL",
    "CLAUDE_AI_HOST",
    "CLAUDE_AI_ORIGIN",
    "CLAUDE_AI_AUTHORIZE_URL",
    "CLAUDE_HOST",
    "CLAUDE_LOCAL_OAUTH_API_BASE",
    "CLAUDE_LOCAL_OAUTH_APPS_BASE",
    "CLAUDE_LOCAL_OAUTH_CONSOLE_BASE",
    "CLAUDE_CODE_PROXY_URL",
    "CLAUDE_CODE_PROXY_HOST",
    "CLAUDE_CODE_HTTP_PROXY",
    "CLAUDE_CODE_HTTPS_PROXY",
    "CLAUDE_CODE_PROXY_AUTHENTICATE",
    "CLAUDE_CODE_CLIENT_CERT",
    "CLAUDE_CODE_CLIENT_KEY",
    "CLAUDE_CODE_CLIENT_KEY_PASSPHRASE",
    "ANTHROPIC_PROFILE",
    "ANTHROPIC_CONFIG_DIR",
    "CLAUDE_SECURESTORAGE_CONFIG_DIR",
    "CLAUDE_ENV_FILE",
    "ANTHROPIC_CUSTOM_HEADERS",
)


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


async def wait_until_gone(pid: int, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not alive(pid):
            return True
        await asyncio.sleep(0.02)
    return not alive(pid)


async def read_pid_when_written(path: Path, timeout: float = 3.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            text = path.read_text().strip()
        except FileNotFoundError:
            text = ""
        if text:
            return int(text)
        await asyncio.sleep(0.02)
    raise AssertionError("the child never wrote its process id")


class TestTheCommandIsFixed:

    def test_the_argv_is_the_minimal_print_run(self) -> None:
        argv, _ = refresh_poke.build_poke(PROFILE, BINARY)

        assert argv == [
            BINARY, "-p", "ok", "--model", "haiku", "--no-session-persistence",
            "--settings", '{"disableAllHooks":true}', "--strict-mcp-config",
            "--tools", "",
        ]
        assert "doctor" not in argv and "--bare" not in argv


class TestTheProfileVariable:

    def test_a_custom_profile_sets_the_config_dir_variable(self) -> None:
        _, env = refresh_poke.build_poke(PROFILE, BINARY)

        assert env["CLAUDE_CONFIG_DIR"] == PROFILE

    def test_the_default_profile_removes_the_variable_entirely(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/somewhere/inherited")

        _, env = refresh_poke.build_poke(None, BINARY)

        assert "CLAUDE_CONFIG_DIR" not in env

    def test_naming_the_default_directory_explicitly_also_removes_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/somewhere/inherited")

        _, env = refresh_poke.build_poke("~/.claude", BINARY)

        assert "CLAUDE_CONFIG_DIR" not in env


class TestWhatIsStrippedFromTheEnvironment:

    @pytest.mark.parametrize("name", MUST_NOT_REACH_THE_CHILD)
    def test_a_credential_or_routing_variable_is_removed(
        self, name: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(name, "not-a-real-value")

        _, env = refresh_poke.build_poke(PROFILE, BINARY)

        assert name not in env

    def test_the_whole_set_goes_at_once_and_not_one_at_a_time(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in MUST_NOT_REACH_THE_CHILD:
            monkeypatch.setenv(name, "not-a-real-value")

        _, env = refresh_poke.build_poke(PROFILE, BINARY)

        assert [name for name in MUST_NOT_REACH_THE_CHILD if name in env] == []

    def test_the_single_use_refresh_token_is_removed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_REFRESH_TOKEN", "not-a-real-value")

        _, env = refresh_poke.build_poke(PROFILE, BINARY)

        assert "CLAUDE_CODE_OAUTH_REFRESH_TOKEN" not in env

    def test_only_the_allow_list_survives_and_session_vars_do_not(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        inherited = (
            "CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ID",
            "CLAUDE_PID", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
            "CLAUDE_CODE_BRIDGE_SESSION_ID", "CC_POKE_MARKER",
        )
        for name in inherited:
            monkeypatch.setenv(name, "inherited")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/somewhere/inherited")
        monkeypatch.setenv("HOME", "/Users/nobody")
        monkeypatch.setenv("PATH", "/usr/bin")

        _, env = refresh_poke.build_poke(PROFILE, BINARY)

        assert [n for n in inherited if n in env] == []
        assert env["HOME"] == "/Users/nobody" and env["PATH"] == "/usr/bin"
        assert env["CLAUDE_CONFIG_DIR"] == PROFILE
        assert set(env) <= set(refresh_poke.ENV_ALLOW_LIST) | {"CLAUDE_CONFIG_DIR"}

    def test_the_parent_environment_is_never_mutated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-value")

        refresh_poke.build_poke(PROFILE, BINARY)

        assert os.environ["ANTHROPIC_API_KEY"] == "not-a-real-value"


class TestRunningIt:

    @pytest.mark.asyncio
    async def test_a_child_that_succeeds_is_reported_as_exit_zero(self) -> None:
        outcome = await refresh_poke.run_poke(["/usr/bin/true"], dict(os.environ))

        assert outcome.ran is True
        assert outcome.exit_code == 0
        assert outcome.timed_out is False
        assert outcome.duration_seconds >= 0.0

    @pytest.mark.asyncio
    async def test_a_child_that_fails_carries_its_status(self) -> None:
        outcome = await refresh_poke.run_poke(["/usr/bin/false"], dict(os.environ))

        assert outcome.ran is True
        assert outcome.exit_code != 0
        assert outcome.timed_out is False

    @pytest.mark.asyncio
    async def test_a_child_reading_stdin_sees_end_of_file_at_once(self) -> None:
        outcome = await refresh_poke.run_poke(["/bin/cat"], dict(os.environ), timeout=5.0)

        assert outcome.timed_out is False
        assert outcome.exit_code == 0

    @pytest.mark.asyncio
    async def test_a_child_that_overruns_is_killed_rather_than_waited_out(self) -> None:
        outcome = await refresh_poke.run_poke(
            ["/bin/sleep", "5"], dict(os.environ), timeout=0.3
        )

        assert outcome.timed_out is True
        assert outcome.exit_code is None
        assert outcome.duration_seconds < 3.0

    @pytest.mark.asyncio
    async def test_a_binary_that_is_not_there_is_a_state_and_not_an_exception(
        self,
    ) -> None:
        outcome = await refresh_poke.run_poke(
            ["/nonexistent/claude", "doctor"], dict(os.environ)
        )

        assert outcome.ran is False
        assert outcome.exit_code is None
        assert outcome.timed_out is False


class TestTheKillReachesTheWholeTree:

    @staticmethod
    def forked_child(pid_file: Path) -> list:
        return [
            "/bin/sh",
            "-c",
            f"sleep 30 & echo $! > '{pid_file}'; wait",
        ]

    @pytest.mark.asyncio
    async def test_the_timeout_kills_the_grandchild_as_well(
        self, tmp_path: Path
    ) -> None:
        pid_file = tmp_path / "grandchild.pid"

        outcome = await refresh_poke.run_poke(
            self.forked_child(pid_file), dict(os.environ), timeout=0.5
        )

        assert outcome.timed_out is True
        grandchild = int(pid_file.read_text().strip())
        try:
            assert await wait_until_gone(grandchild)
        finally:
            if alive(grandchild):
                os.kill(grandchild, 9)

    @pytest.mark.asyncio
    async def test_a_cancelled_poke_kills_the_child_before_it_propagates(
        self, tmp_path: Path
    ) -> None:
        pid_file = tmp_path / "grandchild.pid"
        task = asyncio.ensure_future(
            refresh_poke.run_poke(
                self.forked_child(pid_file), dict(os.environ), timeout=30.0
            )
        )
        grandchild = await read_pid_when_written(pid_file)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        try:
            assert await wait_until_gone(grandchild)
        finally:
            if alive(grandchild):
                os.kill(grandchild, 9)


class TestNothingTheChildPrintsIsLogged:

    @pytest.mark.asyncio
    async def test_the_log_carries_byte_counts_and_never_the_output(self) -> None:
        marker = "OAUTH-SESSION-EXPIRED-MARKER"
        argv = ["/bin/echo", marker]

        with structlog.testing.capture_logs() as captured:
            outcome = await refresh_poke.run_poke(argv, dict(os.environ))

        assert outcome.exit_code == 0
        assert any("poke" in str(record.get("event")) for record in captured)
        assert marker not in repr(captured)
        assert any(
            record.get("stdout_bytes") == len(marker) + 1 for record in captured
        )

    @pytest.mark.asyncio
    async def test_the_output_is_classified_into_labels_and_never_quoted(
        self,
    ) -> None:
        secret = "sk-ant-ort01-NEVER-LOG-THIS-REFRESH-VALUE"
        argv = ["/bin/sh", "-c", f"echo 'OAuth error: invalid_grant {secret}' >&2"]

        with structlog.testing.capture_logs() as captured:
            outcome = await refresh_poke.run_poke(argv, dict(os.environ))

        assert "invalid_grant" in outcome.output_signals
        assert "oauth" in outcome.output_signals
        assert outcome.stderr_bytes > 0
        ran = [r for r in captured if r.get("event") == "provider_ledger_poke_ran"]
        assert ran and "invalid_grant" in ran[0]["output_signals"]
        assert secret not in repr(captured)
        assert secret not in repr(outcome)

    def test_classification_is_labels_in_table_order_and_empty_on_silence(
        self,
    ) -> None:
        assert refresh_poke.classify_output(b"OAuth error: invalid_grant", b"") == (
            "invalid_grant",
            "oauth",
            "error",
        )
        assert refresh_poke.classify_output(b"", None) == ()
        assert refresh_poke.classify_output(b"all checks passed", b"") == ()


class TestResolvingTheBinary:

    def test_the_suite_marker_disables_the_poke_entirely(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(refresh_poke.TEST_MODE_ENV, "1")

        assert refresh_poke.resolve_claude_binary() is None

    def test_without_the_marker_it_answers_an_absolute_path_or_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(refresh_poke.TEST_MODE_ENV, raising=False)
        monkeypatch.setattr(refresh_poke.shutil, "which", lambda name: "/usr/bin/true")

        assert refresh_poke.resolve_claude_binary() == "/usr/bin/true"

    def test_a_relative_answer_disables_the_poke(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(refresh_poke.TEST_MODE_ENV, raising=False)
        monkeypatch.setattr(refresh_poke.shutil, "which", lambda name: "claude")

        assert refresh_poke.resolve_claude_binary() is None

    def test_an_empty_path_entry_is_how_a_relative_answer_happens(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        planted = tmp_path / "claude"
        planted.write_text("#!/bin/sh\nexit 0\n")
        planted.chmod(0o755)
        monkeypatch.delenv(refresh_poke.TEST_MODE_ENV, raising=False)
        monkeypatch.setenv("PATH", f":{os.environ.get('PATH', '')}")
        monkeypatch.chdir(tmp_path)

        assert refresh_poke.shutil.which("claude") == "claude"
        assert refresh_poke.resolve_claude_binary() is None

    def test_a_path_that_is_not_executable_disables_the_poke(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        unreadable = tmp_path / "claude"
        unreadable.write_text("not a program")
        unreadable.chmod(0o644)
        monkeypatch.delenv(refresh_poke.TEST_MODE_ENV, raising=False)
        monkeypatch.setattr(
            refresh_poke.shutil, "which", lambda name: str(unreadable)
        )

        assert refresh_poke.resolve_claude_binary() is None


class TestTheBuilderIsSharedWithTheLogout:

    def test_any_subcommand_can_be_built_with_the_same_environment(self) -> None:
        argv, env = refresh_poke.build_claude_command(
            PROFILE, BINARY, "auth", "logout"
        )

        assert argv == [BINARY, "auth", "logout"]
        assert env[refresh_poke.PROFILE_ENV_VAR] == PROFILE

    def test_the_poke_is_that_builder_with_one_subcommand(self) -> None:
        assert refresh_poke.build_poke(PROFILE, BINARY) == (
            refresh_poke.build_claude_command(PROFILE, BINARY, *refresh_poke.KEEPALIVE_ARGS)
        )

    def test_the_shared_builder_strips_the_single_use_refresh_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_REFRESH_TOKEN", "must-not-be-spent")

        _, env = refresh_poke.build_claude_command(PROFILE, BINARY, "auth", "logout")

        assert "CLAUDE_CODE_OAUTH_REFRESH_TOKEN" not in env

    def test_a_command_with_no_arguments_is_the_bare_binary(self) -> None:
        argv, _ = refresh_poke.build_claude_command(PROFILE, BINARY)

        assert argv == [BINARY]


class TestResolvingAnyBinaryFollowsOneRule:

    def test_the_claude_resolver_is_that_one_rule_applied_to_claude(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        found = tmp_path / "claude"
        found.write_text("#!/bin/sh\n")
        found.chmod(0o755)
        monkeypatch.delenv(refresh_poke.TEST_MODE_ENV, raising=False)
        monkeypatch.setattr(refresh_poke.shutil, "which", lambda name: str(found))

        assert refresh_poke.resolve_claude_binary() == refresh_poke.resolve_binary(
            "claude"
        )

    def test_another_name_is_looked_up_under_that_name(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        asked: list = []
        found = tmp_path / "codex"
        found.write_text("#!/bin/sh\n")
        found.chmod(0o755)
        monkeypatch.delenv(refresh_poke.TEST_MODE_ENV, raising=False)

        def which(name: str):
            asked.append(name)
            return str(found)

        monkeypatch.setattr(refresh_poke.shutil, "which", which)

        assert refresh_poke.resolve_binary("codex") == str(found)
        assert asked == ["codex"]

    def test_the_suite_marker_disables_every_name_and_not_just_claude(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(refresh_poke.TEST_MODE_ENV, "1")

        assert refresh_poke.resolve_binary("codex") is None

    def test_a_relative_answer_disables_any_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(refresh_poke.TEST_MODE_ENV, raising=False)
        monkeypatch.setattr(refresh_poke.shutil, "which", lambda name: name)

        assert refresh_poke.resolve_binary("codex") is None
