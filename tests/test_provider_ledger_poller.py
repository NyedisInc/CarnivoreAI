
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
import structlog

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_plp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_plp_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.config.provider_accounts import ProviderAccount
from src.core.provider_ledger import poller as poller_module
from src.core.provider_ledger import poller_state
from src.core.provider_ledger.codex_credentials import CodexCredential
from src.core.provider_ledger.credentials import ClaudeCredential, ClaudeIdentity
from src.models.provider_ledger import FetchOutcome, UsageWindow

NOW = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)

TOKEN = "sk-ant-oat01-NEVER-LOG-THIS-VALUE"

CODEX_TOKEN = "ey-codex-NEVER-LOG-THIS-VALUE"


@pytest.fixture(autouse=True)
def _configured_rows_only(request):
    if request.node.get_closest_marker("with_default_login") is None:
        request.getfixturevalue("no_builtin_default_login")


def claude_account(
    account_id: str = "max-main", name: str = "Max main"
) -> ProviderAccount:
    return ProviderAccount(
        id=account_id, name=name, provider="claude", claude_config_dir="~/.claude-test"
    )


def codex_account(
    account_id: str = "codex-main", name: str = "Codex main"
) -> ProviderAccount:
    return ProviderAccount(
        id=account_id, name=name, provider="codex", codex_home="~/.codex-test"
    )


def live_claude_credential() -> ClaudeCredential:
    return ClaudeCredential(
        access_token=TOKEN,
        expires_at=NOW + timedelta(hours=4),
        refresh_token_expires_at=NOW + timedelta(days=30),
        scopes=("user:inference", "user:profile"),
        subscription_type="max",
        rate_limit_tier="default",
        source="keychain",
    )


def live_codex_credential(account_id: Optional[str] = "acct-123") -> CodexCredential:
    return CodexCredential(
        access_token=CODEX_TOKEN,
        id_token=None,
        account_id=account_id,
        plan="plus",
        email="someone@example.test",
        last_refresh=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(hours=4),
        source="file",
    )


def ok_outcome(used: float = 42.0, plan: Optional[str] = "max") -> FetchOutcome:
    return FetchOutcome(
        state="ok",
        plan=plan,
        windows=[
            UsageWindow(
                kind="five_hour",
                label="5h",
                used_pct=used,
                window_seconds=18000,
                resets_at=NOW + timedelta(hours=2),
            )
        ],
    )


class FakeClock:

    def __init__(self, start: datetime = NOW) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


class FakeFetcher:

    def __init__(self, outcomes: List[FetchOutcome]) -> None:
        self.outcomes = list(outcomes)
        self.calls: List[Dict[str, Any]] = []

    async def __call__(self, client, access_token, account_id=None) -> FetchOutcome:
        self.calls.append({"access_token": access_token, "account_id": account_id})
        if len(self.outcomes) > 1:
            return self.outcomes.pop(0)
        return self.outcomes[0]


def build_poller(
    accounts: List[ProviderAccount],
    *,
    clock: Optional[FakeClock] = None,
    claude_fetch: Optional[FakeFetcher] = None,
    codex_fetch: Optional[FakeFetcher] = None,
    claude_credential: Any = "live",
    codex_credential: Any = "live",
    identity: Optional[ClaudeIdentity] = None,
    random_unit: float = 0.5,
) -> poller_module.LedgerPoller:
    clock = clock or FakeClock()
    cred = live_claude_credential() if claude_credential == "live" else claude_credential
    codex_cred = (
        live_codex_credential() if codex_credential == "live" else codex_credential
    )
    return poller_module.LedgerPoller(
        config_path=lambda: Path("/nonexistent/config.json"),
        list_accounts=lambda path: list(accounts),
        clock=clock,
        random_unit=lambda: random_unit,
        claude_fetch=claude_fetch or FakeFetcher([ok_outcome()]),
        codex_fetch=codex_fetch or FakeFetcher([ok_outcome(plan="plus")]),
        read_claude_credential=lambda config_dir: cred,
        read_claude_identity=lambda config_dir: identity,
        read_codex_credential=lambda codex_home: codex_cred,
        client_factory=lambda: None,
    )


def row(snapshot, account_id: str):
    for account in snapshot.accounts:
        if account.id == account_id:
            return account
    return None


