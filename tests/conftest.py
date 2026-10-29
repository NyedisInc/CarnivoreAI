
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterator

import pytest

os.environ.setdefault("CLOUDE_STATE_DIR", tempfile.mkdtemp(prefix="cc_test_state_"))

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_test_wd_"))

os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_test_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

os.environ.setdefault("CLOUDE_TEST_MODE", "1")

os.environ.setdefault(
    "CLOUDE_CLAUDE_SETTINGS_PATH",
    os.path.join(
        tempfile.mkdtemp(prefix="cc_test_claude_home_"), ".claude", "settings.json"
    ),
)

os.environ["CARNIVORE_ACCOUNTS_DIR"] = tempfile.mkdtemp(prefix="cc_test_accounts_")

_SHARED_MCP_ROOT = tempfile.mkdtemp(prefix="cc_test_shared_mcp_")
os.environ.setdefault(
    "CLOUDE_SHARED_MCP_PATH", os.path.join(_SHARED_MCP_ROOT, "unset", "carnivore-mcp.json")
)

os.environ["CARNIVORE_ALLOWED_HOSTS"] = "testserver,lan,lan.local,t,s7.local,pcr.local"

from tests import settings_write_recorder
from tests.socket_guard import (
    FORBIDDEN_SOCKET_NAME,
    TEST_SOCKET_NAME,
    TEST_SOCKET_PREFIX,
    default_redirect_is_installed,
    guard_is_installed,
    install_default_socket_redirect,
    install_subprocess_guard,
    kill_test_socket_server,
    remove_default_socket_redirect,
    remove_subprocess_guard,
    sweep_stale_test_sockets,
)


def pytest_sessionstart(session: pytest.Session) -> None:
    if not hasattr(session.config, "workerinput") and not guard_is_installed():
        sweep_stale_test_sockets()


