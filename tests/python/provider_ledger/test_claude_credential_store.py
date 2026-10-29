
from __future__ import annotations

import json
import os
import stat
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx
import pytest

from src.config.provider_accounts import ProviderAccount
from src.core.provider_ledger import (
    claude_store,
    claude_usage,
    credentials,
    keychain,
    poller_core,
    poller_poke,
    refresh_poke,
)
from src.core.sessions.agent_update import CLAUDE_INSTALL_CANDIDATES

SERVICE = "Claude Code-credentials"
USER = "fixture-user"
STALE_TOKEN = "sk-ant-oat01-FIXTURE-STALE"
LIVE_TOKEN = "sk-ant-oat01-FIXTURE-LIVE"
FILE_TOKEN = "sk-ant-oat01-FIXTURE-FILE"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _blob(token: str, expires_at: Optional[datetime]) -> str:
    oauth: Dict[str, object] = {
        "accessToken": token,
        "refreshToken": "sk-ant-ort01-FIXTURE-NOT-REAL",
        "scopes": ["user:inference", "user:profile"],
        "subscriptionType": "max",
    }
    if expires_at is not None:
        oauth["expiresAt"] = int(expires_at.timestamp() * 1000)
        oauth["refreshTokenExpiresAt"] = int((expires_at + timedelta(days=20)).timestamp() * 1000)
    return json.dumps({"claudeAiOauth": oauth})


