
from __future__ import annotations

import asyncio
import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

import structlog

from src.core.catalog import catalog_auth, hosted_api
from src.core.catalog.catalog_auth import FLAG_DEVICE_MINTED, FLAG_DEVICE_REVOKED
from src.core.catalog.device_label import device_fields
from src.core.catalog.token_store import MODE_BOUND, MODE_OWN, CatalogSession, ClientEntry, open_token_store
from src.core.relay_identity import device_key as dk


class ClientSessionsError(ValueError):
    pass


logger = structlog.get_logger()

APIKEY_PREFIX = "apikey:"
FLAG_DEVICE_ID = "device_id"
FLAG_MIGRATED = "clients_migrated"
SWITCH_TTL_S = 600

KeyProvider = Callable[[], Awaitable[dk.DeviceKey]]


class ComputerSignedInAs(Exception):

    def __init__(self, login: str, handle: Optional[str]) -> None:
        super().__init__(login)
        self.login, self.handle = login, handle


class ComputerNeedsSignIn(Exception):
    pass


class RefreshAndRetry(Exception):
    pass


@dataclass(frozen=True)
class ClientRef:

    key: Optional[str]
    via_link: bool = False


def token_claim(token: str, name: str) -> Optional[str]:
    parts = token.split(".")
    body = dk.unb64url(parts[1]) if len(parts) == 3 else None
    try:
        value = json.loads(body.decode("utf-8")).get(name) if body else None
    except (UnicodeDecodeError, ValueError, AttributeError):
        value = None
    return value if isinstance(value, str) and value else None


def client_ref(request: Any) -> ClientRef:
    from src.core.api_keys import store as api_key_store

    via_link = bool(request.scope.get("via_link"))
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header[:7].lower() == "bearer " else ""
    if not token:
        return ClientRef(None, via_link)
    if api_key_store.is_api_key(token):
        row = api_key_store.get_store().authenticate(token)
        return ClientRef(f"{APIKEY_PREFIX}{row['id']}" if row else None, via_link)
    return ClientRef(token_claim(token, "fam"), via_link)


def _provider(held: CatalogSession) -> Optional[str]:
    from src.models.catalog_signin import provider_of_login

    return held.provider or provider_of_login(held.login)


async def _hosted_signout(base: str, access: str) -> None:
    try:
        await hosted_api.call(base, "POST", "/auth/signout", bearer=access)
    except hosted_api.HostedUnavailable as exc:
        logger.info("catalog_extra_session_signout_skipped", error=type(exc).__name__)


async def _mint_device(base: str, parent_access: str, key_provider: KeyProvider) -> Optional[Dict[str, Any]]:
    account, parent_sid = token_claim(parent_access, "sub"), token_claim(parent_access, "sid")
    if not account or not parent_sid:
        return None
    try:
        key = await key_provider()
        ts, nonce = int(time.time()), secrets.token_urlsafe(24)
        message = f"carnivore-device-v1|mint|{account}|{parent_sid}|{key.device_id}|{ts}|{nonce}".encode("ascii")
        answer = await hosted_api.call(
            base, "POST", "/auth/sessions/device", bearer=parent_access,
            json_body={"public_key": dk.b64url(key.raw_pub), "ts": ts, "nonce": nonce,
                       "signature": key.sign(message), **device_fields()},
        )
    except (hosted_api.HostedUnavailable, dk.DeviceKeyUnavailable, OSError) as exc:
        logger.info("catalog_device_mint_unavailable", error=type(exc).__name__)
        return None
    if answer.status != 200 or not isinstance(answer.body.get("access_token"), str):
        logger.info("catalog_device_mint_refused", status=answer.status)
        return None
    return {**answer.body, "device_id": answer.body.get("device_id") or key.device_id}


def _entry(key: str, mode: str, login: str, provider: Optional[str], tokens: Optional[CatalogSession] = None) -> ClientEntry:
    if tokens is None:
        return ClientEntry(key, mode, login, provider)
    return ClientEntry(key, mode, login, provider, tokens.access_token, tokens.access_expires_at,
                       tokens.refresh_token, tokens.refresh_expires_at)


