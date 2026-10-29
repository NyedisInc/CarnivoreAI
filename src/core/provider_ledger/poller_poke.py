
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, NamedTuple, Optional

import structlog

from src.config.provider_accounts import ProviderAccount, profile_dir_for
from src.config import settings as app_settings
from src.core.provider_ledger import refresh_guard, refresh_poke
from src.core.provider_ledger.credentials import is_default_claude_dir
from src.core.provider_ledger.login_command import login_profile_dir
from src.core.provider_ledger.poller_state import AccountState

logger = structlog.get_logger()

__all__ = ["PreExpiry", "RefreshPoker", "forget", "forget_if_superseded"]

_RESOLVE = object()

DEFAULT_PROFILE_KEY = "default"

NEEDS_USER_STATES = frozenset({"failed", "unknown", "needs_login"})

UNMOVED_RETRY_SECONDS = 60.0

MIN_REMAINING_AT_SPAWN_SECONDS = 10.0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PreExpiry(NamedTuple):

    credential: Any
    recheck_at: Optional[datetime]


def forget(state: AccountState) -> None:
    state.poke_state = "idle"
    state.poke_error = None
    state.poke_for_expiry = None


def forget_if_superseded(state: AccountState, credential: Any) -> None:
    if state.poke_for_expiry is not None and credential.expires_at == state.poke_for_expiry:
        return
    forget(state)


def profile_for_poke(account: ProviderAccount) -> Optional[str]:
    if is_default_claude_dir(profile_dir_for(account)):
        return None
    return login_profile_dir(account)


