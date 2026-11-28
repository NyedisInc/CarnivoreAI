
from __future__ import annotations

import asyncio
import functools
import sqlite3
import time
from contextlib import closing
from typing import Any, Awaitable, Callable, Collection, Dict, List, Optional, Tuple

import structlog

from src.core.computers import direction
from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.pack.relay import targets as targets_mod
from src.core.pack.relay.codex_target import codex_relay_profile_name
from src.core.pack.relay.target_side import relay_profile_name

logger = structlog.get_logger()

CREDENTIALS_PATH = "/federation/pack/credentials"
CAP_CREDENTIALS = "pack.credentials"
CODEX_CREDENTIALS_PATH = "/federation/pack/credentials/codex"
CAP_CREDENTIALS_CODEX = "pack.credentials.codex"
CAP_CREDENTIALS_USE = "pack.credentials.use"
PROVIDERS = ("claude", "codex")
RETRY_SECONDS = 30.0
NOT_ACCEPTED = "relay_not_accepted"
PostFn = Callable[[str, str, Optional[dict]], Awaitable[Tuple[int, Any]]]
PeerFn = Callable[[str], Optional[Tuple[PostFn, List[str]]]]
AllowsFn = Callable[[str], Optional[bool]]
AcceptsFn = Callable[[str, str], bool]
ApprovedFn = Callable[[str], bool]
ActiveFn = Callable[[str], Optional[str]]
ReachFn = Callable[[str, str, int], Awaitable[None]]