def _session_of(tokens: Dict[str, Any], provider: str, email: Optional[str]) -> CatalogSession:
    from src.core.catalog import token_refresh

    now = int(time.time())
    login = tokens.get("login") if isinstance(tokens.get("login"), str) and tokens.get("login") else email
    access, refresh = tokens.get("access_token"), tokens.get("refresh_token")
    if not (isinstance(login, str) and login and isinstance(access, str) and access
            and isinstance(refresh, str) and refresh):
        raise ClientSessionsError("hosted sign in answer is missing a login or token")
    return CatalogSession(login, access, now + token_refresh._seconds(tokens, "expires_in"), refresh,
                          now + token_refresh._seconds(tokens, "refresh_expires_in"), provider)


async def _become_device(
    state_dir: Path, base: str, ref: ClientRef, tokens: Dict[str, Any], provider: str,
    email: Optional[str], key_provider: KeyProvider,
) -> CatalogSession:
    sign_in = _session_of(tokens, provider, email)
    minted = await _mint_device(base, sign_in.access_token, key_provider)
    device_tokens = {**minted, "login": sign_in.login} if minted else tokens
    device = catalog_auth.save_session(state_dir, device_tokens, provider, email)
    with open_token_store(state_dir) as store:
        store.flag_clear(FLAG_DEVICE_REVOKED)
        if minted:
            store.flag_set(FLAG_DEVICE_MINTED, "1")
            store.flag_set(FLAG_DEVICE_ID, str(minted["device_id"]))
        else:
            store.flag_clear(FLAG_DEVICE_MINTED)
        if ref.key is not None:
            store.client_put(
                _entry(ref.key, MODE_OWN, sign_in.login, provider, sign_in) if minted
                else _entry(ref.key, MODE_BOUND, sign_in.login, provider),
                int(time.time()),
            )
    if ref.key is not None:
        catalog_auth.notify_client(ref.key)
    return device


class _Switches:

    def __init__(self) -> None:
        self._held: Dict[str, tuple] = {}

    def stash(self, tokens: Dict[str, Any], provider: str, email: Optional[str], key: Optional[str]) -> str:
        now = time.time()
        self._held = {h: v for h, v in self._held.items() if v[4] > now}
        handle = secrets.token_urlsafe(24)
        self._held[handle] = (tokens, provider, email, key, now + SWITCH_TTL_S)
        return handle

    def drop(self, handle: str) -> Optional[tuple]:
        return self._held.pop(handle, None)

    def take(self, handle: str, key: Optional[str]) -> Optional[tuple]:
        value = self._held.get(handle)
        if value is None or value[4] <= time.time() or value[3] != key:
            return None
        del self._held[handle]
        return value

    def waiting_for(self, key: Optional[str]) -> Optional[str]:
        now = time.time()
        for tokens, _provider_name, email, owner, expiry in self._held.values():
            if owner == key and expiry > now:
                login = tokens.get("login")
                return login if isinstance(login, str) and login else email
        return None


switches = _Switches()
_sweeps: set = set()


def _expire_later(base: str, handle: str) -> None:
    async def run() -> None:
        await asyncio.sleep(SWITCH_TTL_S)
        parked = switches.drop(handle)
        if parked is not None:
            access = parked[0].get("access_token")
            if isinstance(access, str) and access:
                await _hosted_signout(base, access)

    task = asyncio.get_running_loop().create_task(run())
    _sweeps.add(task)
    task.add_done_callback(_sweeps.discard)