class TestANewAccountIsPolledAtOnce:

    @pytest.mark.asyncio
    async def test_the_first_pass_reads_usage_for_an_account_it_has_never_seen(self):
        fetch = FakeFetcher([ok_outcome(used=37.0)])
        poller = build_poller([claude_account()], claude_fetch=fetch)

        await poller.run_pass()

        assert len(fetch.calls) == 1
        answer = row(poller.snapshot(), "max-main")
        assert answer.credential_state == "ok"
        assert answer.windows[0].used_pct == 37.0
        assert answer.fetched_at == NOW

    @pytest.mark.asyncio
    async def test_a_row_that_is_not_due_yet_is_not_polled_again(self):
        fetch = FakeFetcher([ok_outcome()])
        clock = FakeClock()
        poller = build_poller([claude_account()], clock=clock, claude_fetch=fetch)

        await poller.run_pass()
        clock.advance(5.0)
        await poller.run_pass()

        assert len(fetch.calls) == 1

    @pytest.mark.asyncio
    async def test_and_it_IS_polled_again_once_its_floor_has_passed(self):
        fetch = FakeFetcher([ok_outcome()])
        clock = FakeClock()
        poller = build_poller([claude_account()], clock=clock, claude_fetch=fetch)

        await poller.run_pass()
        clock.advance(181.0)
        await poller.run_pass()

        assert len(fetch.calls) == 2


class TestACredentialThatCannotWorkSpendsNoRequest:

    @pytest.mark.asyncio
    async def test_a_missing_login_never_reaches_the_network(self):
        fetch = FakeFetcher([ok_outcome()])
        poller = build_poller(
            [claude_account()], claude_fetch=fetch, claude_credential=None
        )

        await poller.run_pass()

        assert fetch.calls == []
        answer = row(poller.snapshot(), "max-main")
        assert answer.credential_state == "missing"
        assert answer.fetched_at is None

    @pytest.mark.asyncio
    async def test_an_expired_token_is_reported_without_a_request(self):
        expired = ClaudeCredential(
            access_token=TOKEN,
            expires_at=NOW - timedelta(minutes=1),
            refresh_token_expires_at=NOW + timedelta(days=30),
            scopes=("user:profile",),
            subscription_type="max",
            rate_limit_tier=None,
            source="keychain",
        )
        fetch = FakeFetcher([ok_outcome()])
        poller = build_poller(
            [claude_account()], claude_fetch=fetch, claude_credential=expired
        )

        await poller.run_pass()

        assert fetch.calls == []
        assert row(poller.snapshot(), "max-main").credential_state == "expired"

    @pytest.mark.asyncio
    async def test_a_local_refusal_reschedules_fast_because_it_cost_nothing(self):
        poller = build_poller([claude_account()], claude_credential=None)

        await poller.run_pass()

        assert row(poller.snapshot(), "max-main").next_poll_at == NOW + timedelta(
            seconds=15
        )


class TestALoginIsNoticedInOneFastRecheckNotAFloor:

    @pytest.mark.asyncio
    async def test_a_missing_credential_flips_to_ok_at_the_15_second_recheck(self):
        box: Dict[str, Any] = {"credential": None}
        fetch = FakeFetcher([ok_outcome(used=12.0)])
        clock = FakeClock()
        poller = poller_module.LedgerPoller(
            config_path=lambda: Path("/nonexistent/config.json"),
            list_accounts=lambda path: [claude_account()],
            clock=clock,
            random_unit=lambda: 0.5,
            claude_fetch=fetch,
            codex_fetch=FakeFetcher([ok_outcome(plan="plus")]),
            read_claude_credential=lambda config_dir: box["credential"],
            read_claude_identity=lambda config_dir: None,
            read_codex_credential=lambda codex_home: None,
            client_factory=lambda: None,
        )

        await poller.run_pass()
        assert fetch.calls == []
        first = row(poller.snapshot(), "max-main")
        assert first.credential_state == "missing"
        assert first.next_poll_at == NOW + timedelta(seconds=15)

        clock.advance(15.0)
        box["credential"] = live_claude_credential()
        await poller.run_pass()

        assert len(fetch.calls) == 1
        answer = row(poller.snapshot(), "max-main")
        assert answer.credential_state == "ok"
        assert answer.windows[0].used_pct == 12.0
        assert answer.next_poll_at == clock.now + timedelta(seconds=180)


