
from __future__ import annotations

import asyncio
import json
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

import structlog

from src.config.relay import DEFAULT_RELAY_CONTROL_URL
from src.core import relay_protocol as proto
from src.core.catalog import hosted_api
from src.core.db import connect, ensure_install_id, get_meta, set_meta
from src.core.relay_identity import device_key as dk
from src.core.relay_identity.account import RelayAccount, account_id

logger = structlog.get_logger()

REFRESH_MARGIN_SECONDS = 120

MAX_ATTEMPTS = 3

META_REGISTERED = "relay_device_registered"

DEVICE_LABEL = "carnivore mac"

META_BOUND = "relay_bound_acct"

REVOKED = "revoked"
UPDATE_REQUIRED = "update_required"
ACCOUNT_DISABLED = "account_disabled"
OWNED_ELSEWHERE = "device_owned_elsewhere"
SIGNIN_REQUIRED = "signin_required"
KEYCHAIN_UNAVAILABLE = "keychain_unavailable"
UNREACHABLE = "control_unreachable"
REFUSED = "refused"
RATE_LIMITED = "rate_limited"
TERMINAL = frozenset({REVOKED, UPDATE_REQUIRED, ACCOUNT_DISABLED, OWNED_ELSEWHERE})


class RelayAuthError(Exception):

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind

    @property
    def terminal(self) -> bool:
        return self.kind in TERMINAL

    @property
    def parks(self) -> bool:
        return self.kind == SIGNIN_REQUIRED


@dataclass(frozen=True)
class RelayToken:

    token: str
    jti: str
    exp: int


def client_version(raw: str) -> str:
    match = re.search(r"\d{1,6}(?:\.\d{1,6}){0,3}", raw or "")
    return match.group(0) if match else "0.0.0"


def _jti_of(token: str) -> str:
    parts = token.split(".")
    body = dk.unb64url(parts[1]) if len(parts) == 3 else None
    try:
        jti = json.loads(body.decode("utf-8")).get("jti") if body else None
    except (UnicodeDecodeError, ValueError, AttributeError):
        jti = None
    if not isinstance(jti, str) or dk.unb64url(jti, 16) is None:
        raise RelayAuthError(REFUSED, "the issued token carries no usable jti")
    return jti


def _db_meta(db_path: Path, key: str, value: Optional[str] = None) -> Optional[str]:
    conn = connect(db_path, create=False)
    try:
        if value is None:
            return get_meta(conn, key)
        set_meta(conn, key, value)
        return value
    finally:
        conn.close()


def _install_id(db_path: Path) -> str:
    conn = connect(db_path, create=False)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            install_id = ensure_install_id(conn)
            conn.execute("COMMIT")
        except sqlite3.Error:
            conn.execute("ROLLBACK")
            raise
        return install_id
    finally:
        conn.close()


Call = Callable[..., Awaitable[hosted_api.HostedAnswer]]


