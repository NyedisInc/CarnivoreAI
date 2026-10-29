
from __future__ import annotations

import asyncio
import os
import random
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

import structlog

from src.config.provider_accounts import ProviderAccount, profile_dir_for
from src.core import resource_push, session_change_notice
from src.core.notifications.sources.login import LoginWatch
from src.core.resource_push import topics as resource_topics
from src.core.provider_ledger import (
    accounts_store,
    claude_usage,
    codex_credentials,
    codex_usage,
    credential_signal,
    credentials,
    poller_poke,
    poller_scan,
    refresh_poke,
    schedule,
)
from src.core.provider_ledger.poller_state import (
    AccountState,
    account_row,
    build_client,
    default_config_path,
    rows_fingerprint,
    utc_now,
)
from src.core.provider_ledger.total import compute_total
from src.models.provider_ledger import LedgerSnapshot, LedgerTotal, LoopStatus
from src.models.websocket import WSMessageType

logger = structlog.get_logger()


class LedgerPoller:

    def __init__(
        self,
        *,
        app_state: Any = None,
        config_path: Callable[[], Path] = default_config_path,
        list_accounts: Callable[
            [Path], List[ProviderAccount]
        ] = accounts_store.list_accounts,
        clock: Callable[[], datetime] = utc_now,
        random_unit: Callable[[], float] = random.random,
        claude_fetch: Callable[..., Any] = claude_usage.fetch_usage,
        codex_fetch: Callable[..., Any] = codex_usage.fetch_usage,
        read_claude_credential: Callable[
            [str], Any
        ] = credentials.read_claude_credential,
        read_claude_identity: Callable[[str], Any] = credentials.read_claude_identity,
        read_codex_credential: Callable[
            [str], Any
        ] = codex_credentials.read_codex_credential,
        client_factory: Callable[[], Any] = build_client,
        tick_seconds: float = schedule.TICK_SECONDS,
        poker: Optional[poller_poke.RefreshPoker] = None,
        after_pass: Optional[Callable[[LedgerSnapshot, Any], Any]] = None,
    ) -> None:
        self._app_state = app_state
        self._config_path = config_path
        self._list_accounts = list_accounts
        self._clock = clock
        self._random_unit = random_unit
        self._claude_fetch = claude_fetch
        self._codex_fetch = codex_fetch
        self._read_claude_credential = read_claude_credential
        self._read_claude_identity = read_claude_identity
        self._read_codex_credential = read_codex_credential
        self._client_factory = client_factory
        self._tick_seconds = tick_seconds
        self._poker = (
            poker
            if poker is not None
            else poller_poke.RefreshPoker(clock=clock, probe=self._probe_usage)
        )
        self._after_pass = after_pass
        self._states: Dict[str, AccountState] = {}
        self._poll_soon: Set[str] = set()
        self._last_pass_at: Optional[datetime] = None
        self._pushed_fingerprint: Optional[str] = None
        self._login_watch = LoginWatch()
        self._task: Optional[asyncio.Task] = None
        self._client: Any = None
        self._stopping = False


    def start(self) -> bool:
        if self._task is not None and not self._task.done():
            return False
        self._stopping = False
        self._client = self._client_factory()
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "provider_ledger_poller_started", tick_seconds=self._tick_seconds
        )
        return True

    async def stop(self) -> None:
        self._stopping = True
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        client = self._client
        self._client = None
        if client is not None and hasattr(client, "aclose"):
            await client.aclose()
        logger.info("provider_ledger_poller_stopped")

    async def _loop(self) -> None:
        while not self._stopping:
            try:
                await self.run_pass()
            except asyncio.CancelledError:
                raise
            except BaseException as exc:  # noqa: BLE001
                logger.warning(
                    "provider_ledger_pass_crashed", error=type(exc).__name__
                )
            if self._stopping:
                break
            await asyncio.sleep(self._tick_seconds)


    def _builtin_login_label(self) -> Optional[str]:
        store = getattr(self._app_state, "ui_preferences_store", None)
        if store is None:
            return None
        label = store.read().get("values", {}).get("builtin_login_label")
        return label if isinstance(label, str) and label else None

    async def run_pass(self) -> List[str]:
        now = self._clock()
        accounts = await poller_scan.read_accounts(
            self._list_accounts, self._config_path()
        )
        if accounts is not None:
            poller_scan.reconcile(
                self._states,
                self._poll_soon,
                poller_scan.with_auto_default(accounts, self._builtin_login_label()),
                now,
            )

        await poller_scan.mark_changed_signals(self._states, now)

        changed: List[str] = []
        for state in list(self._states.values()):
            refresh_only = state.next_poll_at is not None and state.next_poll_at > now
            if refresh_only and (
                state.refresh_check_at is None or state.refresh_check_at > now
            ):
                continue
            await self._poll(state, now, refresh_only=refresh_only)
            changed.append(state.account.id)

        self._last_pass_at = now
        if changed:
            self._publish(changed)
            await self._run_after_pass()
        return changed

    async def _run_after_pass(self) -> None:
        hook = self._after_pass
        if hook is None:
            if os.environ.get("CLOUDE_TEST_MODE"):
                return
            from src.core.account_switch.ledger_hook import after_ledger_pass as hook
        try:
            await hook(self.snapshot(), self._app_state)
        except Exception as exc:  # noqa: BLE001
            logger.warning("account_auto_switch_failed", error=type(exc).__name__)

    async def _poll(
        self, state: AccountState, now: datetime, *, refresh_only: bool = False
    ) -> None:
        account = state.account
        pre_read_signal = await asyncio.to_thread(
            credential_signal.signal_stamp, credential_signal.signal_paths(account)
        )
        credential = await self._read_credential(state)
        state.last_signal = pre_read_signal
        measured = credentials.credential_state_for(credential, now)
        row_error: Optional[str] = None
        state.refresh_check_at = None
        if measured == "expired":
            row_error = self._poker.expired(state, credential, now)
        elif measured == "ok":
            poller_poke.forget_if_superseded(state, credential)
            credential, state.refresh_check_at = await self._poker.pre_expiry(
                state, credential, now, lambda: self._read_credential(state)
            )
            measured = credentials.credential_state_for(credential, now)
            if measured == "ok" and account.provider == "claude":
                refresh_poke.notify_credential(account, credential)
        if measured != "ok":
            changed = state.credential_state != measured
            state.credential_state = measured
            state.error = row_error or measured
            self._schedule(state, now, measured, None, request_skipped=True)
            if changed:
                logger.info(
                    "provider_ledger_credential_unusable",
                    account_id=account.id,
                    provider=account.provider,
                    state=measured,
                )
            return

        if refresh_only:
            return

        if account.provider == "claude":
            outcome = await self._claude_fetch(self._client, credential.access_token)
        else:
            outcome = await self._codex_fetch(
                self._client, credential.access_token, credential.account_id
            )

        state.credential_state = outcome.state
        if outcome.state == "ok":
            state.windows = list(outcome.windows)
            state.fetched_at = now
            state.error = None
            if outcome.plan:
                state.plan = outcome.plan
        else:
            state.error = outcome.error or outcome.state
        self._schedule(state, now, outcome.state, outcome.retry_after_seconds)
        logger.info(
            "provider_ledger_polled",
            account_id=account.id,
            provider=account.provider,
            state=outcome.state,
            windows=len(state.windows),
        )

    async def _probe_usage(self, access_token: str) -> str:
        return (await self._claude_fetch(self._client, access_token)).state

    async def _read_credential(self, state: AccountState) -> Any:
        account = state.account
        profile_dir = profile_dir_for(account)
        if account.provider == "claude":
            credential = await asyncio.to_thread(
                self._read_claude_credential, profile_dir
            )
            identity = await asyncio.to_thread(
                self._read_claude_identity, profile_dir
            )
            state.setup_complete = identity.setup_complete if identity is not None else None
            if identity is not None:
                state.identity = identity.email or state.identity
                state.plan = identity.subscription_type or state.plan
            if credential is not None:
                state.plan = state.plan or credential.subscription_type
                state.login_expires_at = credential.refresh_token_expires_at
            return credential

        credential = await asyncio.to_thread(
            self._read_codex_credential, profile_dir
        )
        if credential is not None:
            state.identity = credential.email or state.identity
            state.plan = credential.plan or state.plan
        return credential

    def _schedule(
        self,
        state: AccountState,
        now: datetime,
        outcome_state: str,
        retry_after_seconds: Optional[float],
        *,
        request_skipped: bool = False,
    ) -> None:
        interval = schedule.next_interval_seconds(
            provider=state.account.provider,
            state=outcome_state,
            retry_after_seconds=retry_after_seconds,
            rate_limited_interval_seconds=state.rate_limited_interval,
            random_unit=self._random_unit(),
            request_skipped=request_skipped,
        )
        state.rate_limited_interval = (
            interval if outcome_state == "rate_limited" else None
        )
        state.next_poll_at = schedule.next_poll_at(now, interval)

    def _publish(self, account_ids: List[str]) -> None:
        session_change_notice.publish(
            self._app_state,
            {
                "type": WSMessageType.PROVIDER_LEDGER_UPDATED,
                "account_ids": sorted(account_ids),
            },
        )
        snapshot = self.snapshot()
        self._login_watch.observe(snapshot.accounts)
        fingerprint = rows_fingerprint(snapshot.accounts, alive=snapshot.loop.alive)
        if fingerprint == self._pushed_fingerprint:
            return
        self._pushed_fingerprint = fingerprint
        resource_push.notify(resource_topics.PROVIDER_LEDGER)
        resource_push.notify(resource_topics.ACCOUNT_SWITCH)


    def poll_soon(self, account_id: str) -> None:
        self._poll_soon.add(account_id)
        state = self._states.get(account_id)
        if state is not None:
            state.next_poll_at = self._clock()

    def forget_account(self, account_id: str) -> None:
        self._poll_soon.discard(account_id)
        state = self._states.pop(account_id, None)
        if state is not None:
            self._poker.forget_profile(state.account)

    def status(self) -> LoopStatus:
        alive = self._task is not None and not self._task.done()
        return LoopStatus(alive=alive, last_pass_at=self._last_pass_at)

    def snapshot(self) -> LedgerSnapshot:
        rows = [
            account_row(state)
            for state in sorted(
                self._states.values(),
                key=lambda s: (s.account.provider, s.account.name, s.account.id),
            )
        ]
        return LedgerSnapshot(
            accounts=rows,
            total=compute_total(rows) if rows else LedgerTotal(accounts=0),
            loop=self.status(),
        )
