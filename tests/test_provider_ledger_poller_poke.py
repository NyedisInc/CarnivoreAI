
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import structlog

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pkp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pkp_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.config.provider_accounts import ProviderAccount
from src.core.provider_ledger import poller as poller_module
from src.core.provider_ledger import poller_poke, refresh_guard, refresh_poke
from src.core.provider_ledger.credentials import ClaudeCredential
from src.models.provider_ledger import FetchOutcome, UsageWindow

pytestmark = pytest.mark.usefixtures("no_builtin_default_login")

NOW = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)

LEAD = timedelta(seconds=refresh_guard.PRE_EXPIRY_LEAD_SECONDS)

TOKEN = "sk-ant-oat01-NEVER-LOG-THIS-VALUE"

BINARY = "/opt/homebrew/bin/claude"


def claude_account(
    account_id: str = "max-main", config_dir: str = "~/.claude-test"
) -> ProviderAccount:
    return ProviderAccount(
        id=account_id, name="Max main", provider="claude", claude_config_dir=config_dir
    )


def codex_account() -> ProviderAccount:
    return ProviderAccount(
        id="codex-main", name="Codex main", provider="codex", codex_home="~/.codex-test"
    )


def claude_credential(
    *,
    expires_at: datetime,
    refresh_token_expires_at: Optional[datetime] = NOW + timedelta(days=29),
    access_token: str = TOKEN,
    has_refresh_token: bool = False,
) -> ClaudeCredential:
    return ClaudeCredential(
        access_token=access_token,
        expires_at=expires_at,
        refresh_token_expires_at=refresh_token_expires_at,
        scopes=("user:inference", "user:profile"),
        subscription_type="max",
        rate_limit_tier="default_claude_max_20x",
        source="keychain",
        has_refresh_token=has_refresh_token,
    )


def due_credential(**overrides: Any) -> ClaudeCredential:
    return claude_credential(expires_at=NOW + timedelta(minutes=3), **overrides)


def expired_credential(refresh_deadline: Optional[datetime] = None) -> ClaudeCredential:
    return claude_credential(
        expires_at=NOW - timedelta(minutes=35),
        refresh_token_expires_at=(
            refresh_deadline if refresh_deadline is not None else NOW + timedelta(days=29)
        ),
    )


def refreshed_credential(hours: float = 8.0) -> ClaudeCredential:
    return claude_credential(expires_at=NOW + timedelta(hours=hours))


def ok_outcome() -> FetchOutcome:
    return FetchOutcome(
        state="ok",
        plan="max",
        windows=[UsageWindow(kind="five_hour", label="5h", used_pct=42.0)],
    )


def ran(exit_code: int = 0, *, timed_out: bool = False) -> refresh_poke.PokeOutcome:
    return refresh_poke.PokeOutcome(
        ran=True,
        exit_code=None if timed_out else exit_code,
        timed_out=timed_out,
        duration_seconds=1.1,
    )


class FakeClock:

    def __init__(self, start: datetime = NOW) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


class CredentialSource:

    def __init__(self, credential: Any) -> None:
        self.credential = credential

    def __call__(self, config_dir: str) -> Any:
        return self.credential


class FakePoke:

    def __init__(
        self,
        outcomes: Optional[List[refresh_poke.PokeOutcome]] = None,
        *,
        on_run: Any = None,
        delay: float = 0.0,
    ) -> None:
        self.outcomes = list(outcomes or [ran(0)])
        self.on_run = on_run
        self.delay = delay
        self.calls: List[Dict[str, Any]] = []

    async def __call__(self, argv, env, *, timeout=None) -> refresh_poke.PokeOutcome:
        self.calls.append({"argv": list(argv), "env": dict(env), "timeout": timeout})
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.on_run is not None:
            self.on_run()
        if len(self.outcomes) > 1:
            return self.outcomes.pop(0)
        return self.outcomes[0]


class FakeBusy:

    def __init__(self, answer: Optional[str] = None) -> None:
        self.answer = answer
        self.profiles: List[Optional[str]] = []

    def __call__(self, profile: Optional[str]) -> Optional[str]:
        self.profiles.append(profile)
        return self.answer


class FakeFetcher:

    def __init__(self) -> None:
        self.calls: List[Any] = []

    async def __call__(self, client, access_token, account_id=None) -> FetchOutcome:
        self.calls.append(access_token)
        return ok_outcome()