class TestACredentialWriteIsNoticedOnTheNextTick:

    @pytest.mark.asyncio
    async def test_a_missing_login_is_repolled_the_tick_after_its_identity_file_appears(
        self, tmp_path
    ):
        box: Dict[str, Any] = {"credential": None}
        fetch = FakeFetcher([ok_outcome(used=9.0)])
        clock = FakeClock()
        account = ProviderAccount(
            id="max-main",
            name="Max main",
            provider="claude",
            claude_config_dir=str(tmp_path),
        )
        poller = poller_module.LedgerPoller(
            config_path=lambda: Path("/nonexistent/config.json"),
            list_accounts=lambda path: [account],
            clock=clock,
            random_unit=lambda: 0.5,
            claude_fetch=fetch,
            codex_fetch=FakeFetcher([ok_outcome(plan="plus")]),
            read_claude_credential=lambda config_dir: box["credential"],
            read_claude_identity=lambda config_dir: None,
            read_codex_credential=lambda codex_home: None,
            client_factory=lambda: None,
        )

        await poller.run_pass()
        assert fetch.calls == []
        first = row(poller.snapshot(), "max-main")
        assert first.credential_state == "missing"
        assert first.next_poll_at == NOW + timedelta(seconds=15)

        clock.advance(5.0)
        (tmp_path / ".claude.json").write_text('{"oauthAccount": {}}')
        box["credential"] = live_claude_credential()
        await poller.run_pass()

        assert len(fetch.calls) == 1
        answer = row(poller.snapshot(), "max-main")
        assert answer.credential_state == "ok"
        assert answer.windows[0].used_pct == 9.0

    @pytest.mark.asyncio
    async def test_no_file_change_leaves_a_missing_account_waiting_for_its_backstop(
        self, tmp_path
    ):
        fetch = FakeFetcher([ok_outcome()])
        clock = FakeClock()
        account = ProviderAccount(
            id="max-main",
            name="Max main",
            provider="claude",
            claude_config_dir=str(tmp_path),
        )
        poller = poller_module.LedgerPoller(
            config_path=lambda: Path("/nonexistent/config.json"),
            list_accounts=lambda path: [account],
            clock=clock,
            random_unit=lambda: 0.5,
            claude_fetch=fetch,
            codex_fetch=FakeFetcher([ok_outcome(plan="plus")]),
            read_claude_credential=lambda config_dir: None,
            read_claude_identity=lambda config_dir: None,
            read_codex_credential=lambda codex_home: None,
            client_factory=lambda: None,
        )

        await poller.run_pass()
        clock.advance(5.0)
        await poller.run_pass()

        assert fetch.calls == []
        assert row(poller.snapshot(), "max-main").credential_state == "missing"

    @pytest.mark.asyncio
    async def test_a_write_that_lands_during_the_read_is_caught_on_the_next_tick(
        self, tmp_path
    ):
        identity_file = tmp_path / ".claude.json"
        box: Dict[str, Any] = {"credential": None}

        def read_and_race(config_dir: str):
            identity_file.write_text('{"oauthAccount": {}}')
            return box["credential"]

        fetch = FakeFetcher([ok_outcome(used=5.0)])
        clock = FakeClock()
        account = ProviderAccount(
            id="max-main",
            name="Max main",
            provider="claude",
            claude_config_dir=str(tmp_path),
        )
        poller = poller_module.LedgerPoller(
            config_path=lambda: Path("/nonexistent/config.json"),
            list_accounts=lambda path: [account],
            clock=clock,
            random_unit=lambda: 0.5,
            claude_fetch=fetch,
            codex_fetch=FakeFetcher([ok_outcome(plan="plus")]),
            read_claude_credential=read_and_race,
            read_claude_identity=lambda config_dir: None,
            read_codex_credential=lambda codex_home: None,
            client_factory=lambda: None,
        )

        await poller.run_pass()
        assert fetch.calls == []
        assert row(poller.snapshot(), "max-main").credential_state == "missing"

        box["credential"] = live_claude_credential()
        clock.advance(5.0)
        await poller.run_pass()

        assert len(fetch.calls) == 1
        assert row(poller.snapshot(), "max-main").credential_state == "ok"

    @pytest.mark.asyncio
    async def test_an_ok_account_is_never_stat_checked_on_a_tick_it_is_not_due(
        self, monkeypatch
    ):
        import src.core.provider_ledger.poller_core as poller_core_module

        seen_ids: List[str] = []
        real_paths = poller_core_module.credential_signal.signal_paths

        def spy_paths(account):
            seen_ids.append(account.id)
            return real_paths(account)

        monkeypatch.setattr(
            poller_core_module.credential_signal, "signal_paths", spy_paths
        )

        ok_account = ProviderAccount(
            id="ok-one",
            name="Ok one",
            provider="claude",
            claude_config_dir="~/.claude-signal-ok-test",
        )
        missing_account = ProviderAccount(
            id="missing-one",
            name="Missing one",
            provider="claude",
            claude_config_dir="~/.claude-signal-missing-test",
        )

        def read_cred(config_dir: str):
            return live_claude_credential() if "ok-test" in config_dir else None

        clock = FakeClock()
        poller = poller_module.LedgerPoller(
            config_path=lambda: Path("/nonexistent/config.json"),
            list_accounts=lambda path: [ok_account, missing_account],
            clock=clock,
            random_unit=lambda: 0.5,
            claude_fetch=FakeFetcher([ok_outcome()]),
            codex_fetch=FakeFetcher([ok_outcome(plan="plus")]),
            read_claude_credential=read_cred,
            read_claude_identity=lambda config_dir: None,
            read_codex_credential=lambda codex_home: None,
            client_factory=lambda: None,
        )

        await poller.run_pass()
        seen_ids.clear()

        clock.advance(5.0)
        await poller.run_pass()

        assert "ok-one" not in seen_ids
        assert row(poller.snapshot(), "ok-one").credential_state == "ok"


