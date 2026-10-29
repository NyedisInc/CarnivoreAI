
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import secrets
import time
from contextlib import closing
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

import structlog

from src.core import relay_keychain
from src.core.catalog import catalog_auth, hosted_api, pow_client, token_refresh
from src.core.catalog.device_label import device_fields
from src.core.catalog.token_store import GUEST_PROVIDER, CatalogSession, open_token_store
from src.core.db import META_INSTALL_ID, get_meta
from src.core.relay_identity import device_key
from src.core.test_write_guard import running_under_test

logger = structlog.get_logger(__name__)

GUEST_KEY_SERVICE = relay_keychain.CATALOG_GUEST_KEY_SERVICE

TERMS_VERSION = "2026-10-01"

GUEST_ID = re.compile(r"^guest:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

COOLDOWN_SECONDS = 600.0

Call = Callable[..., Awaitable[hosted_api.HostedAnswer]]


class GuestUnavailable(Exception):

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_cooldown_until = 0.0


class _GuestGone(Exception):
    pass


def _is_gone(answer: hosted_api.HostedAnswer) -> bool:
    code = answer.body.get("code") if isinstance(answer.body, dict) else None
    return (answer.status == 404 and code == "not_found") or (answer.status == 403 and code == "guest_unavailable")


async def _retire(state_dir, install_id: str) -> None:
    await asyncio.to_thread(relay_keychain.delete_password, GUEST_KEY_SERVICE, install_id)
    with open_token_store(state_dir) as store:
        store.clear_guest_id()
    logger.info("catalog_guest_retired")


def background_enabled() -> bool:
    return not (running_under_test() or os.environ.get(relay_keychain.TEST_SLOT_ENV))


def install_id_from(open_db: Callable[[], Any]) -> str:
    with closing(open_db()) as conn:
        value = get_meta(conn, META_INSTALL_ID)
    if not value:
        raise GuestUnavailable("guest_refused")
    return value


def _read(service: str, account: str) -> Tuple[str, Optional[str]]:
    return relay_keychain.read_password_state(service, account)


def _write(service: str, account: str, secret: str, replace: bool = True) -> None:
    relay_keychain.write_password(service, account, secret, replace=replace)


def _load_key(install_id: str) -> device_key.DeviceKey:
    try:
        return device_key.load_or_create(install_id, read=_read, write=_write, service=GUEST_KEY_SERVICE)
    except device_key.DeviceKeyUnavailable:
        logger.warning("catalog_guest_keychain_unavailable")
        raise GuestUnavailable("keychain_unavailable") from None


def _session_from(body: Dict[str, Any], guest_id: str, now: int) -> Optional[CatalogSession]:
    access, refresh = body.get("access_token"), body.get("refresh_token")
    if not (isinstance(access, str) and access and isinstance(refresh, str) and refresh):
        return None
    return CatalogSession(
        login=guest_id,
        access_token=access,
        access_expires_at=now + token_refresh._seconds(body, "expires_in"),
        refresh_token=refresh,
        refresh_expires_at=now + token_refresh._seconds(body, "refresh_expires_in"),
        provider=GUEST_PROVIDER,
    )


async def ensure_guest_session(
    *, state_dir, api_base_url: str, install_id: Callable[[], str],
    call: Call = hosted_api.call, clock: Callable[[], float] = time.time,
) -> str:
    global _cooldown_until
    async with catalog_auth.rotation_lock():
        now = int(clock())
        held = catalog_auth.read_session(state_dir)
        if held is not None and not held.is_guest:
            raise GuestUnavailable("signed_in")
        if held is not None and token_refresh.token_action(held, now) == token_refresh.USE_ACCESS:
            return held.access_token
        if now < _cooldown_until:
            raise GuestUnavailable("guest_refused")
        iid = await asyncio.to_thread(install_id)
        key = await asyncio.to_thread(_load_key, iid)
        with open_token_store(state_dir) as store:
            guest_id = store.guest_id()
        try:
            if guest_id is not None:
                try:
                    body = await _reauth(api_base_url, key, guest_id, now, call)
                except _GuestGone:
                    await _retire(state_dir, iid)
                    key, guest_id = await asyncio.to_thread(_load_key, iid), None
            if guest_id is None:
                guest_id, body = await _create(api_base_url, key, iid, now, call)
        except hosted_api.HostedUnavailable as exc:
            logger.warning("catalog_guest_unreachable", code=exc.code)
            raise GuestUnavailable("unreachable") from None
        except GuestUnavailable:
            _cooldown_until = now + COOLDOWN_SECONDS
            raise
        session = _session_from(body, guest_id, now)
        if session is None:
            _cooldown_until = now + COOLDOWN_SECONDS
            raise GuestUnavailable("guest_refused")
        with open_token_store(state_dir) as store:
            store.set_guest_id(guest_id)
            if not store.save_guest(session):
                raise GuestUnavailable("signed_in")
        logger.info("catalog_guest_session_stored")
        return session.access_token


async def _create(
    api_base_url: str, key: device_key.DeviceKey, install_id: str, now: int, call: Call
) -> Tuple[str, Dict[str, Any]]:
    challenge = await call(api_base_url, "POST", "/pow", json_body={"scope": "guest_create"})
    if challenge.status >= 400:
        raise GuestUnavailable("guest_refused")
    try:
        solved = await pow_client.solve_off_loop(dict(challenge.body))
    except pow_client.PowUnsolvable:
        raise GuestUnavailable("guest_refused") from None
    pub = device_key.b64url(key.raw_pub)
    answer = await call(api_base_url, "POST", "/auth/guest", json_body={
        "public_key": pub, "ts": now, "pow": solved,
        "signature": key.sign(f"carnivore-guest-v1|create|{pub}|{now}".encode("ascii")),
        "install_id": install_id, "terms_version": TERMS_VERSION, "age_attested": True,
        "client": device_fields()["client"], "label": "",
    })
    if answer.status >= 400:
        logger.warning("catalog_guest_create_refused", status=answer.status)
        raise GuestUnavailable("guest_refused")
    guest_id = answer.body.get("guest_id") or answer.body.get("login")
    if not (isinstance(guest_id, str) and GUEST_ID.match(guest_id)):
        raise GuestUnavailable("guest_refused")
    return guest_id, dict(answer.body)


async def _reauth(
    api_base_url: str, key: device_key.DeviceKey, guest_id: str, now: int, call: Call
) -> Dict[str, Any]:
    nonce = secrets.token_hex(16)
    answer = await call(api_base_url, "POST", "/auth/guest/session", json_body={
        "guest_id": guest_id, "ts": now, "nonce": nonce,
        "signature": key.sign(f"carnivore-guest-v1|session|{guest_id}|{now}|{nonce}".encode("ascii")),
    })
    if _is_gone(answer):
        raise _GuestGone
    if answer.status >= 400:
        logger.warning("catalog_guest_reauth_refused", status=answer.status)
        raise GuestUnavailable("guest_refused")
    return dict(answer.body)


def _subject_of(access_token: str) -> Optional[str]:
    try:
        payload = access_token.split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return None
    sub = data.get("sub") if isinstance(data, dict) else None
    return sub if isinstance(sub, str) and sub else None


async def fold_pending(
    *, state_dir, api_base_url: str, install_id: Callable[[], str],
    call: Call = hosted_api.call, clock: Callable[[], float] = time.time,
) -> str:
    with open_token_store(state_dir) as store:
        guest_id = store.guest_id()
    held = catalog_auth.read_session(state_dir)
    if guest_id is None or held is None or held.is_guest:
        return "none"
    try:
        token = await catalog_auth.bearer(state_dir, api_base_url)
    except (catalog_auth.SignedOut, catalog_auth.RotationFailed, hosted_api.HostedUnavailable):
        return "kept"
    target = _subject_of(token)
    iid = await asyncio.to_thread(install_id)
    state, value = await asyncio.to_thread(_read, GUEST_KEY_SERVICE, iid)
    seed = device_key.unb64url(value, 32) if state == relay_keychain.READ_OK else None
    if target is None or seed is None:
        logger.warning("catalog_guest_fold_cannot_prove")
        return "kept"
    key = device_key.DeviceKey.from_seed(seed)
    now, nonce = int(clock()), secrets.token_hex(16)
    try:
        answer = await call(api_base_url, "POST", "/account/fold", bearer=token, json_body={
            "guest_id": guest_id, "ts": now, "nonce": nonce,
            "signature": key.sign(
                f"carnivore-guest-v1|fold|{guest_id}|{target}|{now}|{nonce}".encode("ascii")),
        })
    except hosted_api.HostedUnavailable:
        return "unreachable"
    done = answer.status < 300 or (
        answer.status == 409 and answer.body.get("code") == "guest_already_folded")
    if answer.status == 404 and _is_gone(answer):
        await _retire(state_dir, iid)
        return "none"
    if not done:
        logger.warning("catalog_guest_fold_refused", status=answer.status)
        return "kept"
    await asyncio.to_thread(relay_keychain.delete_password, GUEST_KEY_SERVICE, iid)
    with open_token_store(state_dir) as store:
        store.clear_guest_id()
    logger.info("catalog_guest_folded")
    return "folded"


_installed: Optional[Callable[[Dict[str, Any]], None]] = None
_fold_tasks: set = set()


def install_fold(app_state: Any) -> None:
    global _installed
    if _installed is not None:
        catalog_auth.unsubscribe(_installed)

    def schedule() -> None:
        services = app_state.services
        try:
            task = asyncio.get_running_loop().create_task(fold_pending(
                state_dir=services.settings_reader.state_dir(),
                api_base_url=services.catalog.api_base_url(),
                install_id=lambda: install_id_from(services.catalog.open_db)))
        except RuntimeError:
            return
        _fold_tasks.add(task)

        def _done(finished: "asyncio.Task[str]") -> None:
            _fold_tasks.discard(finished)
            if not finished.cancelled() and finished.exception() is not None:
                logger.warning("catalog_guest_fold_failed", error=type(finished.exception()).__name__)

        task.add_done_callback(_done)

    def on_event(event: Dict[str, Any]) -> None:
        if event.get("signed_in"):
            schedule()

    _installed = on_event
    catalog_auth.subscribe(on_event)
    schedule()