def build_poller(
    accounts: List[ProviderAccount],
    *,
    clock: Optional[FakeClock] = None,
    source: Optional[CredentialSource] = None,
    poke: Any = None,
    busy: Optional[FakeBusy] = None,
    binary: Optional[str] = BINARY,
    fetch: Optional[FakeFetcher] = None,
    codex_credential: Any = None,
    probe: Any = None,
    keepalive: bool = True,
) -> poller_module.LedgerPoller:
    clock = clock or FakeClock()
    source = source or CredentialSource(due_credential())
    return poller_module.LedgerPoller(
        config_path=lambda: Path("/nonexistent/config.json"),
        list_accounts=lambda path: list(accounts),
        clock=clock,
        random_unit=lambda: 0.5,
        claude_fetch=fetch or FakeFetcher(),
        codex_fetch=fetch or FakeFetcher(),
        read_claude_credential=source,
        read_claude_identity=lambda config_dir: None,
        read_codex_credential=lambda codex_home: codex_credential,
        client_factory=lambda: None,
        poker=poller_poke.RefreshPoker(
            claude_binary=binary,
            run=poke if poke is not None else FakePoke(),
            busy=busy if busy is not None else FakeBusy(),
            clock=clock,
            probe=probe,
            keepalive=keepalive,
        ),
    )


def row(snapshot, account_id: str):
    for account in snapshot.accounts:
        if account.id == account_id:
            return account
    return None


def state_of(poller: poller_module.LedgerPoller, account_id: str = "max-main"):
    return poller._states[account_id]


class TestTheScheduleFiresAtExpiryMinusTheLead:

    def test_the_lead_is_four_minutes(self) -> None:
        assert refresh_guard.PRE_EXPIRY_LEAD_SECONDS == 240.0

    @pytest.mark.asyncio
    async def test_not_a_second_early_and_on_the_dot(self) -> None:
        clock = FakeClock()
        expires = NOW + timedelta(hours=2)
        source = CredentialSource(claude_credential(expires_at=expires))
        poke = FakePoke(on_run=lambda: setattr(source, "credential", refreshed_credential(10)))
        poller = build_poller([claude_account()], clock=clock, source=source, poke=poke)

        await poller.run_pass()
        assert poke.calls == []
        assert state_of(poller).refresh_check_at == expires - LEAD

        clock.now = expires - LEAD - timedelta(seconds=1)
        await poller.run_pass()
        assert poke.calls == []

        clock.now = expires - LEAD
        await poller.run_pass()
        assert len(poke.calls) == 1
        answer = row(poller.snapshot(), "max-main")
        assert answer.credential_state == "ok"
        assert answer.poke.state == "idle"

    @pytest.mark.asyncio
    async def test_the_refresh_check_sends_no_usage_request(self) -> None:
        clock = FakeClock()
        source = CredentialSource(claude_credential(expires_at=NOW + LEAD + timedelta(seconds=60)))
        poke = FakePoke(on_run=lambda: setattr(source, "credential", refreshed_credential()))
        fetch = FakeFetcher()
        poller = build_poller(
            [claude_account()], clock=clock, source=source, poke=poke, fetch=fetch
        )

        await poller.run_pass()
        assert len(fetch.calls) == 1
        next_usage = state_of(poller).next_poll_at

        clock.advance(60.0)
        await poller.run_pass()

        assert len(poke.calls) == 1
        assert len(fetch.calls) == 1
        assert state_of(poller).next_poll_at == next_usage

    @pytest.mark.asyncio
    async def test_the_child_is_pointed_at_this_accounts_own_profile(self) -> None:
        poke = FakePoke()
        poller = build_poller([claude_account()], poke=poke)

        await poller.run_pass()

        env = poke.calls[0]["env"]
        assert env["CLAUDE_CONFIG_DIR"].endswith(".claude-test")
        assert poke.calls[0]["argv"][:3] == [BINARY, "-p", "ok"]
        assert "doctor" not in poke.calls[0]["argv"]

    @pytest.mark.asyncio
    async def test_the_poke_gets_the_generous_bound_not_thirty_seconds(self) -> None:
        poke = FakePoke()
        poller = build_poller([claude_account()], poke=poke)

        await poller.run_pass()

        assert poke.calls[0]["timeout"] == refresh_poke.POKE_TIMEOUT_SECONDS
        assert refresh_poke.POKE_TIMEOUT_SECONDS > 30.0

    @pytest.mark.asyncio
    async def test_the_default_profile_is_poked_with_the_variable_unset(self) -> None:
        poke = FakePoke()
        poller = build_poller([claude_account(config_dir="~/.claude")], poke=poke)

        await poller.run_pass()

        assert "CLAUDE_CONFIG_DIR" not in poke.calls[0]["env"]