class TestTheRateLimitLadderAsTheLoopWalksIt:

    @pytest.mark.asyncio
    async def test_a_429_with_a_deadline_schedules_exactly_that_deadline(self):
        fetch = FakeFetcher(
            [FetchOutcome(state="rate_limited", retry_after_seconds=90.0,
                          error="rate_limited")]
        )
        poller = build_poller([claude_account()], claude_fetch=fetch)

        await poller.run_pass()

        answer = row(poller.snapshot(), "max-main")
        assert answer.credential_state == "rate_limited"
        assert answer.next_poll_at == NOW + timedelta(seconds=90)

    @pytest.mark.asyncio
    async def test_consecutive_429s_grow_the_wait_and_then_stop_growing(self):
        fetch = FakeFetcher([FetchOutcome(state="rate_limited", error="rate_limited")])
        clock = FakeClock()
        poller = build_poller([claude_account()], clock=clock, claude_fetch=fetch)
        waits = []

        for _ in range(3):
            await poller.run_pass()
            answer = row(poller.snapshot(), "max-main")
            waits.append((answer.next_poll_at - clock.now).total_seconds())
            clock.advance(waits[-1])

        assert waits == [360.0, 540.0, 810.0]

    @pytest.mark.asyncio
    async def test_the_growth_stops_at_thirty_minutes(self):
        fetch = FakeFetcher([FetchOutcome(state="rate_limited", error="rate_limited")])
        clock = FakeClock()
        poller = build_poller([claude_account()], clock=clock, claude_fetch=fetch)
        waits = []

        for _ in range(8):
            await poller.run_pass()
            answer = row(poller.snapshot(), "max-main")
            waits.append((answer.next_poll_at - clock.now).total_seconds())
            clock.advance(waits[-1])

        assert waits[-1] == 1800.0
        assert max(waits) == 1800.0

    @pytest.mark.asyncio
    async def test_one_successful_poll_puts_the_account_back_on_its_floor(self):
        fetch = FakeFetcher(
            [FetchOutcome(state="rate_limited", error="rate_limited"), ok_outcome()]
        )
        clock = FakeClock()
        poller = build_poller([claude_account()], clock=clock, claude_fetch=fetch)

        await poller.run_pass()
        clock.advance(360.0)
        await poller.run_pass()

        answer = row(poller.snapshot(), "max-main")
        assert answer.credential_state == "ok"
        assert answer.next_poll_at == clock.now + timedelta(seconds=180)