class KeychainStub:

    def __init__(self, items: Dict[Tuple[str, Optional[str]], str]) -> None:
        self.items = items
        self.calls: List[List[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        service = argv[argv.index("-s") + 1]
        account = argv[argv.index("-a") + 1] if "-a" in argv else None
        document = self.items.get((service, account))
        if document is None:
            return subprocess.CompletedProcess(argv, 44, stdout="", stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout=document + "\n", stderr="")


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USER", USER)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    return tmp_path


def _install(monkeypatch, items) -> KeychainStub:
    stub = KeychainStub(items)
    monkeypatch.setattr(keychain.subprocess, "run", stub)
    return stub




def test_the_measured_incident_reads_claude_codes_own_item(home, monkeypatch) -> None:
    _install(monkeypatch, {
        (SERVICE, None): _blob(STALE_TOKEN, _now() - timedelta(days=20)),
        (SERVICE, "unknown"): _blob(STALE_TOKEN, _now() - timedelta(days=20)),
        (SERVICE, USER): _blob(LIVE_TOKEN, _now() + timedelta(hours=2)),
    })

    cred = credentials.read_claude_credential("~/.claude")

    assert cred is not None and cred.access_token == LIVE_TOKEN
    assert credentials.credential_state_for(cred, _now()) == "ok"


def test_a_live_own_item_skips_the_service_only_lookup(home, monkeypatch) -> None:
    stub = _install(monkeypatch, {(SERVICE, USER): _blob(LIVE_TOKEN, _now() + timedelta(hours=2))})

    credentials.read_claude_credential("~/.claude")

    assert all("-a" in call for call in stub.calls)


def test_no_own_item_falls_back_to_the_service_only_lookup(home, monkeypatch) -> None:
    _install(monkeypatch, {(SERVICE, None): _blob(LIVE_TOKEN, _now() + timedelta(hours=1))})

    cred = credentials.read_claude_credential("~/.claude")

    assert cred is not None and cred.access_token == LIVE_TOKEN


def test_a_fresher_credentials_file_beats_a_lapsed_keychain(home, monkeypatch) -> None:
    (home / ".claude").mkdir()
    (home / ".claude" / ".credentials.json").write_text(_blob(FILE_TOKEN, _now() + timedelta(hours=3)))
    _install(monkeypatch, {(SERVICE, USER): _blob(STALE_TOKEN, _now() - timedelta(hours=1))})

    cred = credentials.read_claude_credential("~/.claude")

    assert cred is not None and cred.source == "file" and cred.access_token == FILE_TOKEN


def test_a_stale_credentials_file_never_beats_a_live_keychain(home, monkeypatch) -> None:
    (home / ".claude").mkdir()
    (home / ".claude" / ".credentials.json").write_text(_blob(FILE_TOKEN, _now() - timedelta(days=3)))
    _install(monkeypatch, {(SERVICE, USER): _blob(LIVE_TOKEN, _now() + timedelta(hours=1))})

    cred = credentials.read_claude_credential("~/.claude")

    assert cred is not None and cred.source == "keychain"


def test_a_tie_keeps_the_first_candidate_and_no_expiry_never_displaces_one() -> None:
    moment = _now() + timedelta(hours=1)

    class C:
        def __init__(self, name, expires_at):
            self.name, self.expires_at, self.source = name, expires_at, "keychain"

    first, second, undated = C("a", moment), C("b", moment), C("c", None)
    assert claude_store.pick_freshest([None, first, second, undated]).name == "a"
    assert claude_store.pick_freshest([undated, first]).name == "a"
    assert claude_store.pick_freshest([None, None]) is None


def test_every_store_empty_is_none_and_reports_missing(home, monkeypatch) -> None:
    _install(monkeypatch, {})
    cred = credentials.read_claude_credential("~/.claude")
    assert cred is None
    assert credentials.credential_state_for(cred, _now()) == "missing"




def test_the_account_is_user_when_set(monkeypatch) -> None:
    monkeypatch.setenv("USER", "someone.else_1")
    assert claude_store.claude_keychain_account() == "someone.else_1"


def test_the_account_falls_back_to_the_login_name(monkeypatch) -> None:
    import pwd

    monkeypatch.delenv("USER", raising=False)
    assert claude_store.claude_keychain_account() == pwd.getpwuid(os.getuid()).pw_name


def test_a_name_outside_the_rule_becomes_claude_code_user(monkeypatch) -> None:
    monkeypatch.setenv("USER", "has space")
    assert claude_store.claude_keychain_account() == claude_store.CLAUDE_FALLBACK_ACCOUNT




def _fake_claude(path: Path, executable: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    mode = stat.S_IRUSR | stat.S_IWUSR | (stat.S_IXUSR if executable else 0)
    path.chmod(mode)
    return path


def test_a_minimal_path_still_finds_the_native_install(home, monkeypatch) -> None:
    monkeypatch.delenv(refresh_poke.TEST_MODE_ENV, raising=False)
    empty = home / "emptybin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    installed = _fake_claude(home / ".local" / "bin" / "claude")

    assert refresh_poke.resolve_claude_binary() == str(installed)
    assert CLAUDE_INSTALL_CANDIDATES[0] == "~/.local/bin/claude"


def test_path_still_wins_when_it_has_an_answer(home, monkeypatch) -> None:
    monkeypatch.delenv(refresh_poke.TEST_MODE_ENV, raising=False)
    on_path = _fake_claude(home / "pathbin" / "claude")
    _fake_claude(home / ".local" / "bin" / "claude")
    monkeypatch.setenv("PATH", str(on_path.parent))

    assert refresh_poke.resolve_claude_binary() == str(on_path)


def test_a_non_executable_install_is_skipped_not_run(home, monkeypatch) -> None:
    monkeypatch.delenv(refresh_poke.TEST_MODE_ENV, raising=False)
    monkeypatch.setenv("PATH", str(home / "nothing"))
    _fake_claude(home / ".local" / "bin" / "claude", executable=False)

    assert refresh_poke.resolve_binary("claude", ("~/.local/bin/claude", "relative/claude")) is None


def test_the_suite_marker_still_disables_the_fallbacks(home, monkeypatch) -> None:
    monkeypatch.setenv(refresh_poke.TEST_MODE_ENV, "1")
    _fake_claude(home / ".local" / "bin" / "claude")
    assert refresh_poke.resolve_claude_binary() is None




@pytest.mark.asyncio
@pytest.mark.parametrize(
    "own_expiry",
    [timedelta(hours=2), timedelta(minutes=2), timedelta(minutes=-5)],
    ids=["live", "inside_refresh_window", "lapsed"],
)
async def test_a_poller_pass_never_refreshes_and_never_writes(home, monkeypatch, own_expiry) -> None:
    stub = _install(monkeypatch, {
        (SERVICE, None): _blob(STALE_TOKEN, _now() - timedelta(days=20)),
        (SERVICE, USER): _blob(LIVE_TOKEN, _now() + own_expiry),
    })
    requests: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"five_hour": {"utilization": 12}, "seven_day": {"utilization": 34}})

    poller = poller_core.LedgerPoller(
        config_path=lambda: home / "config.json",
        list_accounts=lambda path: [],
        claude_fetch=claude_usage.fetch_usage,
        poker=poller_poke.RefreshPoker(claude_binary=None),
    )
    poller._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        await poller.run_pass()
    finally:
        await poller._client.aclose()

    assert all(call[:2] == ["security", "find-generic-password"] for call in stub.calls)
    assert all(str(r.url) == claude_usage.USAGE_URL and r.method == "GET" for r in requests)
    row = poller.snapshot().accounts[0]
    if own_expiry > timedelta(0):
        assert row.credential_state == "ok"
        assert len(requests) == 1
        assert requests[0].headers["Authorization"] == f"Bearer {LIVE_TOKEN}"
        assert {w.kind for w in row.windows} >= {"five_hour", "seven_day"}
    else:
        assert row.credential_state == "expired"
        assert requests == []