class TestAnExpiredTokenIsNeverPoked:

    @pytest.mark.asyncio
    async def test_expired_at_first_sight_does_not_auto_refresh(self) -> None:
        poke = FakePoke()
        poller = build_poller(
            [claude_account()], source=CredentialSource(expired_credential()), poke=poke
        )

        await poller.run_pass()

        assert poke.calls == []
        answer = row(poller.snapshot(), "max-main")
        assert answer.credential_state == "expired"
        assert answer.error == "expired"
        assert answer.poke is None

    @pytest.mark.asyncio
    async def test_a_login_past_its_refresh_deadline_says_so(self) -> None:
        poller = build_poller(
            [claude_account()],
            source=CredentialSource(expired_credential(NOW - timedelta(hours=1))),
        )

        await poller.run_pass()

        assert row(poller.snapshot(), "max-main").error == refresh_poke.LOGIN_EXPIRED

    @pytest.mark.asyncio
    async def test_a_codex_account_is_never_poked(self) -> None:
        poke = FakePoke()
        poller = build_poller([codex_account()], poke=poke, codex_credential=None)

        await poller.run_pass()

        assert poke.calls == []

    @pytest.mark.asyncio
    async def test_a_healthy_token_hours_from_expiry_is_not_poked(self) -> None:
        poke = FakePoke()
        poller = build_poller(
            [claude_account()],
            source=CredentialSource(refreshed_credential(4)),
            poke=poke,
        )

        await poller.run_pass()

        assert poke.calls == []


def revivable(**overrides: Any) -> ClaudeCredential:
    return claude_credential(
        expires_at=NOW - timedelta(minutes=35), has_refresh_token=True, **overrides
    )


class FakeProbe:

    def __init__(self, state: str) -> None:
        self.state = state
        self.tokens: List[str] = []

    async def __call__(self, access_token: str) -> str:
        self.tokens.append(access_token)
        return self.state


class TestThereIsNoRevivePoke:

    @pytest.mark.asyncio
    async def test_an_expired_token_with_a_refresh_token_is_left_alone(self) -> None:
        poke = FakePoke()
        poller = build_poller(
            [claude_account()], source=CredentialSource(revivable()), poke=poke
        )

        await poller.run_pass()

        assert poke.calls == []
        assert row(poller.snapshot(), "max-main").credential_state == "expired"

    def test_the_revive_entry_points_are_gone(self) -> None:
        assert not hasattr(poller_poke.RefreshPoker, "post_expiry")
        assert not hasattr(poller_module.LedgerPoller, "_auto_revive_enabled")


