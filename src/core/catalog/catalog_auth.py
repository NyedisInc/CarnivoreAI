
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import structlog

from src.core.catalog import hosted_api, token_refresh
from src.core.catalog.token_store import CatalogSession, open_token_store

logger = structlog.get_logger()

Subscriber = Callable[[Dict[str, Any]], None]

_subscribers: List[Subscriber] = []
_lock_holder: Optional[Tuple[asyncio.AbstractEventLoop, asyncio.Lock]] = None


class SignedOut(Exception):
    pass


@dataclass
class RotationFailed(Exception):

    status: int
    body: Dict[str, Any]


def _lock() -> asyncio.Lock:
    global _lock_holder
    loop = asyncio.get_running_loop()
    if _lock_holder is None or _lock_holder[0] is not loop:
        _lock_holder = (loop, asyncio.Lock())
    return _lock_holder[1]


def rotation_lock() -> asyncio.Lock:
    return _lock()


def subscribe(callback: Subscriber) -> None:
    if callback not in _subscribers:
        _subscribers.append(callback)


def unsubscribe(callback: Subscriber) -> None:
    if callback in _subscribers:
        _subscribers.remove(callback)


def _notify(session: Optional[CatalogSession]) -> None:
    from src.models.catalog_signin import provider_of_login

    if session is not None and session.is_guest:
        return
    event = {
        "signed_in": session is not None,
        "login": session.login if session else None,
        "provider": (session.provider or provider_of_login(session.login)) if session else None,
    }
    for callback in list(_subscribers):
        try:
            callback(dict(event))
        except Exception as exc:  # noqa: BLE001
            logger.warning("catalog_auth_subscriber_failed", error=type(exc).__name__)


def read_session(state_dir: Path) -> Optional[CatalogSession]:
    with open_token_store(state_dir) as store:
        return store.read()


def save_session(
    state_dir: Path, tokens: Dict[str, Any], provider: str, email: Optional[str] = None
) -> CatalogSession:
    now = int(time.time())
    login = tokens.get("login") if isinstance(tokens.get("login"), str) and tokens.get("login") else email
    access = tokens.get("access_token")
    refresh = tokens.get("refresh_token")
    if not (isinstance(login, str) and login and isinstance(access, str) and access
            and isinstance(refresh, str) and refresh):
        raise ValueError("hosted sign in answer is missing a login or token")
    session = CatalogSession(
        login=login,
        access_token=access,
        access_expires_at=now + token_refresh._seconds(tokens, "expires_in"),
        refresh_token=refresh,
        refresh_expires_at=now + token_refresh._seconds(tokens, "refresh_expires_in"),
        provider=provider,
    )
    with open_token_store(state_dir) as store:
        store.save(session)
    _notify(session)
    return session


def forget(state_dir: Path) -> bool:
    with open_token_store(state_dir) as store:
        held = store.read()
        removed = store.clear()
    if removed and not (held and held.is_guest):
        _notify(None)
    return removed


def forget_if_access_is(state_dir: Path, access_token: str) -> bool:
    with open_token_store(state_dir) as store:
        held = store.read()
        removed = store.clear_if_access_is(access_token)
    if removed and not (held and held.is_guest):
        _notify(None)
    return removed


def _action(held: Optional[CatalogSession], now: int, refused: Optional[str]) -> str:
    action = token_refresh.token_action(held, now)
    if (action == token_refresh.USE_ACCESS and refused is not None
            and held is not None and held.access_token == refused):
        return token_refresh.ROTATE if held.refresh_expires_at > now else token_refresh.SIGNED_OUT
    return action


async def bearer(
    state_dir: Path, api_base_url: str, clock: Callable[[], float] = time.time,
    refused: Optional[str] = None, allow_guest: bool = False,
) -> str:
    held = read_session(state_dir)
    action = _action(None if _hidden_guest(held, allow_guest) else held, int(clock()), refused)
    if action == token_refresh.SIGNED_OUT:
        raise SignedOut()
    if action == token_refresh.USE_ACCESS:
        return held.access_token  # type: ignore[union-attr]

    async with _lock():
        held = read_session(state_dir)
        action = _action(None if _hidden_guest(held, allow_guest) else held, int(clock()), refused)
        if action == token_refresh.SIGNED_OUT:
            raise SignedOut()
        if action == token_refresh.USE_ACCESS:
            return held.access_token  # type: ignore[union-attr]

        spent = held.refresh_token  # type: ignore[union-attr]
        answer = await hosted_api.call(
            api_base_url, "POST", "/auth/refresh", json_body={"refresh_token": spent}
        )
        if answer.status == 401:
            with open_token_store(state_dir) as store:
                cleared = store.clear_if_refresh_is(spent)
            logger.info("catalog_signin_rotation_refused", cleared=cleared)
            if cleared and not held.is_guest:  # type: ignore[union-attr]
                _notify(None)
            raise SignedOut()
        if answer.status >= 400:
            raise RotationFailed(answer.status, dict(answer.body))
        replacement = token_refresh.session_from_refresh(
            answer.body,
            fallback_login=held.login,  # type: ignore[union-attr]
            now=int(clock()),
            provider=held.provider,  # type: ignore[union-attr]
        )
        if replacement is None:
            raise SignedOut()
        with open_token_store(state_dir) as store:
            swapped = store.save_if_refresh_is(spent, replacement)
        if not swapped:
            current = read_session(state_dir)
            if current is None:
                raise SignedOut()
            return current.access_token
        logger.info("catalog_signin_rotated")
        return replacement.access_token


def _hidden_guest(held: Optional[CatalogSession], allow_guest: bool) -> bool:
    return held is not None and held.is_guest and not allow_guest


async def current(
    state_dir: Path, api_base_url: str, allow_guest: bool = False
) -> Optional[CatalogSession]:
    held = read_session(state_dir)
    if held is None or _hidden_guest(held, allow_guest):
        return None
    now = int(time.time())
    action = token_refresh.token_action(held, now)
    if action == token_refresh.SIGNED_OUT:
        return None
    if action == token_refresh.ROTATE:
        try:
            await bearer(state_dir, api_base_url, allow_guest=allow_guest)
        except SignedOut:
            return None
        except (hosted_api.HostedUnavailable, RotationFailed) as exc:
            logger.info("catalog_session_rotation_deferred", error=type(exc).__name__)
        return read_session(state_dir)
    return held


async def sign_out(state_dir: Path, api_base_url: str) -> None:
    held = read_session(state_dir)
    if held is not None and held.is_guest:
        return
    try:
        token = await bearer(state_dir, api_base_url)
        await hosted_api.call(api_base_url, "POST", "/auth/signout", bearer=token)
    except (SignedOut, RotationFailed, hosted_api.HostedUnavailable) as exc:
        logger.info("catalog_hosted_signout_skipped", error=type(exc).__name__)
    forget(state_dir)