class Relay:

    def __init__(self, *, open_db: Callable[[], sqlite3.Connection], peer: PeerFn, notify: Callable[[], None],
                 self_id: str, allows: Optional[AllowsFn] = None, accepts: Optional[AcceptsFn] = None, approved: Optional[ApprovedFn] = None, candidates: Optional[Callable[[], List[str]]] = None,
                 on_pushed: Optional[Callable[[str, List[str]], None]] = None, active: Optional[ActiveFn] = None, clock: Callable[[], float] = time.time,
                 reach: Optional[ReachFn] = None, via_member: Optional[Callable[[str], bool]] = None) -> None:
        self._open_db, self._peer, self._notify, self._clock = open_db, peer, notify, clock
        self._self_id = self_id
        self._allows: AllowsFn = allows or (lambda _iid: True)
        self._accepts: AcceptsFn = accepts or (lambda _iid, _account: True)
        self._approved: ApprovedFn = approved or (lambda _iid: True)
        self._candidates: Callable[[], List[str]] = candidates or (lambda: [])
        self._on_pushed = on_pushed
        self._active: ActiveFn = active or (lambda _provider: None)
        self._reach = reach
        self._via_member = via_member
        self._retry_at: Dict[Tuple[str, str], float] = {}
        self._busy: set = set()
        self._tasks: set = set()

    def on_credential(self, account: Any, credential: Any) -> None:
        key = getattr(account, "id", None)
        provider = getattr(account, "provider", None)
        if provider not in PROVIDERS or not key or key in self._busy:
            return
        self._busy.add(key)
        task = asyncio.get_running_loop().create_task(self._run(key, credential, provider))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, account_key: str, credential: Any, provider: str = "claude") -> None:
        try:
            pushed = await self.push_account(account_key, credential, provider)
            if pushed and self._on_pushed is not None:
                self._on_pushed(account_key, pushed)
        except (sqlite3.Error, OSError) as exc:
            logger.warning("pack_relay_pass_failed", account=account_key, error=type(exc).__name__)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pack_relay_pass_failed", account=account_key, error=type(exc).__name__)
        finally:
            self._busy.discard(account_key)

    async def push_account(self, account_key: str, credential: Any, provider: str = "claude") -> List[str]:
        expires_at = getattr(credential, "expires_at", None)
        dial = asyncio.get_running_loop().create_task(self._reach(account_key, provider, int(expires_at.timestamp() * 1000))) \
            if self._reach is not None and expires_at is not None else None
        try:
            return await self._push_pass(account_key, credential, provider)
        finally:
            if dial is not None:
                await dial

    async def _push_pass(self, account_key: str, credential: Any, provider: str) -> List[str]:
        cap = CAP_CREDENTIALS_CODEX if provider == "codex" else CAP_CREDENTIALS
        def read() -> List[targets_mod.Target]:
            approved = functools.lru_cache(maxsize=None)(self._approved)
            armed = False
            with closing(self._open_db()) as conn:
                if not targets_mod.default_mode(conn, account_key):
                    ready = [iid for iid in self._candidates() if (link := self._peer(iid)) is not None and cap in link[1]
                             and self._allows(iid) is True and self._accepts(iid, account_key) and approved(iid)]
                    if ready:
                        targets_mod.arm_active(conn, account_key, ready, self._self_id, provider)
                        armed = True
                if targets_mod.default_mode(conn, account_key):
                    ready = []
                    for iid in self._candidates():
                        link = self._peer(iid)
                        if link is not None and cap in link[1] and self._allows(iid) is True \
                                and self._accepts(iid, account_key) and approved(iid):
                            ready.append(iid)
                    if ready:
                        targets_mod.arm_default(conn, account_key, ready, self._self_id, provider)
                        armed = True
                rows = [r for r in targets_mod.enabled_for(conn, account_key) if approved(r.target_install_id)]
            if armed:
                self._notify()
            return rows

        rows = await asyncio.to_thread(read)
        if not rows:
            return []
        use_hint = await asyncio.to_thread(self._active, provider) == account_key
        expires = getattr(credential, "expires_at", None)
        token = getattr(credential, "access_token", None)
        if expires is None or not token:
            return []
        if provider == "codex" and not (getattr(credential, "id_token", None) and getattr(credential, "account_id", None)):
            return []
        expiry_ms = int(expires.timestamp() * 1000)
        pushed: List[str] = []
        for row in rows:
            if direction.contained(row.target_install_id):
                continue
            if not self._accepts(row.target_install_id, account_key):
                continue
            if row.state == "refused":
                continue
            if row.state == "pushed" and row.last_expiry_pushed is not None and row.last_expiry_pushed >= expiry_ms:
                continue
            if provider == "codex" and cap not in ((self._peer(row.target_install_id) or (None, []))[1]):
                continue
            gate = (account_key, row.target_install_id)
            if self._retry_at.get(gate, 0.0) > self._clock():
                continue
            outcome = await self._push_one(row, account_key, credential, expiry_ms, provider, use_hint)
            await asyncio.to_thread(self._record, account_key, row.target_install_id, outcome, expiry_ms)
            if outcome == "pushed":
                pushed.append(row.target_install_id)
                self._retry_at.pop(gate, None)
            else:
                self._retry_at[gate] = self._clock() + RETRY_SECONDS
            self._notify()
        return pushed

    def _record(self, account_key: str, install_id: str, outcome: str, expiry_ms: int) -> None:
        with closing(self._open_db()) as conn:
            targets_mod.record(conn, account_key, install_id, outcome, expiry_ms, self._clock())

    async def _push_one(self, row: targets_mod.Target, account_key: str, credential: Any, expiry_ms: int,
                        provider: str = "claude", use_hint: bool = False) -> str:
        peer = self._peer(row.target_install_id)
        if peer is None:
            return "failed"
        member = self._via_member is not None and self._via_member(row.target_install_id)
        post, capabilities = peer
        codex = provider == "codex"
        if (CAP_CREDENTIALS_CODEX if codex else CAP_CREDENTIALS) not in capabilities:
            return "refused"
        if self._allows(row.target_install_id) is not True:
            return "failed"
        if codex:
            body = {"account_key": account_key, "profile": codex_relay_profile_name(account_key, self._self_id),
                    "access_token": credential.access_token, "id_token": credential.id_token,
                    "account_id": credential.account_id, "expires_at": expiry_ms, "plan": getattr(credential, "plan", None)}
        else:
            body = self._claude_body(account_key, credential, expiry_ms)
        if use_hint and CAP_CREDENTIALS_USE in capabilities:
            body["use_for_new_sessions"] = True
        try:
            status, data = await post("POST", CODEX_CREDENTIALS_PATH if codex else CREDENTIALS_PATH, body)
        except (asyncio.TimeoutError, OSError, ValueError, PeerUnreachable, PeerRefused) as exc:
            logger.info("pack_relay_push_failed", account=account_key, target=row.target_install_id,
                        error=type(exc).__name__)
            return "failed"
        logger.info("pack_relay_pushed", account=account_key, target=row.target_install_id, status=status)
        if status == 200:
            return "pushed"
        if isinstance(data, dict) and isinstance(data.get("detail"), dict) and data["detail"].get("code") == NOT_ACCEPTED:
            return "failed"
        if member and status in (401, 403) and not (status == 403 and isinstance(data, dict) and isinstance(data.get("detail"), dict)
                                                    and data["detail"].get("code") == "pack_restricted"):
            return "failed"
        return "refused" if status in (401, 403, 409, 422) else "failed"

    def _claude_body(self, account_key: str, credential: Any, expiry_ms: int) -> dict:
        return {"account_key": account_key, "profile": relay_profile_name(account_key, self._self_id),
                "access_token": credential.access_token, "expires_at": expiry_ms,
                "scopes": list(getattr(credential, "scopes", ()) or ()),
                "subscription_type": getattr(credential, "subscription_type", None),
                "rate_limit_tier": getattr(credential, "rate_limit_tier", None)}

    async def revoke(self, account_key: str, install_ids: List[str], provider: str = "claude") -> List[str]:
        failed: List[str] = []
        codex = provider == "codex"
        for iid in install_ids:
            peer = self._peer(iid)
            if peer is None:
                failed.append(iid)
                continue
            if (CAP_CREDENTIALS_CODEX if codex else CAP_CREDENTIALS) not in peer[1]:
                continue
            try:
                status, _ = await peer[0]("DELETE", f"{CODEX_CREDENTIALS_PATH if codex else CREDENTIALS_PATH}/{account_key}", None)
            except (asyncio.TimeoutError, OSError, ValueError, PeerUnreachable, PeerRefused) as exc:
                logger.info("pack_relay_revoke_failed", account=account_key, target=iid, error=type(exc).__name__)
                failed.append(iid)
                continue
            logger.info("pack_relay_revoked", account=account_key, target=iid, status=status)
            if status != 200 and status != 404:
                failed.append(iid)
        return failed

    async def sweep_orphans(self, existing: Collection[str]) -> int:
        from src.core.pack.machines import capabilities
        from src.core.pack.relay import ledger_sync_store, removed_copies

        now_ms = int(self._clock() * 1000)

        def read() -> Tuple[List[targets_mod.Target], set]:
            with closing(self._open_db()) as conn:
                removed: set = set()
                if capabilities.mesh_on():
                    removed_copies.prune_records(conn, now_ms)
                    removed = {iid for iid, _, _ in removed_copies.removed_computers(conn)}
                return targets_mod.orphan_rows(conn, existing), removed

        def drop(rows: List[Tuple[str, str, str]], kept: List[Tuple[str, str, str, int, float]]) -> None:
            with closing(self._open_db()) as conn:
                if kept:
                    removed_copies.keep_records(conn, kept)
                for account_key, iid, provider in rows:
                    targets_mod.delete_row(conn, account_key, iid)
                    if iid != targets_mod.DEFAULT_MARK:
                        ledger_sync_store.forget(iid, provider, account_key)

        dropped: List[Tuple[str, str, str]] = []
        kept: List[Tuple[str, str, str, int, float]] = []
        paired = set(await asyncio.to_thread(self._candidates))
        orphans, removed_ids = await asyncio.to_thread(read)
        for row in orphans:
            provider = "codex" if row.target_profile.endswith("-relay-codex") else "claude"
            if row.target_install_id == targets_mod.DEFAULT_MARK or row.state == "off" \
                    or (row.target_install_id not in paired and self._peer(row.target_install_id) is None):
                dropped.append((row.account_key, row.target_install_id, provider))
                if row.target_install_id in removed_ids and row.state != "off" and row.last_push_at is not None \
                        and row.last_expiry_pushed is not None and int(row.last_expiry_pushed) > now_ms:
                    kept.append((row.target_install_id, row.account_key, provider, int(row.last_expiry_pushed), float(row.last_push_at)))
            elif not await self.revoke(row.account_key, [row.target_install_id], provider):
                dropped.append((row.account_key, row.target_install_id, provider))
        if dropped:
            await asyncio.to_thread(drop, dropped, kept)
            self._notify()
        return len(dropped)