class DeviceSession:

    def __init__(
        self,
        *,
        db_path: Path,
        control_url: str = DEFAULT_RELAY_CONTROL_URL,
        version: str = "0.0.0",
        call: Call = hosted_api.call,
        key_loader: Callable[[str], dk.DeviceKey] = dk.load_or_create,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        account: Optional[RelayAccount] = None,
        on_repair: Optional[Callable[[int], Awaitable[None]]] = None,
        on_token: Optional[Callable[[], None]] = None,
    ) -> None:
        self._on_repair = on_repair
        self._on_token = on_token
        self._account = account
        self._db_path = Path(db_path)
        self._control_url = control_url
        self.version = client_version(version)
        self._call = call
        self._key_loader = key_loader
        self._clock = clock
        self._sleep = sleep
        self._key: Optional[dk.DeviceKey] = None
        self._token: Optional[RelayToken] = None
        self._fetch_lock = asyncio.Lock()

    @property
    def device_id(self) -> Optional[str]:
        return None if self._key is None else self._key.device_id

    async def key(self) -> dk.DeviceKey:
        if self._key is None:
            try:
                install_id = await asyncio.to_thread(_install_id, self._db_path)
                self._key = await asyncio.to_thread(self._key_loader, install_id)
            except (dk.DeviceKeyUnavailable, sqlite3.Error) as exc:
                logger.warning("relay_device_key_unavailable", error=type(exc).__name__)
                raise RelayAuthError(KEYCHAIN_UNAVAILABLE, type(exc).__name__) from None
        return self._key

    async def _bearer(self, refused: Optional[str] = None) -> Optional[str]:
        return None if self._account is None else await self._account.bearer(refused)

    async def account_bearer(self) -> Optional[str]:
        return await self._bearer()

    async def ensure_registered(self) -> str:
        return await self._ensure(await self._bearer())

    async def _ensure(self, bearer: Optional[str]) -> str:
        key = await self.key()
        try:
            cached = await asyncio.to_thread(_db_meta, self._db_path, META_REGISTERED)
        except sqlite3.Error:
            cached = None
        if cached != key.device_id:
            ts = int(self._clock())
            body = {"pub": dk.b64url(key.raw_pub), "label": DEVICE_LABEL, "ts": ts,
                    "sig": key.sign(dk.register_message(key.device_id, key.raw_pub, ts))}
            answer = await self._post("/devices", body, bearer)
            owned = answer.status == 409 and answer.body.get("code") == OWNED_ELSEWHERE
            if answer.status == 200 and answer.body.get("device_id") == key.device_id:
                await self._remember(META_BOUND, account_id(bearer) if bearer else None)
            elif not (owned and bearer):
                raise _refusal(answer)
            await self._remember(META_REGISTERED, key.device_id)
            logger.info("relay_device_registered", device=key.device_id)
        if bearer:
            await self._claim(key, bearer)
        return key.device_id

    async def _remember(self, meta_key: str, value: Optional[str]) -> None:
        if value is None:
            return
        try:
            await asyncio.to_thread(_db_meta, self._db_path, meta_key, value)
        except sqlite3.Error as exc:
            logger.warning("relay_device_meta_unwritten", key=meta_key, error=type(exc).__name__)

    async def _claim(self, key: dk.DeviceKey, bearer: str) -> None:
        acct = account_id(bearer)
        if acct is None:
            return
        try:
            bound = await asyncio.to_thread(_db_meta, self._db_path, META_BOUND)
        except sqlite3.Error:
            bound = None
        if bound == acct:
            return
        for attempt in (1, 2):
            ts, nonce = int(self._clock()), secrets.token_bytes(16)
            body = {"device_id": key.device_id, "ts": ts, "nonce": dk.b64url(nonce),
                    "sig": key.sign(dk.claim_message(key.device_id, acct, ts, nonce))}
            answer = await self._post("/devices/claim", body, bearer)
            if answer.status == 200:
                break
            if not (attempt == 1 and answer.status == 409 and _code(answer) == OWNED_ELSEWHERE):
                raise _refusal(answer)
        await self._remember(META_BOUND, acct)
        self.drop_token()
        logger.info("relay_device_claimed", device=key.device_id)

    async def token(self) -> RelayToken:
        cached = self._fresh_token()
        if cached is not None:
            return cached
        async with self._fetch_lock:
            cached = self._fresh_token()
            if cached is not None:
                return cached
            return await self._fetch_token()

    def _fresh_token(self) -> Optional[RelayToken]:
        if self._token is not None and self._token.exp - REFRESH_MARGIN_SECONDS > self._clock():
            return self._token
        return None

    async def _fetch_token(self) -> RelayToken:
        bearer = await self._bearer()
        await self._ensure(bearer)
        answer = await self._post("/token", await self._token_request(), bearer)
        if answer.status == 404:
            await asyncio.to_thread(_db_meta, self._db_path, META_REGISTERED, "")
            await asyncio.to_thread(_db_meta, self._db_path, META_BOUND, "")
            await self._ensure(bearer)
            answer = await self._post("/token", await self._token_request(), bearer)
        if bearer and _code(answer) == "session_revoked":
            answer = await self._after_revoked(bearer)
        issued, exp = answer.body.get("token"), answer.body.get("exp")
        if answer.status != 200 or not isinstance(issued, str) or not isinstance(exp, int):
            raise _refusal(answer)
        repair = answer.body.get("link_repair")
        if self._on_repair is not None and isinstance(repair, int) and not isinstance(repair, bool):
            try:
                await self._on_repair(repair)
            except (OSError, sqlite3.Error) as exc:
                logger.warning("relay_repair_failed", error_type=type(exc).__name__)
                raise RelayAuthError(REFUSED, "repair_failed") from None
        self._token = RelayToken(token=issued, jti=_jti_of(issued), exp=exp)
        logger.info("relay_token_issued", exp=exp)
        if self._on_token is not None:
            self._on_token()
        return self._token

    async def _after_revoked(self, refused: str) -> hosted_api.HostedAnswer:
        fresh = await self._bearer(refused)
        if fresh is None:
            return hosted_api.HostedAnswer(401, {"code": "session_revoked"})
        answer = await self._post("/token", await self._token_request(), fresh)
        if _code(answer) == "session_revoked":
            logger.warning("relay_account_session_revoked_parked")
        return answer

    async def _token_request(self) -> Dict[str, Any]:
        key = await self.key()
        ts, nonce = int(self._clock()), secrets.token_bytes(16)
        return {"device_id": key.device_id, "ts": ts, "nonce": dk.b64url(nonce),
                "client": self.version,
                "sig": key.sign(dk.token_message(key.device_id, ts, nonce))}

    def drop_token(self) -> None:
        self._token = None

    async def pop_headers(self, token: RelayToken, *, tunnel: bool = False) -> Dict[str, str]:
        key = await self.key()
        ts = int(self._clock())
        message = dk.link_tunnel_pop_message if tunnel else dk.pop_message
        return {
            "Authorization": f"Bearer {token.token}",
            "Carnivore-Relay-PoP-Ts": str(ts),
            "Carnivore-Relay-PoP": key.sign(message(token.jti, ts)),
            "Carnivore-Relay-Client": self.version,
        }

    async def reauth_frame(self, token: RelayToken) -> Dict[str, Any]:
        key = await self.key()
        ts = int(self._clock())
        return {"type": "reauth", "token": token.token, "pop_ts": ts,
                "pop": key.sign(dk.pop_message(token.jti, ts))}

    async def tunnel_reauth_payload(self, token: RelayToken) -> Dict[str, Any]:
        key = await self.key()
        ts = int(self._clock())
        return {"token": token.token, "pop_ts": ts,
                "pop": key.sign(dk.link_tunnel_pop_message(token.jti, ts))}

    def new_link_identity(self) -> Tuple[str, str]:
        if self._key is None:
            raise RelayAuthError(KEYCHAIN_UNAVAILABLE, "device key not loaded")
        nonce = secrets.token_bytes(16)
        return dk.link_id_for(self._key.device_id, nonce), dk.b64url(nonce)

    async def _post(self, path: str, body: Dict[str, Any],
                    bearer: Optional[str] = None) -> hosted_api.HostedAnswer:
        auth = {"bearer": bearer} if bearer else {}
        answer: Optional[hosted_api.HostedAnswer] = None
        for attempt in range(MAX_ATTEMPTS):
            if attempt:
                await self._sleep(proto.backoff_delay(attempt - 1))
            try:
                answer = await self._call(self._control_url, "POST", path, json_body=body, **auth)
            except hosted_api.HostedUnavailable as exc:
                logger.warning("relay_control_unreachable", path=path, code=exc.code,
                               attempt=attempt + 1)
                continue
            if answer.status < 500:
                return answer
            logger.warning("relay_control_error", path=path, status=answer.status,
                           attempt=attempt + 1)
        if answer is None:
            raise RelayAuthError(UNREACHABLE, "the relay control plane could not be reached")
        return answer


def _code(answer: hosted_api.HostedAnswer) -> str:
    return str(answer.body.get("code", ""))


_CODE_KINDS = {
    "account_required": SIGNIN_REQUIRED,
    "session_revoked": SIGNIN_REQUIRED,
    "unauthorized": SIGNIN_REQUIRED,
    "account_disabled": ACCOUNT_DISABLED,
    OWNED_ELSEWHERE: OWNED_ELSEWHERE,
}


def _refusal(answer: hosted_api.HostedAnswer) -> RelayAuthError:
    code = _code(answer)
    if code in _CODE_KINDS:
        kind = _CODE_KINDS[code]
    elif answer.status == 403:
        kind = REVOKED
    elif answer.status == 426:
        kind = UPDATE_REQUIRED
    elif answer.status == 429:
        kind = RATE_LIMITED
    elif answer.status >= 500:
        kind = UNREACHABLE
    else:
        kind = REFUSED
    logger.warning("relay_control_refused", status=answer.status, code=code, kind=kind)
    return RelayAuthError(kind, code)