async def complete_signin(
    state_dir: Path, base: str, ref: ClientRef, tokens: Dict[str, Any], provider: str,
    email: Optional[str], key_provider: KeyProvider,
) -> CatalogSession:
    sign_in = _session_of(tokens, provider, email)
    device = catalog_auth.device_session(state_dir)
    if device is None:
        if ref.via_link or (ref.key or "").startswith(APIKEY_PREFIX):
            await _hosted_signout(base, sign_in.access_token)
            raise ComputerNeedsSignIn()
        return await _become_device(state_dir, base, ref, tokens, provider, email, key_provider)
    if ref.key is None:
        await _hosted_signout(base, sign_in.access_token)
        raise RefreshAndRetry()
    if device.login != sign_in.login:
        handle = switches.stash(tokens, provider, email, ref.key)
        _expire_later(base, handle)
        raise ComputerSignedInAs(device.login, handle)
    with open_token_store(state_dir) as store:
        minted = store.flag_get(FLAG_DEVICE_MINTED) == "1"
        store.client_put(
            _entry(ref.key, MODE_OWN, sign_in.login, provider, sign_in) if minted
            else _entry(ref.key, MODE_BOUND, sign_in.login, provider),
            int(time.time()),
        )
    if not minted:
        await _hosted_signout(base, sign_in.access_token)
    catalog_auth.notify_client(ref.key)
    return device


async def remint(
    state_dir: Path, base: str, ref: ClientRef, bound_account: Optional[str], key_provider: KeyProvider,
) -> bool:
    if ref.via_link or ref.key is None or not bound_account or catalog_auth.device_session(state_dir) is not None:
        return False
    with open_token_store(state_dir) as store:
        if store.flag_get(FLAG_DEVICE_REVOKED) == "1":
            return False
        entry = store.client_get(ref.key)
    if entry is None or entry.mode != MODE_OWN or not entry.access_token:
        return False
    if token_claim(entry.access_token, "sub") != bound_account:
        return False
    minted = await _mint_device(base, entry.access_token, key_provider)
    if minted is None:
        return False
    catalog_auth.save_session(state_dir, {**minted, "login": entry.login}, entry.provider or "email")
    with open_token_store(state_dir) as store:
        store.flag_set(FLAG_DEVICE_MINTED, "1")
        store.flag_set(FLAG_DEVICE_ID, str(minted["device_id"]))
    return True


async def session_views(state_dir: Path, base: str, ref: ClientRef) -> Dict[str, Any]:
    device = await catalog_auth.current(state_dir, base, allow_guest=True)
    guest = device is not None and device.is_guest
    real = device if device is not None and not guest else None
    with open_token_store(state_dir) as store:
        minted = store.flag_get(FLAG_DEVICE_MINTED) == "1"
        entry = store.client_get(ref.key) if ref.key is not None else None
    computer = {"signed_in": real is not None, "login": real.login if real else None,
                "provider": _provider(real) if real else None, "minted": bool(minted and real)}
    if ref.key is None:
        client = {"signed_in": real is not None, "login": computer["login"], "provider": computer["provider"],
                  "mode": None, "legacy": True}
    elif entry is None:
        client = {"signed_in": False, "login": None, "provider": None, "mode": None, "legacy": False}
    elif entry.mode == MODE_BOUND:
        live = real is not None and real.login == entry.login
        client = {"signed_in": live, "login": entry.login if live else None,
                  "provider": entry.provider if live else None, "mode": MODE_BOUND, "legacy": False}
    else:
        try:
            await catalog_auth.bearer_for(state_dir, base, ref.key)
            alive = True
        except catalog_auth.SignedOut:
            alive = False
        except (catalog_auth.RotationFailed, hosted_api.HostedUnavailable):
            alive = True
        client = {"signed_in": alive, "login": entry.login if alive else None,
                  "provider": entry.provider if alive else None, "mode": MODE_OWN, "legacy": False}
    client["via_link"] = ref.via_link
    return {"computer": computer, "client": client, "guest": guest}


def device_keep(state_dir: Path) -> List[Dict[str, str]]:
    device = catalog_auth.device_session(state_dir)
    with open_token_store(state_dir) as store:
        minted, device_id = store.flag_get(FLAG_DEVICE_MINTED) == "1", store.flag_get(FLAG_DEVICE_ID)
    sid = token_claim(device.access_token, "sid") if device else None
    return [{"sid": sid, "device_id": device_id}] if minted and sid and device_id else []


