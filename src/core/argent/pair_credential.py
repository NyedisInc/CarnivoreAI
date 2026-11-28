
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import structlog
from pydantic import BaseModel, ConfigDict, Field

from src.core.federation.peer_client import PeerRefused, PeerUnreachable
from src.core.argent import settings as settings_module
from src.core.argent.delegate import REMINT_FRACTION, DelegateUnavailable, Delegates
from src.core.argent.store import ArgentStore
from src.core.argent.token_store import TokenStore, TokenUnavailable

logger = structlog.get_logger()

CAP_CREDENTIAL = "argent.pair.credential"
CREDENTIAL_PATH = "/federation/argent/credential"
TENANT_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
TOKEN_RE = re.compile(r"[A-Za-z0-9_.~+/=:-]{16,1024}")
MIN_REMAINING_SECONDS = 60
MAX_REMAINING_SECONDS = 90 * 24 * 3600
MAX_CA_BYTES = 16000
CA_RE = re.compile(r"(?:-----BEGIN CERTIFICATE-----\n[A-Za-z0-9+/=\n]{20,8000}?\n-----END CERTIFICATE-----\n?){1,4}")
CA_DIR_NAME = "argent-ca"
RETRY_SECONDS = 30.0
FORCE_MIN_SECONDS = 60.0
PostFn = Callable[[str, str, Optional[dict]], Awaitable[Tuple[int, Any]]]
PeerFn = Callable[[str], Optional[Tuple[PostFn, List[str]]]]


class PairRefused(Exception):

    def __init__(self, code: str, status: int = 422) -> None:
        super().__init__(code)
        self.code, self.status = code, status


class CredentialBody(BaseModel):
    """One relayed Argent credential. ``extra=forbid``: a body carrying a refresh token, or anything else, is refused outright."""

    model_config = ConfigDict(extra="forbid", repr=False)

    tenant_id: str = Field(max_length=64)
    identity_id: str = Field(default="", max_length=128)
    display_name: str = Field(default="", max_length=200)
    access_token: str = Field(max_length=1024, repr=False)
    expires_at: int = Field(ge=0, le=10 ** 14)
    ca_pem: Optional[str] = Field(default=None, max_length=MAX_CA_BYTES)


def ca_file_for(state_dir: Path, sender_install_id: str) -> Path:
    return state_dir / CA_DIR_NAME / f"{hashlib.sha256(sender_install_id.encode('utf-8')).hexdigest()[:12]}.pem"