class TestAFailedPollKeepsTheLastGoodReading:

    @pytest.mark.asyncio
    async def test_a_transport_error_leaves_the_windows_and_the_stamp_alone(self):
        fetch = FakeFetcher(
            [ok_outcome(used=61.0), FetchOutcome(state="error", error="unreachable")]
        )
        clock = FakeClock()
        poller = build_poller([claude_account()], clock=clock, claude_fetch=fetch)

        await poller.run_pass()
        clock.advance(181.0)
        await poller.run_pass()

        answer = row(poller.snapshot(), "max-main")
        assert answer.credential_state == "error"
        assert answer.error == "unreachable"
        assert answer.windows[0].used_pct == 61.0
        assert answer.fetched_at == NOW

    @pytest.mark.asyncio
    async def test_a_recovered_poll_clears_the_error_it_was_carrying(self):
        fetch = FakeFetcher(
            [FetchOutcome(state="error", error="timeout"), ok_outcome()]
        )
        clock = FakeClock()
        poller = build_poller([claude_account()], clock=clock, claude_fetch=fetch)

        await poller.run_pass()
        clock.advance(181.0)
        await poller.run_pass()

        answer = row(poller.snapshot(), "max-main")
        assert answer.error is None
        assert answer.fetched_at == clock.now


class TestTheAccountListIsRereadEveryPass:

    @pytest.mark.asyncio
    async def test_an_account_added_between_passes_appears_and_is_polled(self):
        accounts = [claude_account()]
        fetch = FakeFetcher([ok_outcome()])
        poller = build_poller(accounts, claude_fetch=fetch)

        await poller.run_pass()
        accounts.append(claude_account("max-second", "Max second"))
        await poller.run_pass()

        assert len(fetch.calls) == 2
        assert row(poller.snapshot(), "max-second") is not None

    @pytest.mark.asyncio
    async def test_an_account_removed_between_passes_leaves_the_snapshot(self):
        accounts = [claude_account(), claude_account("max-second", "Max second")]
        poller = build_poller(accounts)

        await poller.run_pass()
        accounts.pop()
        await poller.run_pass()

        snapshot = poller.snapshot()
        assert [a.id for a in snapshot.accounts] == ["max-main"]
        assert snapshot.total.accounts == 1

    @pytest.mark.asyncio
    async def test_poll_soon_makes_a_row_due_before_its_floor_elapses(self):
        fetch = FakeFetcher([ok_outcome()])
        poller = build_poller([claude_account()], claude_fetch=fetch)

        await poller.run_pass()
        poller.poll_soon("max-main")
        await poller.run_pass()

        assert len(fetch.calls) == 2


