
from __future__ import annotations

import asyncio
import sqlite3
import time
from contextlib import closing
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

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
PROVIDERS = ("claude", "codex")
RETRY_SECONDS = 30.0
NOT_ACCEPTED = "relay_not_accepted"
PostFn = Callable[[str, str, Optional[dict]], Awaitable[Tuple[int, Any]]]
PeerFn = Callable[[str], Optional[Tuple[PostFn, List[str]]]]
AllowsFn = Callable[[str], Optional[bool]]
AcceptsFn = Callable[[str, str], bool]


class Relay:

    def __init__(self, *, open_db: Callable[[], sqlite3.Connection], peer: PeerFn, notify: Callable[[], None],
                 self_id: str, allows: Optional[AllowsFn] = None, accepts: Optional[AcceptsFn] = None, candidates: Optional[Callable[[], List[str]]] = None,
                 on_pushed: Optional[Callable[[str, List[str]], None]] = None, clock: Callable[[], float] = time.time) -> None:
        self._open_db, self._peer, self._notify, self._clock = open_db, peer, notify, clock
        self._self_id = self_id
        self._allows: AllowsFn = allows or (lambda _iid: True)
        self._accepts: AcceptsFn = accepts or (lambda _iid, _account: True)
        self._candidates: Callable[[], List[str]] = candidates or (lambda: [])
        self._on_pushed = on_pushed
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
        finally:
            self._busy.discard(account_key)

    async def push_account(self, account_key: str, credential: Any, provider: str = "claude") -> List[str]:
        cap = CAP_CREDENTIALS_CODEX if provider == "codex" else CAP_CREDENTIALS

        def read() -> List[targets_mod.Target]:
            with closing(self._open_db()) as conn:
                if targets_mod.default_mode(conn, account_key):
                    ready = []
                    for iid in self._candidates():
                        link = self._peer(iid)
                        if link is not None and cap in link[1] and self._allows(iid) is True \
                                and self._accepts(iid, account_key):
                            ready.append(iid)
                    if ready:
                        targets_mod.arm_default(conn, account_key, ready, self._self_id, provider)
                return targets_mod.enabled_for(conn, account_key)

        rows = await asyncio.to_thread(read)
        if not rows:
            return []
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
            outcome = await self._push_one(row, account_key, credential, expiry_ms, provider)
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
                        provider: str = "claude") -> str:
        peer = self._peer(row.target_install_id)
        if peer is None:
            return "failed"
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
        return "refused" if status in (401, 403, 409, 422) else "failed"

    def _claude_body(self, account_key: str, credential: Any, expiry_ms: int) -> dict:
        return {"account_key": account_key, "profile": relay_profile_name(account_key, self._self_id),
                "access_token": credential.access_token, "expires_at": expiry_ms,
                "scopes": list(getattr(credential, "scopes", ()) or ()),
                "subscription_type": getattr(credential, "subscription_type", None),
                "rate_limit_tier": getattr(credential, "rate_limit_tier", None)}

    async def revoke(self, account_key: str, install_ids: List[str], provider: str = "claude") -> None:
        for iid in install_ids:
            peer = self._peer(iid)
            codex = provider == "codex"
            if peer is None or (CAP_CREDENTIALS_CODEX if codex else CAP_CREDENTIALS) not in peer[1]:
                continue
            try:
                status, _ = await peer[0]("DELETE", f"{CODEX_CREDENTIALS_PATH if codex else CREDENTIALS_PATH}/{account_key}", None)
            except (asyncio.TimeoutError, OSError, ValueError, PeerUnreachable, PeerRefused) as exc:
                logger.info("pack_relay_revoke_failed", account=account_key, target=iid, error=type(exc).__name__)
                continue
            logger.info("pack_relay_revoked", account=account_key, target=iid, status=status)