class RefreshPoker:

    def __init__(
        self,
        *,
        claude_binary: Any = _RESOLVE,
        run: Callable[..., Awaitable[refresh_poke.PokeOutcome]] = refresh_poke.run_poke,
        busy: Callable[[Optional[str]], Optional[str]] = refresh_guard.busy_reason,
        timeout: float = refresh_poke.POKE_TIMEOUT_SECONDS,
        clock: Callable[[], datetime] = _utc_now,
        probe: Optional[Callable[[str], Awaitable[str]]] = None,
        keepalive: Optional[bool] = None,
    ) -> None:
        self._binary: Optional[str] = (
            refresh_poke.resolve_claude_binary()
            if claude_binary is _RESOLVE
            else claude_binary
        )
        self._run = run
        self._busy = busy
        self._timeout = timeout
        self._clock = clock
        self._probe = probe
        self._keepalive: bool = (
            app_settings.ledger_keepalive if keepalive is None else keepalive
        )
        self._locks: Dict[str, asyncio.Lock] = {}
        if self._binary is None:
            logger.warning("provider_ledger_poke_disabled_no_claude_binary")

    def _lock_for(self, account: ProviderAccount) -> asyncio.Lock:
        key = profile_for_poke(account) or DEFAULT_PROFILE_KEY
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def forget_profile(self, account: ProviderAccount) -> None:
        key = profile_for_poke(account) or DEFAULT_PROFILE_KEY
        lock = self._locks.get(key)
        if lock is not None and not lock.locked():
            del self._locks[key]

    def expired(self, state: AccountState, credential: Any, now: datetime) -> Optional[str]:
        if state.account.provider != "claude" or credential is None:
            return None
        deadline = credential.refresh_token_expires_at
        if deadline is not None and deadline <= now:
            return refresh_poke.LOGIN_EXPIRED
        if state.poke_state in NEEDS_USER_STATES:
            return state.poke_error
        return None

    async def pre_expiry(
        self,
        state: AccountState,
        credential: Any,
        now: datetime,
        reread: Callable[[], Awaitable[Any]],
    ) -> PreExpiry:
        expires_at = credential.expires_at
        if (
            state.account.provider != "claude"
            or expires_at is None
            or not self._keepalive
        ):
            return PreExpiry(credential, None)
        due = refresh_guard.refresh_due_at(expires_at)
        if now < due:
            return PreExpiry(credential, due)
        if state.poke_for_expiry == expires_at:
            return PreExpiry(credential, expires_at)

        deadline = credential.refresh_token_expires_at
        if deadline is not None and deadline <= now:
            return PreExpiry(credential, None)

        if self._binary is None:
            state.poke_state = "failed"
            state.poke_error = refresh_poke.POKE_BINARY_MISSING
            state.poke_for_expiry = expires_at
            return PreExpiry(credential, None)

        lock = self._lock_for(state.account)
        if lock.locked():
            return PreExpiry(credential, refresh_guard.busy_recheck_at(now, expires_at))

        async with lock:
            profile = profile_for_poke(state.account)
            reason = await asyncio.to_thread(self._busy, profile)
            if reason is not None:
                logger.info(
                    "provider_ledger_poke_skipped",
                    account_id=state.account.id,
                    reason=reason,
                )
                return PreExpiry(credential, refresh_guard.busy_recheck_at(now, expires_at))
            spawn_at = self._clock()
            margin = timedelta(seconds=MIN_REMAINING_AT_SPAWN_SECONDS)
            if spawn_at >= expires_at - margin:
                logger.info(
                    "provider_ledger_poke_skipped",
                    account_id=state.account.id,
                    reason="window_closed",
                )
                return PreExpiry(credential, expires_at)
            return await self._poke(state, credential, spawn_at, reread, profile)

    async def _poke(
        self,
        state: AccountState,
        credential: Any,
        now: datetime,
        reread: Callable[[], Awaitable[Any]],
        profile: Optional[str],
    ) -> PreExpiry:
        before = credential.expires_at
        state.poke_for_expiry = before
        state.poke_state = "running"
        state.poke_last_at = now
        argv, env = refresh_poke.build_poke(profile, self._binary)
        logger.info("provider_ledger_poke_started", account_id=state.account.id)

        try:
            outcome = await self._run(argv, env, timeout=self._timeout)
            fresh = await reread()
        except BaseException as exc:
            state.poke_state = "failed"
            state.poke_error = refresh_poke.POKE_ERRORED
            logger.warning(
                "provider_ledger_poke_errored",
                account_id=state.account.id,
                error=type(exc).__name__,
            )
            raise

        moved = (
            fresh is not None
            and fresh.expires_at is not None
            and fresh.expires_at > before
        )
        retry_at: Optional[datetime] = None
        if moved:
            result, reason = "refreshed", None
        else:
            verdict = await self._probe_unmoved(fresh)
            if verdict == "expired":
                result, reason = refresh_poke.NEEDS_LOGIN, refresh_poke.NEEDS_LOGIN
            elif verdict == "ok":
                result, reason = "idle", None
                state.poke_for_expiry = None
                retry_at = now + timedelta(seconds=UNMOVED_RETRY_SECONDS)
            elif outcome.timed_out:
                result, reason = "unknown", refresh_poke.POKE_TIMED_OUT
            else:
                result, reason = "failed", refresh_poke.failure_reason(outcome)
        state.poke_state = "idle" if moved else result
        state.poke_error = reason
        logger.info(
            "provider_ledger_poke_finished",
            account_id=state.account.id,
            outcome=result,
            reason=reason,
            moved=moved,
            exit_code=outcome.exit_code,
            timed_out=outcome.timed_out,
            duration_seconds=round(outcome.duration_seconds, 3),
            stdout_bytes=outcome.stdout_bytes,
            stderr_bytes=outcome.stderr_bytes,
            output_signals=list(outcome.output_signals),
        )
        if moved or fresh is None or fresh.expires_at is None or fresh.expires_at <= now:
            return PreExpiry(fresh, None)
        if retry_at is not None and retry_at < fresh.expires_at:
            return PreExpiry(fresh, retry_at)
        return PreExpiry(fresh, fresh.expires_at)

    async def _probe_unmoved(self, fresh: Any) -> Optional[str]:
        token = fresh.access_token if fresh is not None else None
        if self._probe is None or not token:
            return None
        return await self._probe(token)