class TestAnUnmovedPokeIsProbedOnceWithTheCurrentToken:

    @pytest.mark.asyncio
    async def test_a_401_marks_needs_login_and_no_claude_runs_again(self) -> None:
        clock = FakeClock()
        poke = FakePoke([ran(0)])
        probe = FakeProbe("expired")
        poller = build_poller(
            [claude_account()], clock=clock, poke=poke, probe=probe
        )

        await poller.run_pass()
        for _ in range(12):
            clock.advance(20.0)
            await poller.run_pass()

        assert len(poke.calls) == 1
        assert probe.tokens == [TOKEN]
        answer = row(poller.snapshot(), "max-main")
        assert answer.poke.state == "needs_login"
        assert answer.poke.error == refresh_poke.NEEDS_LOGIN

    @pytest.mark.asyncio
    async def test_a_fresh_login_clears_needs_login(self) -> None:
        source = CredentialSource(due_credential())
        poke = FakePoke([ran(0)])
        poller = build_poller(
            [claude_account()], source=source, poke=poke, probe=FakeProbe("expired")
        )
        await poller.run_pass()
        assert state_of(poller).poke_state == "needs_login"

        source.credential = refreshed_credential()
        poller._poll_soon.add("max-main")
        await poller.run_pass()

        assert state_of(poller).poke_state == "idle"

    @pytest.mark.asyncio
    async def test_a_200_retries_on_a_later_pass_still_before_expiry(self) -> None:
        clock = FakeClock()
        poke = FakePoke([ran(0)])
        probe = FakeProbe("ok")
        poller = build_poller(
            [claude_account()], clock=clock, poke=poke, probe=probe
        )

        await poller.run_pass()
        assert len(poke.calls) == 1
        assert state_of(poller).refresh_check_at == NOW + timedelta(seconds=60)
        clock.advance(61.0)
        await poller.run_pass()

        assert len(poke.calls) == 2
        assert row(poller.snapshot(), "max-main").poke.state != "needs_login"

    @pytest.mark.asyncio
    async def test_a_probe_error_is_failed_and_not_retried(self) -> None:
        clock = FakeClock()
        poke = FakePoke([ran(0)])
        poller = build_poller(
            [claude_account()], clock=clock, poke=poke, probe=FakeProbe("error")
        )

        await poller.run_pass()
        for _ in range(8):
            clock.advance(20.0)
            await poller.run_pass()

        assert len(poke.calls) == 1
        assert row(poller.snapshot(), "max-main").poke.state == "failed"

    @pytest.mark.asyncio
    async def test_a_moved_expiry_sends_no_probe(self) -> None:
        source = CredentialSource(due_credential())
        poke = FakePoke(on_run=lambda: setattr(source, "credential", refreshed_credential()))
        probe = FakeProbe("expired")
        poller = build_poller([claude_account()], source=source, poke=poke, probe=probe)

        await poller.run_pass()

        assert probe.tokens == []
        assert row(poller.snapshot(), "max-main").poke.state == "idle"


class TestTheKeepaliveSwitch:

    @pytest.mark.asyncio
    async def test_switched_off_never_spawns_and_never_probes(self) -> None:
        poke = FakePoke()
        probe = FakeProbe("ok")
        poller = build_poller(
            [claude_account()], poke=poke, probe=probe, keepalive=False
        )

        await poller.run_pass()

        assert poke.calls == [] and probe.tokens == []
        assert row(poller.snapshot(), "max-main").credential_state == "ok"

    def test_the_default_follows_the_setting_and_a_slot_env_turns_it_off(self, monkeypatch) -> None:
        from src.config.settings import Settings

        monkeypatch.setenv("CARNIVORE_LEDGER_KEEPALIVE", "0")
        assert Settings().ledger_keepalive is False
        monkeypatch.delenv("CARNIVORE_LEDGER_KEEPALIVE")
        assert Settings().ledger_keepalive is True


class TestSuccessIsTheExpiryMovingAndNothingElse:

    @pytest.mark.asyncio
    async def test_a_poke_that_exits_zero_without_moving_the_expiry_failed(self) -> None:
        poller = build_poller([claude_account()], poke=FakePoke([ran(0)]))

        with structlog.testing.capture_logs() as captured:
            await poller.run_pass()

        finished = [r for r in captured if r.get("event") == "provider_ledger_poke_finished"]
        assert finished[0]["exit_code"] == 0
        assert finished[0]["moved"] is False
        assert finished[0]["outcome"] == "failed"
        answer = row(poller.snapshot(), "max-main")
        assert answer.credential_state == "ok"
        assert answer.poke.state == "failed"
        assert answer.poke.error == refresh_poke.POKE_NO_REFRESH

    @pytest.mark.asyncio
    async def test_a_non_zero_exit_carries_its_own_reason(self) -> None:
        poller = build_poller([claude_account()], poke=FakePoke([ran(1)]))

        await poller.run_pass()

        assert row(poller.snapshot(), "max-main").poke.error == refresh_poke.POKE_EXIT_NONZERO

    @pytest.mark.asyncio
    async def test_a_poke_that_timed_out_is_unknown_not_failed(self) -> None:
        poller = build_poller([claude_account()], poke=FakePoke([ran(0, timed_out=True)]))

        await poller.run_pass()

        answer = row(poller.snapshot(), "max-main")
        assert answer.poke.state == "unknown"
        assert answer.poke.error == refresh_poke.POKE_TIMED_OUT

    @pytest.mark.asyncio
    async def test_a_timeout_that_did_move_the_expiry_is_a_success(self) -> None:
        source = CredentialSource(due_credential())
        poke = FakePoke(
            [ran(0, timed_out=True)],
            on_run=lambda: setattr(source, "credential", refreshed_credential()),
        )
        poller = build_poller([claude_account()], source=source, poke=poke)

        await poller.run_pass()

        assert row(poller.snapshot(), "max-main").poke.state == "idle"

    @pytest.mark.asyncio
    async def test_a_poke_that_left_the_store_empty_reads_missing_at_once(self) -> None:
        source = CredentialSource(due_credential())
        poke = FakePoke(on_run=lambda: setattr(source, "credential", None))
        poller = build_poller([claude_account()], source=source, poke=poke)

        await poller.run_pass()

        assert row(poller.snapshot(), "max-main").credential_state == "missing"