def _write_ca(path: Path, pem: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(pem if pem.endswith("\n") else pem + "\n", encoding="utf-8")
    os.replace(tmp, path)


def receive(sender_install_id: str, body: CredentialBody, *, store: ArgentStore, tokens: TokenStore, state_dir: Path,
            config_path: Optional[Path] = None, now: Optional[float] = None) -> int:
    clock = time.time() if now is None else now
    if not TENANT_RE.fullmatch(body.tenant_id) or (body.identity_id and not TENANT_RE.fullmatch(body.identity_id)):
        raise PairRefused("bad_tenant")
    if not TOKEN_RE.fullmatch(body.access_token):
        raise PairRefused("bad_token")
    if not (clock + MIN_REMAINING_SECONDS) * 1000 <= body.expires_at <= (clock + MAX_REMAINING_SECONDS) * 1000:
        raise PairRefused("expired")
    if body.ca_pem is not None and not CA_RE.fullmatch(body.ca_pem):
        raise PairRefused("bad_ca")
    current = store.get_login()
    if current is not None and float(current["expires_at"]) > clock and not store.login_expired():
        source = store.login_source()
        if not source.startswith("relay:"):
            raise PairRefused("own_login", 409)
        if source != f"relay:{sender_install_id}":
            raise PairRefused("relay_peer_conflict", 409)
    previous_relay = current is not None and store.login_source().startswith("relay:")
    try:
        tokens.write(body.tenant_id, body.access_token)
    except TokenUnavailable:
        raise PairRefused("write_failed", 503) from None
    previous = store.set_login(body.tenant_id, body.identity_id, body.display_name, int(body.expires_at / 1000 - clock), source=f"relay:{sender_install_id}")
    if previous and previous_relay:
        tokens.delete(previous)
    ca_path = ""
    if body.ca_pem is not None:
        try:
            target = ca_file_for(state_dir, sender_install_id)
            _write_ca(target, body.ca_pem)
            ca_path = str(target)
        except OSError:
            raise PairRefused("write_failed", 503) from None

    def mutate(block: Dict[str, Any]) -> None:
        block["tokenPointer"] = tokens.pointer(body.tenant_id)
        if ca_path and (not block.get("caPath") or str(block.get("caPath")).startswith(str(state_dir / CA_DIR_NAME))):
            block["caPath"] = ca_path

    settings_module.update(mutate, config_path, imported=True)
    logger.info("argent_pair_credential_received", sender=sender_install_id)
    return body.expires_at


class CredentialSender:

    def __init__(self, *, store: ArgentStore, tokens: TokenStore, peer: PeerFn, candidates: Callable[[], List[str]],
                 allows: Callable[[str], Optional[bool]], read_settings: Callable[[], Any], approved: Optional[Callable[[str], bool]] = None,
                 clock: Callable[[], float] = time.time, delegates: Optional[Delegates] = None, label: Callable[[str], str] = lambda iid: iid, max_life: Optional[int] = None,
                 frozen: Callable[[], bool] = lambda: False, denied: Callable[[str], bool] = lambda _iid: False) -> None:
        self._store, self._tokens, self._peer, self._candidates = store, tokens, peer, candidates
        self._allows, self._read_settings, self._clock = allows, read_settings, clock
        self._approved = approved or (lambda _iid: False)
        self._delegates = delegates or Delegates(store, tokens, read_settings=read_settings, clock=clock)
        self._label = label
        self._max_life = max_life
        self._frozen = frozen
        self._denied = denied
        self.sent: Dict[str, Dict[str, Any]] = {}
        self._retry_at: Dict[str, float] = {}
        self._fails: Dict[str, int] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._forced_at: Dict[str, float] = {}

    def _ca_text(self) -> Optional[str]:
        path = self._read_settings().ca_path
        if not path:
            return None
        try:
            with open(path, "rb") as handle:
                text = handle.read(MAX_CA_BYTES + 1).decode("utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        return text if len(text) <= MAX_CA_BYTES and CA_RE.fullmatch(text) else None

    async def push(self, only: Optional[str] = None, force: bool = False) -> List[str]:
        login = await asyncio.to_thread(self._store.get_login)
        source = await asyncio.to_thread(self._store.login_source)
        now = self._clock()
        if login is None or source != "own" or float(login["expires_at"]) <= now + MIN_REMAINING_SECONDS:
            return []
        pushed: List[str] = []
        frozen = await asyncio.to_thread(self._frozen)
        listed = [only] if only else await asyncio.to_thread(self._candidates)
        if not only:
            for iid in await asyncio.to_thread(self._store.delegate_installs):
                if iid in listed:
                    continue
                if frozen and not await asyncio.to_thread(self._denied, iid):
                    continue
                async with self._lock(iid):
                    await self._delegates.revoke(iid)
        for iid in listed:
            lock = self._lock(iid)
            if force and (lock.locked() or now - self._forced_at.get(iid, -1e9) < FORCE_MIN_SECONDS):
                continue
            async with lock:
                if force:
                    self._forced_at[iid] = now
                if await self._push_one(iid, login, now, force, frozen):
                    pushed.append(iid)
        return pushed

    def delegate_copies(self, iid: str, since_ms: int) -> List[Dict[str, Any]]:
        return self._delegates.copies_of(iid, since_ms)

    async def revoke_removed(self, iid: str) -> str:
        async with self._lock(iid):
            killed: List[str] = []
            pending = await self._delegates.revoke(iid, killed)
            if pending is None:
                return "none"
            state = "pending" if pending else ("dead" if killed else "expired")
            self.sent[iid] = {"state": state, "expires_at": max((int(e["expires_at"]) for e in pending), default=None)}
        logger.info("argent_delegate_removed", target=iid, state=state, killed=len(killed), pending=len(pending))
        return state

    def _lock(self, install_id: str) -> asyncio.Lock:
        return self._locks.setdefault(install_id, asyncio.Lock())

    async def _push_one(self, iid: str, login: Dict[str, object], now: float, force: bool, frozen: bool = False) -> bool:
        if self._allows(iid) is False:
            await self._delegates.revoke(iid)
        pre, approved = await asyncio.to_thread(lambda: (self._frozen(), self._approved(iid)))
        if not approved and (not (frozen or pre or await asyncio.to_thread(self._frozen)) or await asyncio.to_thread(self._denied, iid)):
            await self._delegates.revoke(iid)
        link = self._peer(iid)
        if link is None or CAP_CREDENTIAL not in link[1]:
            return False
        if self._allows(iid) is not True or not approved:
            self.sent[iid] = {"state": "not_accepting", "expires_at": None}
            return False
        rec = await asyncio.to_thread(self._store.delegate_get, iid)
        if not force and rec and rec.get("id") and now < float(rec["remint_at"]):
            return False
        if not force and self._retry_at.get(iid, 0.0) > now:
            return False
        try:
            minted = await self._delegates.mint(await asyncio.to_thread(self._label, iid))
        except DelegateUnavailable as exc:
            self.sent[iid] = {"state": "no_delegate" if exc.code == "route_missing" else "failed", "expires_at": None}
            self._back_off(iid, 600.0 if exc.code == "route_missing" else None)
            return False
        expiry_ms = int((now + minted.expires_in) * 1000)
        fresh = {"id": minted.id, "expires_at": expiry_ms}
        base = rec or {"id": "", "expires_at": 0, "remint_at": 0, "stale": []}
        await asyncio.to_thread(self._store.delegate_put, iid, {**base, "stale": [*base.get("stale", []), fresh]})
        body = {"tenant_id": login["tenant_id"], "identity_id": login["identity_id"], "display_name": login["display_name"],
                "access_token": minted.token, "expires_at": expiry_ms, "ca_pem": self._ca_text()}
        outcome = "too_long" if self._max_life is not None and minted.expires_in > self._max_life else await self._post(link[0], iid, body)
        self.sent[iid] = {"state": outcome, "expires_at": expiry_ms if outcome == "pushed" else None}
        if outcome != "pushed":
            self._back_off(iid, None)
            pending = await self._delegates.retire([fresh])
            await asyncio.to_thread(self._store.delegate_put, iid, {**base, "stale": [*base.get("stale", []), *pending]})
            return False
        self._retry_at.pop(iid, None)
        self._fails.pop(iid, None)
        superseded = ([{"id": base["id"], "expires_at": base["expires_at"]}] if base.get("id") else []) + list(base.get("stale", []))
        stale = await self._delegates.retire(superseded)
        await asyncio.to_thread(self._store.delegate_put, iid, {**fresh, "stale": stale, "remint_at": now + REMINT_FRACTION * minted.expires_in})
        return True

    def _back_off(self, iid: str, fixed: Optional[float]) -> None:
        n = self._fails.get(iid, 0)
        self._fails[iid] = n + 1
        self._retry_at[iid] = self._clock() + (fixed if fixed is not None else min(RETRY_SECONDS * 2 ** n, 600.0))

    async def _post(self, post: PostFn, iid: str, body: dict) -> str:
        try:
            status, _ = await post("POST", CREDENTIAL_PATH, body)
        except (asyncio.TimeoutError, OSError, ValueError, PeerUnreachable, PeerRefused) as exc:
            logger.info("argent_pair_credential_push_failed", target=iid, error=type(exc).__name__)
            return "failed"
        logger.info("argent_pair_credential_pushed", target=iid, status=status)
        return "pushed" if status == 200 else ("refused" if status in (401, 403, 409, 422) else "failed")