@pytest.fixture(autouse=True)
def shared_mcp_isolation(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    digest = hashlib.sha256(request.node.nodeid.encode()).hexdigest()[:16]
    monkeypatch.setenv(
        "CLOUDE_SHARED_MCP_PATH",
        os.path.join(_SHARED_MCP_ROOT, digest, "carnivore-mcp.json"),
    )


@pytest.fixture(autouse=True)
def hero_art_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.companies import hero_art_gen

    monkeypatch.setattr(hero_art_gen, "AUTO_GENERATE", False)


@pytest.fixture(autouse=True)
def agent_tool_switches_on(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("real_agent_tool_switches") is not None:
        return
    from src.core.mcp import agent_tool_switches

    monkeypatch.setattr(agent_tool_switches, "current", lambda: agent_tool_switches.AgentToolSwitches(huddle=True, swarm=True))


@pytest.fixture(autouse=True)
def swarm_switch_on(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("real_swarm_switch") is not None:
        return
    from src.core.swarm import switch

    monkeypatch.setattr(switch, "is_on", lambda: True)


@pytest.fixture(autouse=True)
def tool_family_signals_on(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("real_tool_family_signals") is not None:
        return
    from src.core.mcp import family_signals

    monkeypatch.setattr(family_signals, "in_use", lambda key: True)


@pytest.fixture(autouse=True)
def deprecated_tools_on(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("real_deprecated_default_off") is not None:
        return
    from src.core.mcp import tool_switches

    monkeypatch.setattr(tool_switches, "DEFAULT_OFF", frozenset())


@pytest.fixture(scope="session", autouse=True)
def tmux_socket_isolation() -> Iterator[str]:
    install_default_socket_redirect()
    install_subprocess_guard()
    try:
        yield TEST_SOCKET_NAME
    finally:
        kill_test_socket_server()
        remove_subprocess_guard()
        remove_default_socket_redirect()


@pytest.fixture(autouse=True)
def reset_pane_listing_cache() -> None:
    from src.core.sessions.pane_listing_cache import invalidate_pane_listing

    invalidate_pane_listing()


@pytest.fixture(autouse=True)
def assert_socket_guard_active(tmux_socket_isolation: str) -> None:
    if not guard_is_installed():
        pytest.fail(
            "tmux socket guard is NOT installed. The suite cannot prove it "
            "will stay off the production socket, so this is a failure, not "
            "a pass."
        )

    if not default_redirect_is_installed():
        pytest.fail(
            "the production default socket name was NOT redirected, so a "
            "test that names no socket would fall back to the live socket. "
            "That state cannot be shown to be safe, so it is a failure."
        )

    name = tmux_socket_isolation
    if not name:
        pytest.fail(
            "test tmux socket name is empty, so the target socket cannot be "
            "determined. Under the three-outcome rule that is a failure."
        )
    if name == FORBIDDEN_SOCKET_NAME:
        pytest.fail(
            f"test tmux socket resolved to the production socket "
            f"{FORBIDDEN_SOCKET_NAME!r}."
        )
    if not name.startswith(TEST_SOCKET_PREFIX):
        pytest.fail(
            f"test tmux socket {name!r} does not carry the required prefix "
            f"{TEST_SOCKET_PREFIX!r}, so it cannot be shown to be a "
            "throwaway socket."
        )


@pytest.fixture(scope="session")
def _nonscratch_base() -> Iterator[Path]:
    base = Path(tempfile.mkdtemp(prefix=".cloude-test-project-roots-", dir=Path.home()))
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


@pytest.fixture
def nonscratch_tmp_path(_nonscratch_base: Path) -> Path:
    from src.core.transcript_import_paths import is_scratch

    path = Path(tempfile.mkdtemp(dir=_nonscratch_base))
    assert not is_scratch(str(path)), (
        f"{path} is under a SCRATCH_PREFIXES entry, so the project binder "
        "will refuse it and every test using this fixture would assert "
        "against a refusal rather than against the behaviour it names."
    )
    return path


@pytest.fixture
def tmux_test_socket(tmux_socket_isolation: str) -> str:
    return tmux_socket_isolation


@pytest.fixture(autouse=True)
def _reset_tmux_probe_cache():
    from src.core import tmux_discovery

    tmux_discovery.reset_probe_cache()
    yield
    tmux_discovery.reset_probe_cache()


@pytest.fixture(autouse=True)
def _forget_pipeline_engine():
    from src.core.pipeline import runtime

    runtime.reset_for_test()
    yield
    runtime.reset_for_test()


@pytest.fixture(autouse=True)
def _reset_token_usage_location_cache():
    from src.core.session_token_usage.reader import reset_location_caches_for_tests

    reset_location_caches_for_tests()
    yield
    reset_location_caches_for_tests()


@pytest.fixture(scope="session", autouse=True)
def relay_publisher_never_starts() -> Iterator[Any]:
    try:
        from src.core import relay_publisher
    except SystemExit:
        yield None
        return

    real = relay_publisher.start_if_enabled
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(relay_publisher, "start_if_enabled", lambda *a, **k: None)
        yield real


@pytest.fixture(autouse=True)
def _real_relay_start_when_marked(
    request, monkeypatch, relay_publisher_never_starts: Any
) -> None:
    if relay_publisher_never_starts is None:
        return
    if request.node.get_closest_marker("real_relay_start") is not None:
        monkeypatch.setattr(
            "src.core.relay_publisher.start_if_enabled",
            relay_publisher_never_starts,
        )


@pytest.fixture(autouse=True)
def claude_session_registry_isolation(monkeypatch, tmp_path_factory) -> None:
    empty = tmp_path_factory.mktemp("claude_sessions_registry")
    monkeypatch.setattr(
        "src.core.attention.registry_read.default_registry_directory",
        lambda: str(empty),
    )
    monkeypatch.setattr(
        "src.core.claude_config.profile_roots._default_config_path",
        lambda: empty / "no-config.json",
    )
    from src.core.claude_config import profile_roots

    profile_roots.reset_profile_roots_cache_for_tests()


@pytest.fixture(scope="session", autouse=True)
def real_claude_settings_unchanged() -> Iterator[None]:
    target = Path.home() / ".claude" / "settings.json"

    def _fingerprint() -> tuple[str, str]:
        try:
            if not target.exists():
                return ("absent", "")
            return ("present", hashlib.sha256(target.read_bytes()).hexdigest())
        except OSError as exc:
            return ("unreadable", str(exc))

    before = _fingerprint()
    settings_write_recorder.install(target)
    try:
        yield
    finally:
        after = _fingerprint()
        write_seen = settings_write_recorder.write_was_recorded(target)
        settings_write_recorder.remove(target)
        verdict, message = settings_write_recorder.canary_verdict(before, after, write_seen)
        if verdict == "fail":
            raise AssertionError(message)
        if verdict == "warn":
            (sys.__stderr__ or sys.stderr).write(f"settings_canary: {message}\n")



@pytest.fixture
def app_services():
    from src.core.composition import build_services

    return build_services()



def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    try:
        from tests.jsonl_shape_support import not_evaluated_entries
    except ImportError:
        return
    entries = not_evaluated_entries()
    if not entries:
        return
    terminalreporter.write_sep("=", "COULD NOT EVALUATE", red=True, bold=True)
    terminalreporter.write_line(
        f"{len(entries)} guarantee(s) were NOT verified by this run. A pass "
        "above does not cover them."
    )
    for guarantee, reason in entries:
        terminalreporter.write_line(f"  NOT VERIFIED: {guarantee}")
        terminalreporter.write_line(f"    because: {reason}")



_SOCKET_GUARD_NAMES = frozenset(
    {
        "socket_guard",
        "TEST_SOCKET_NAME",
        "TEST_SOCKET_PREFIX",
        "FORBIDDEN_SOCKET_NAME",
        "TmuxSocketGuardError",
        "assert_safe_socket_name",
        "classify_tmux_argv",
        "derive_test_socket",
    }
)

_REAL_TMUX_FIXTURE = "tmux_test_socket"


def _drives_real_tmux(item) -> bool:
    if _REAL_TMUX_FIXTURE in getattr(item, "fixturenames", ()):
        return True
    module = getattr(item, "module", None)
    if module is None:
        return False
    return bool(_SOCKET_GUARD_NAMES & set(vars(module)))


_FULL_TIER_LIST = Path(__file__).resolve().parent / "full_tier_files.txt"


def _full_tier_files() -> frozenset[str]:
    lines = _FULL_TIER_LIST.read_text(encoding="utf-8").splitlines()
    return frozenset(
        line.strip() for line in lines if line.strip() and not line.startswith("#")
    )


def pytest_collection_modifyitems(config, items) -> None:
    full_tier = _full_tier_files()
    root = Path(str(config.rootpath))
    for item in items:
        if _drives_real_tmux(item):
            item.add_marker(pytest.mark.real_tmux)
        try:
            rel = Path(str(item.path)).relative_to(root).as_posix()
        except ValueError:
            continue
        if rel in full_tier:
            item.add_marker(pytest.mark.full_tier)


@pytest.fixture
def no_builtin_default_login(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.provider_ledger import poller_scan

    monkeypatch.setattr(poller_scan, "with_auto_default", lambda accounts, label=None: accounts)