class TestNothingIsEverRetried:

    @pytest.mark.asyncio
    async def test_no_retry_after_a_failure_inside_the_window_or_after_expiry(
        self,
    ) -> None:
        clock = FakeClock()
        poke = FakePoke([ran(0)])
        poller = build_poller([claude_account()], clock=clock, poke=poke)

        await poller.run_pass()
        assert state_of(poller).refresh_check_at == NOW + timedelta(minutes=3)
        for _ in range(8):
            clock.advance(20.0)
            await poller.run_pass()
        assert len(poke.calls) == 1
        clock.now = NOW + timedelta(minutes=3)
        await poller.run_pass()

        assert len(poke.calls) == 1
        answer = row(poller.snapshot(), "max-main")
        assert answer.credential_state == "expired"
        assert answer.error == refresh_poke.POKE_NO_REFRESH
        assert answer.poke.state == "failed"

    @pytest.mark.asyncio
    async def test_unknown_on_timeout_does_not_retry(self) -> None:
        clock = FakeClock()
        poke = FakePoke([ran(0, timed_out=True)])
        poller = build_poller([claude_account()], clock=clock, poke=poke)

        await poller.run_pass()
        for _ in range(8):
            clock.advance(20.0)
            await poller.run_pass()

        assert len(poke.calls) == 1
        assert row(poller.snapshot(), "max-main").poke.state == "unknown"

    @pytest.mark.asyncio
    async def test_a_runner_that_raises_is_recorded_and_not_retried(self) -> None:
        calls: List[int] = []

        async def explode(argv, env, *, timeout=None):
            calls.append(1)
            raise RuntimeError("the spawn layer failed")

        clock = FakeClock()
        poller = build_poller([claude_account()], clock=clock, poke=explode)

        with pytest.raises(RuntimeError):
            await poller.run_pass()
        clock.advance(20.0)
        await poller.run_pass()

        assert len(calls) == 1
        answer = row(poller.snapshot(), "max-main")
        assert answer.poke.state == "failed"
        assert answer.poke.error == refresh_poke.POKE_ERRORED

    @pytest.mark.asyncio
    async def test_a_transient_empty_read_is_not_a_repaired_login(self) -> None:
        clock = FakeClock()
        source = CredentialSource(due_credential())
        poke = FakePoke([ran(0)])
        poller = build_poller([claude_account()], clock=clock, source=source, poke=poke)

        await poller.run_pass()
        source.credential = None
        clock.advance(20.0)
        await poller.run_pass()
        source.credential = due_credential()
        clock.advance(20.0)
        await poller.run_pass()

        assert len(poke.calls) == 1
        assert row(poller.snapshot(), "max-main").poke.state == "failed"

    @pytest.mark.asyncio
    async def test_a_fresh_login_retires_the_record_and_gets_its_own_attempt(
        self,
    ) -> None:
        clock = FakeClock()
        source = CredentialSource(due_credential())
        poke = FakePoke([ran(0)])
        poller = build_poller([claude_account()], clock=clock, source=source, poke=poke)
        await poller.run_pass()
        assert len(poke.calls) == 1

        new_expiry = NOW + timedelta(hours=8)
        source.credential = claude_credential(expires_at=new_expiry)
        clock.advance(200.0)
        await poller.run_pass()
        assert row(poller.snapshot(), "max-main").poke.state == "idle"

        clock.now = new_expiry - LEAD
        await poller.run_pass()
        assert len(poke.calls) == 2