class TestTheSnapshotShape:

    @pytest.mark.asyncio
    async def test_rows_are_ordered_by_provider_then_by_name(self):
        accounts = [
            codex_account("codex-b", "Zeta codex"),
            claude_account("max-z", "Zeta max"),
            claude_account("max-a", "Alpha max"),
        ]
        poller = build_poller(accounts)

        await poller.run_pass()

        assert [a.id for a in poller.snapshot().accounts] == [
            "max-a",
            "max-z",
            "codex-b",
        ]

    @pytest.mark.asyncio
    async def test_the_total_line_averages_only_the_accounts_that_reported(self):
        accounts = [claude_account(), claude_account("max-second", "Max second")]
        poller = build_poller(accounts)

        await poller.run_pass()

        total = poller.snapshot().total
        assert total.accounts == 2
        assert total.windows[0].kind == "five_hour"
        assert total.windows[0].used_pct == 42.0

    @pytest.mark.asyncio
    @pytest.mark.with_default_login
    async def test_an_install_with_no_accounts_polls_the_auto_default_login(self):
        poller = build_poller([])

        await poller.run_pass()

        snapshot = poller.snapshot()
        assert [a.id for a in snapshot.accounts] == ["auto-claude-default"]
        assert snapshot.accounts[0].credential_state == "ok"
        assert snapshot.total.accounts == 1

    @pytest.mark.asyncio
    @pytest.mark.with_default_login
    async def test_a_configured_account_is_polled_beside_the_default_login(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        fetch = FakeFetcher([ok_outcome()])
        poller = build_poller([claude_account()], claude_fetch=fetch)

        await poller.run_pass()

        ids = sorted(a.id for a in poller.snapshot().accounts)
        assert ids == ["auto-claude-default", "max-main"]
        assert len(fetch.calls) == 2

    @pytest.mark.asyncio
    @pytest.mark.with_default_login
    async def test_the_auto_default_reports_missing_when_there_is_no_login(self):
        poller = build_poller([], claude_credential=None)

        await poller.run_pass()

        snapshot = poller.snapshot()
        assert [a.id for a in snapshot.accounts] == ["auto-claude-default"]
        assert snapshot.accounts[0].credential_state == "missing"

    @pytest.mark.asyncio
    async def test_a_claude_row_takes_its_identity_from_the_profile_file(self):
        poller = build_poller(
            [claude_account()],
            identity=ClaudeIdentity(
                email="alex@example.test",
                organization_name="Example",
                subscription_type="max",
            ),
        )

        await poller.run_pass()

        answer = row(poller.snapshot(), "max-main")
        assert answer.identity == "alex@example.test"
        assert answer.plan == "max"

    @pytest.mark.asyncio
    async def test_a_codex_row_takes_its_identity_from_its_own_credential(self):
        fetch = FakeFetcher([ok_outcome(plan=None)])
        poller = build_poller([codex_account()], codex_fetch=fetch)

        await poller.run_pass()

        answer = row(poller.snapshot(), "codex-main")
        assert answer.identity == "someone@example.test"
        assert answer.plan == "plus"

    @pytest.mark.asyncio
    async def test_the_codex_account_id_reaches_the_fetcher(self):
        fetch = FakeFetcher([ok_outcome()])
        poller = build_poller([codex_account()], codex_fetch=fetch)

        await poller.run_pass()

        assert fetch.calls[0]["account_id"] == "acct-123"


class TestLivenessIsNotFreshness:

    @pytest.mark.asyncio
    async def test_a_poller_that_was_never_started_reports_not_alive(self):
        poller = build_poller([claude_account()])

        await poller.run_pass()

        assert poller.status().alive is False

    @pytest.mark.asyncio
    async def test_but_it_still_records_when_its_last_pass_finished(self):
        clock = FakeClock()
        poller = build_poller([claude_account()], clock=clock)

        assert poller.status().last_pass_at is None
        await poller.run_pass()

        assert poller.status().last_pass_at == clock.now

    @pytest.mark.asyncio
    async def test_a_started_loop_reports_alive_and_stops_cleanly(self):
        poller = build_poller([])
        assert poller.start() is True
        try:
            await asyncio.sleep(0)
            assert poller.status().alive is True
        finally:
            await poller.stop()
        assert poller.status().alive is False


class TestNoCredentialEverReachesALogLine:

    @pytest.mark.asyncio
    async def test_a_full_pass_over_both_providers_logs_no_token(self):
        accounts = [claude_account(), codex_account()]
        poller = build_poller(accounts)

        with structlog.testing.capture_logs() as captured:
            await poller.run_pass()

        assert captured, "the pass logged nothing, so the search proves nothing"
        blob = repr(captured)
        assert TOKEN not in blob
        assert CODEX_TOKEN not in blob

    @pytest.mark.asyncio
    async def test_and_a_failing_pass_does_not_log_one_either(self):
        fetch = FakeFetcher([FetchOutcome(state="error", error="unreachable")])
        poller = build_poller([claude_account()], claude_fetch=fetch)

        with structlog.testing.capture_logs() as captured:
            await poller.run_pass()

        assert captured
        assert TOKEN not in repr(captured)


class TestTheLoopSurvivesAPassThatCrashes:

    @pytest.mark.asyncio
    async def test_an_exception_from_the_account_list_does_not_kill_the_loop(self):
        calls = {"n": 0}

        def exploding_list(path):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ValueError("Invalid JSON in config.json")
            return [claude_account()]

        poller = poller_module.LedgerPoller(
            config_path=lambda: Path("/nonexistent/config.json"),
            list_accounts=exploding_list,
            clock=FakeClock(),
            random_unit=lambda: 0.5,
            claude_fetch=FakeFetcher([ok_outcome()]),
            codex_fetch=FakeFetcher([ok_outcome()]),
            read_claude_credential=lambda config_dir: live_claude_credential(),
            read_claude_identity=lambda config_dir: None,
            read_codex_credential=lambda codex_home: None,
            client_factory=lambda: None,
        )

        with structlog.testing.capture_logs() as captured:
            await poller.run_pass()

        assert any("provider_ledger" in str(record.get("event")) for record in captured)
        assert poller.snapshot().accounts == []

        await poller.run_pass()
        assert len(poller.snapshot().accounts) == 1


class TestAValueThatCannotBeSentIsNeverSent:

    @pytest.mark.asyncio
    async def test_a_claude_token_with_a_non_ascii_character_is_never_fetched_with(
        self,
    ):
        fetch = FakeFetcher([ok_outcome()])
        credential = ClaudeCredential(
            access_token=TOKEN + "é",
            expires_at=NOW + timedelta(hours=4),
            refresh_token_expires_at=NOW + timedelta(days=30),
            scopes=("user:inference", "user:profile"),
            subscription_type="max",
            rate_limit_tier="default",
            source="keychain",
        )
        poller = build_poller(
            [claude_account()], claude_fetch=fetch, claude_credential=credential
        )

        await poller.run_pass()

        assert fetch.calls == []
        assert row(poller.snapshot(), "max-main").credential_state == "error"

    @pytest.mark.asyncio
    async def test_a_codex_account_id_that_cannot_be_sent_is_not_fetched_with_either(
        self,
    ):
        fetch = FakeFetcher([ok_outcome(plan="plus")])
        credential = CodexCredential(
            access_token=CODEX_TOKEN,
            id_token=None,
            account_id="acct-é",
            plan="plus",
            email="someone@example.test",
            last_refresh=None,
            expires_at=NOW + timedelta(hours=4),
            source="file",
        )
        poller = build_poller(
            [codex_account()], codex_fetch=fetch, codex_credential=credential
        )

        await poller.run_pass()

        assert fetch.calls == []
        assert row(poller.snapshot(), "codex-main").credential_state == "error"


class TestTheOutermostCatchLogsAClassNameAndNothingElse:

    @pytest.mark.asyncio
    async def test_the_crash_line_carries_the_class_name_not_the_message(self):
        poller = build_poller([claude_account()])

        async def exploding_pass():
            poller._stopping = True
            raise RuntimeError(f"boom {TOKEN}")

        poller.run_pass = exploding_pass

        with structlog.testing.capture_logs() as captured:
            await poller._loop()

        crashes = [
            record
            for record in captured
            if record.get("event") == "provider_ledger_pass_crashed"
        ]
        assert crashes, "the crash was not logged at all"
        assert crashes[0]["error"] == "RuntimeError"
        assert TOKEN not in repr(captured)


class TestTheClientTrustsNoAmbientEnvironment:

    def test_the_pooled_client_does_not_read_proxy_or_cert_variables(self):
        assert poller_state.build_client().trust_env is False




def test_a_row_carries_its_colour_and_whether_it_is_managed() -> None:
    state = poller_state.AccountState(
        account=ProviderAccount(
            id="claude1",
            name="Claude 1",
            provider="claude",
            managed=True,
            color="#8b5cf6",
        )
    )
    row = poller_state.account_row(state)
    assert row.color == "#8b5cf6"
    assert row.managed is True


def test_a_row_with_no_colour_carries_none_and_never_a_stand_in() -> None:
    state = poller_state.AccountState(
        account=ProviderAccount(id="work", name="Work", provider="claude")
    )
    row = poller_state.account_row(state)
    assert row.color is None
    assert row.managed is False




def test_a_row_carries_the_configured_accounts_own_short_name() -> None:
    state = poller_state.AccountState(
        account=ProviderAccount(
            id="claude1",
            name="Claude Code - Acme",
            provider="claude",
            short_name="Nyedis",
        )
    )
    row = poller_state.account_row(state)
    assert row.short_name == "Nyedis"


def test_a_row_with_no_short_name_carries_none() -> None:
    state = poller_state.AccountState(
        account=ProviderAccount(id="work", name="Work", provider="claude")
    )
    row = poller_state.account_row(state)
    assert row.short_name is None


class TestForgettingAnAccountTheRouteJustRemoved:

    @pytest.mark.asyncio
    async def test_the_readings_go_at_once_rather_than_on_the_next_pass(self):
        poller = build_poller([claude_account()])
        await poller.run_pass()
        assert row(poller.snapshot(), "max-main") is not None

        poller.forget_account("max-main")

        assert row(poller.snapshot(), "max-main") is None

    @pytest.mark.asyncio
    async def test_an_id_this_loop_never_saw_is_not_an_error(self):
        poller = build_poller([claude_account()])

        poller.forget_account("never-polled")

        assert poller.snapshot().loop is not None

    @pytest.mark.asyncio
    async def test_a_hurry_that_was_queued_for_it_goes_too(self):
        poller = build_poller([claude_account()])
        poller.poll_soon("max-main")

        poller.forget_account("max-main")

        assert "max-main" not in poller._poll_soon

    @pytest.mark.asyncio
    async def test_it_leaves_the_other_accounts_alone(self):
        poller = build_poller([claude_account(), claude_account(account_id="second")])
        await poller.run_pass()

        poller.forget_account("max-main")

        assert row(poller.snapshot(), "second") is not None