async def sign_out_all(
    state_dir: Path, base: str, ref: ClientRef,
) -> Dict[str, Any]:
    if ref.key is None:
        raise catalog_auth.UnknownClient()
    token = await catalog_auth.bearer_for(state_dir, base, ref.key)
    keep = device_keep(state_dir)
    body: Dict[str, Any] = {"include_self": True, "keep": keep} if keep else {}
    answer = await hosted_api.call(base, "POST", "/auth/sessions/revoke-all", json_body=body or None, bearer=token)
    if answer.status == 401:
        raise catalog_auth.SignedOut()
    if answer.status >= 400:
        raise catalog_auth.RotationFailed(answer.status, dict(answer.body))
    kept_device = bool(keep) and "kept" in answer.body
    if not kept_device:
        await _hosted_signout(base, token)
    with open_token_store(state_dir) as store:
        gone = store.clients_clear()
    for entry in gone:
        catalog_auth.notify_client(entry.client_key)
    if not kept_device:
        catalog_auth.forget(state_dir)
    return {"kept_device": kept_device}


async def use_account(
    state_dir: Path, base: str, ref: ClientRef, handle: str, key_provider: KeyProvider,
) -> CatalogSession:
    parked = switches.take(handle, ref.key)
    if parked is None:
        raise LookupError("no such switch")
    tokens, provider, email, _owner, _expiry = parked
    old = catalog_auth.device_session(state_dir)
    if old is not None:
        try:
            await _hosted_signout(base, await catalog_auth.bearer(state_dir, base))
        except (catalog_auth.SignedOut, catalog_auth.RotationFailed, hosted_api.HostedUnavailable) as exc:
            logger.info("catalog_switch_old_signout_skipped", error=type(exc).__name__)
    with open_token_store(state_dir) as store:
        owns = [e for e in store.clients_all() if e.mode == MODE_OWN]
    for entry in owns:
        await catalog_auth.sign_out_client(state_dir, base, entry.client_key)
    with open_token_store(state_dir) as store:
        gone = store.clients_clear()
    for entry in gone:
        catalog_auth.notify_client(entry.client_key)
    return await _become_device(state_dir, base, ref, tokens, provider, email, key_provider)


def migrate(state_dir: Path, families: List[str], key_ids: List[str]) -> int:
    device = catalog_auth.device_session(state_dir)
    now = int(time.time())
    bound = 0
    with open_token_store(state_dir) as store:
        if store.flag_get(FLAG_MIGRATED) == "1":
            return 0
        if device is not None:
            for key in [*families, *(f"{APIKEY_PREFIX}{k}" for k in key_ids)]:
                if store.client_get(key) is None:
                    store.client_put(_entry(key, MODE_BOUND, device.login, _provider(device)), now)
                    bound += 1
        store.flag_set(FLAG_MIGRATED, "1")
    logger.info("catalog_clients_migrated", bound=bound)
    return bound


def bind_family_to_device(state_dir: Path, family: str) -> bool:
    if not family:
        return False
    device = catalog_auth.device_session(state_dir)
    if device is None:
        return False
    now = int(time.time())
    with open_token_store(state_dir) as store:
        if store.client_get(family) is not None:
            return False
        store.client_put(_entry(family, MODE_BOUND, device.login, _provider(device)), now)
    logger.info("catalog_client_bound_door", mode=MODE_BOUND)
    return True


_pending: set = set()


def family_died(state_dir_of: Callable[[], Path], base_of: Callable[[], str]) -> Callable[[List[str]], None]:
    async def run(families: List[str]) -> None:
        for family in families:
            try:
                await catalog_auth.sign_out_client(state_dir_of(), base_of(), family)
            except (OSError, hosted_api.HostedUnavailable, catalog_auth.UnknownClient) as exc:
                logger.info("catalog_family_cleanup_skipped", error=type(exc).__name__)

    def listener(families: List[str]) -> None:
        task = asyncio.get_running_loop().create_task(run(list(families)))
        _pending.add(task)
        task.add_done_callback(_pending.discard)

    return listener