class TestStandingAsideWhileClaudeCodeIsBusy:

    @pytest.mark.asyncio
    async def test_a_live_claude_under_the_profile_skips_and_rechecks_soon(
        self,
    ) -> None:
        clock = FakeClock()
        busy = FakeBusy(refresh_guard.BUSY_CLAUDE_RUNNING)
        poke = FakePoke()
        poller = build_poller([claude_account()], clock=clock, poke=poke, busy=busy)

        await poller.run_pass()
        assert poke.calls == []
        recheck = state_of(poller).refresh_check_at
        assert recheck == NOW + timedelta(seconds=refresh_guard.BUSY_RECHECK_SECONDS)

        busy.answer = None
        clock.now = recheck
        await poller.run_pass()
        assert len(poke.calls) == 1

    @pytest.mark.asyncio
    async def test_a_held_refresh_lock_skips_too(self) -> None:
        poke = FakePoke()
        poller = build_poller(
            [claude_account()], poke=poke, busy=FakeBusy(refresh_guard.BUSY_REFRESH_LOCK)
        )

        await poller.run_pass()

        assert poke.calls == []
        assert row(poller.snapshot(), "max-main").poke is None

    @pytest.mark.asyncio
    async def test_the_recheck_never_lands_after_expiry(self) -> None:
        poller = build_poller(
            [claude_account()],
            source=CredentialSource(claude_credential(expires_at=NOW + timedelta(seconds=20))),
            busy=FakeBusy(refresh_guard.BUSY_CLAUDE_RUNNING),
        )

        await poller.run_pass()

        assert state_of(poller).refresh_check_at is None

    @pytest.mark.asyncio
    async def test_the_guard_is_asked_about_the_exported_profile(self) -> None:
        busy = FakeBusy()
        poller = build_poller([claude_account(config_dir="~/.claude")], busy=busy)
        await poller.run_pass()
        assert busy.profiles == [None]

        busy = FakeBusy()
        poller = build_poller([claude_account()], busy=busy)
        await poller.run_pass()
        assert busy.profiles[0].endswith(".claude-test")
        assert os.path.isabs(busy.profiles[0])

    @pytest.mark.asyncio
    async def test_no_claude_on_this_machine_names_it(self) -> None:
        poke = FakePoke()
        poller = build_poller([claude_account()], poke=poke, binary=None)

        await poller.run_pass()

        assert poke.calls == []
        assert row(poller.snapshot(), "max-main").poke.error == refresh_poke.POKE_BINARY_MISSING


class TestTheClockIsReReadRightBeforeTheSpawn:

    @pytest.mark.asyncio
    async def test_a_later_account_that_expired_during_an_earlier_poke_is_not_poked(
        self,
    ) -> None:
        clock = FakeClock()
        by_dir = {
            "one": due_credential(),
            "two": claude_credential(expires_at=NOW + timedelta(minutes=2)),
        }

        def source(config_dir: str) -> Any:
            return by_dir["one" if config_dir.endswith("one") else "two"]

        def slow_refresh() -> None:
            by_dir["one"] = refreshed_credential()
            clock.advance(130.0)

        poke = FakePoke(on_run=slow_refresh)
        poller = build_poller(
            [
                claude_account(account_id="max-one", config_dir="~/.claude-one"),
                claude_account(account_id="max-two", config_dir="~/.claude-two"),
            ],
            clock=clock,
            source=source,
            poke=poke,
        )

        await poller.run_pass()

        assert len(poke.calls) == 1
        assert poke.calls[0]["env"]["CLAUDE_CONFIG_DIR"].endswith(".claude-one")
        assert row(poller.snapshot(), "max-two").poke is None

        clock.advance(5.0)
        await poller.run_pass()
        assert len(poke.calls) == 1
        assert row(poller.snapshot(), "max-two").credential_state == "expired"

    @pytest.mark.asyncio
    async def test_a_token_seconds_from_expiry_at_spawn_time_is_not_poked(self) -> None:
        left = poller_poke.MIN_REMAINING_AT_SPAWN_SECONDS - 1
        poke = FakePoke()
        poller = build_poller(
            [claude_account()],
            source=CredentialSource(claude_credential(expires_at=NOW + timedelta(seconds=left))),
            poke=poke,
        )

        await poller.run_pass()

        assert poke.calls == []


class TestOnlyOnePokePerProfileAtATime:

    @pytest.mark.asyncio
    async def test_two_overlapping_passes_run_one_poke(self) -> None:
        poke = FakePoke(delay=0.02)
        poller = build_poller([claude_account()], poke=poke)

        await asyncio.gather(poller.run_pass(), poller.run_pass())

        assert len(poke.calls) == 1

    @pytest.mark.asyncio
    async def test_two_accounts_on_one_profile_directory_share_the_lock(self) -> None:
        poke = FakePoke(delay=0.02)
        poller = build_poller(
            [
                claude_account(account_id="max-one", config_dir="~/.claude-shared"),
                claude_account(account_id="max-two", config_dir="~/.claude-shared"),
            ],
            poke=poke,
        )

        await asyncio.gather(poller.run_pass(), poller.run_pass())

        assert len(poke.calls) == 1

    @pytest.mark.asyncio
    async def test_two_accounts_on_different_directories_both_poke(self) -> None:
        poke = FakePoke(delay=0.02)
        poller = build_poller(
            [
                claude_account(account_id="max-one", config_dir="~/.claude-one"),
                claude_account(account_id="max-two", config_dir="~/.claude-two"),
            ],
            poke=poke,
        )

        await poller.run_pass()

        assert len(poke.calls) == 2


class TestWhatTheRowAndTheLogCarry:

    @pytest.mark.asyncio
    async def test_the_login_deadline_reaches_a_healthy_row(self) -> None:
        deadline = NOW + timedelta(days=29)
        source = CredentialSource(
            claude_credential(expires_at=NOW + timedelta(hours=4), refresh_token_expires_at=deadline)
        )
        poller = build_poller([claude_account()], source=source)

        await poller.run_pass()

        assert row(poller.snapshot(), "max-main").login_expires_at == deadline

    @pytest.mark.asyncio
    async def test_a_store_that_named_no_deadline_publishes_none(self) -> None:
        source = CredentialSource(
            claude_credential(expires_at=NOW + timedelta(hours=4), refresh_token_expires_at=None)
        )
        poller = build_poller([claude_account()], source=source)

        await poller.run_pass()

        assert row(poller.snapshot(), "max-main").login_expires_at is None

    @pytest.mark.asyncio
    async def test_each_attempt_is_logged_with_its_outcome_and_never_a_token(
        self,
    ) -> None:
        fresh_token = "sk-ant-oat01-FRESH-NEVER-LOG"
        source = CredentialSource(due_credential())
        poke = FakePoke(
            on_run=lambda: setattr(
                source,
                "credential",
                claude_credential(expires_at=NOW + timedelta(hours=8), access_token=fresh_token),
            )
        )
        poller = build_poller([claude_account()], source=source, poke=poke)

        with structlog.testing.capture_logs() as captured:
            await poller.run_pass()

        finished = [r for r in captured if r.get("event") == "provider_ledger_poke_finished"]
        assert len(finished) == 1
        assert finished[0]["account_id"] == "max-main"
        assert finished[0]["outcome"] == "refreshed"
        assert finished[0]["moved"] is True
        for key in ("duration_seconds", "exit_code", "stdout_bytes", "output_signals"):
            assert key in finished[0]
        text = repr(captured)
        assert TOKEN not in text
        assert fresh_token not in text
        assert "sk-ant-" not in text

    @pytest.mark.asyncio
    async def test_a_skip_is_logged_with_its_reason(self) -> None:
        poller = build_poller(
            [claude_account()], busy=FakeBusy(refresh_guard.BUSY_CLAUDE_RUNNING)
        )

        with structlog.testing.capture_logs() as captured:
            await poller.run_pass()

        skipped = [r for r in captured if r.get("event") == "provider_ledger_poke_skipped"]
        assert skipped and skipped[0]["reason"] == refresh_guard.BUSY_CLAUDE_RUNNING
        assert "sk-ant-" not in repr(captured)


class TestTheBusyGuardReadsOnlyThrowawayDirectories:

    def test_an_empty_profile_is_not_busy(self, tmp_path: Path) -> None:
        assert refresh_guard.busy_reason(str(tmp_path / "profile")) is None

    def test_a_registered_live_claude_is_busy(self, tmp_path: Path, monkeypatch) -> None:
        profile = tmp_path / "profile"
        (profile / "sessions").mkdir(parents=True)
        (profile / "sessions" / f"{os.getpid()}.json").write_text("{}")
        monkeypatch.setattr(refresh_guard, "_pid_config_dir", lambda pid: str(profile.resolve()))

        assert refresh_guard.busy_reason(str(profile)) == refresh_guard.BUSY_CLAUDE_RUNNING

    def test_a_shared_registry_only_counts_this_profiles_own_claude(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        shared = tmp_path / "shared"
        shared.mkdir()
        (shared / f"{os.getpid()}.json").write_text("{}")
        mine, other = tmp_path / "mine", tmp_path / "other"
        mine.mkdir()
        (mine / "sessions").symlink_to(shared)
        owner = {"v": str(other.resolve())}
        monkeypatch.setattr(refresh_guard, "_pid_config_dir", lambda pid: owner["v"])
        assert refresh_guard.busy_reason(str(mine)) is None
        owner["v"] = str(mine.resolve())
        assert refresh_guard.busy_reason(str(mine)) == refresh_guard.BUSY_CLAUDE_RUNNING
        owner["v"] = None
        assert refresh_guard.busy_reason(str(mine)) == refresh_guard.BUSY_CLAUDE_RUNNING

    def test_pid_config_dir_reads_this_processes_env(self, monkeypatch) -> None:
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/tmp")
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
        try:
            assert refresh_guard._pid_config_dir(child.pid) == os.path.realpath("/tmp")
        finally:
            child.kill()
            child.wait()

    def test_a_registration_whose_pid_is_gone_is_not(self, tmp_path: Path) -> None:
        child = subprocess.Popen(["/usr/bin/true"])
        child.wait()
        profile = tmp_path / "profile"
        (profile / "sessions").mkdir(parents=True)
        (profile / "sessions" / f"{child.pid}.json").write_text("{}")

        assert refresh_guard.busy_reason(str(profile)) is None

    def test_a_fresh_refresh_lock_is_busy_and_a_stale_one_is_not(
        self, tmp_path: Path
    ) -> None:
        profile = tmp_path / "profile"
        lock = profile / refresh_guard.REFRESH_LOCK_NAME
        lock.mkdir(parents=True)
        assert refresh_guard.busy_reason(str(profile)) == refresh_guard.BUSY_REFRESH_LOCK

        old = time.time() - refresh_guard.LOCK_FRESH_SECONDS - 5
        os.utime(lock, (old, old))
        assert refresh_guard.busy_reason(str(profile)) is None

    def test_the_legacy_sibling_lock_is_busy_too(self, tmp_path: Path) -> None:
        profile = tmp_path / "profile"
        profile.mkdir()
        (tmp_path / "profile.lock").mkdir()

        assert refresh_guard.busy_reason(str(profile)) == refresh_guard.BUSY_REFRESH_LOCK


class TestDroppingAProfileLockWhenAnAccountGoes:

    def test_an_idle_profiles_lock_is_dropped(self):
        poker = poller_poke.RefreshPoker(claude_binary="/fake/claude")
        account = claude_account()
        poker._lock_for(account)

        poker.forget_profile(account)

        assert poker._locks == {}

    @pytest.mark.asyncio
    async def test_a_lock_that_is_held_is_left_exactly_where_it_is(self):
        poker = poller_poke.RefreshPoker(claude_binary="/fake/claude")
        account = claude_account()
        lock = poker._lock_for(account)

        async with lock:
            poker.forget_profile(account)

        assert poker._lock_for(account) is lock

    def test_a_profile_no_lock_was_ever_taken_for_is_not_an_error(self):
        poker = poller_poke.RefreshPoker(claude_binary="/fake/claude")

        poker.forget_profile(claude_account())

        assert poker._locks == {}

    def test_another_profiles_lock_is_untouched(self):
        poker = poller_poke.RefreshPoker(claude_binary="/fake/claude")
        mine = claude_account()
        theirs = claude_account("other", "~/.claude-other")
        kept = poker._lock_for(theirs)
        poker._lock_for(mine)

        poker.forget_profile(mine)

        assert poker._lock_for(theirs) is kept
