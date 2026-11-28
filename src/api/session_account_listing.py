
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Iterable, Optional, Set, Tuple

import structlog

from src.core.account_switch import pane_account
from src.core.hosts.identity import is_remote_info

logger = structlog.get_logger(__name__)

RETRY_SECONDS = 60.0

Key = Tuple[str, Optional[int]]

_cache: Dict[Key, Tuple[Optional[str], float]] = {}
_in_flight: Set[Key] = set()
_tasks: Set["asyncio.Task[None]"] = set()
_generation: Dict[str, int] = {}


def invalidate(tmux_name: str) -> None:
    _generation[tmux_name] = _generation.get(tmux_name, 0) + 1
    for key in [k for k in _cache if k[0] == tmux_name]:
        del _cache[key]
    _in_flight.difference_update([k for k in _in_flight if k[0] == tmux_name])


def reset() -> None:
    _cache.clear()
    _in_flight.clear()
    _generation.clear()


def cached_account(info: Any) -> Optional[str]:
    key = _key(info)
    hit = _cache.get(key) if key is not None else None
    return hit[0] if hit else None


def _provider_for(info: Any, profiles: Any = None) -> Optional[str]:
    family = getattr(info, "agent_family", None) or ""
    provider = pane_account.FAMILY_PROVIDER.get(family)
    if provider is not None:
        return provider
    if family == "agy":
        return "antigravity"
    if family == "custom":
        from src.core.agy.identity import info_is_agy

        if info_is_agy(info, profiles):
            return "antigravity"
    return None


def _key(info: Any, profiles: Any = None) -> Optional[Key]:
    provider = _provider_for(info, profiles)
    name = getattr(info, "tmux_session", None)
    if provider is None or not name or is_remote_info(info):
        return None
    if getattr(info, "activity_status", None) == "dead":
        return None
    return (name, getattr(info.session, "tmux_created_epoch", None))


def _resolve_agy_account(session_manager: Any, tmux_name: str, conv_uuid: Optional[str], accounts: Any) -> Optional[str]:
    from src.config import settings
    from src.core.agy import accounts as agy_accounts, state as agy_state

    cid = conv_uuid or (
        session_manager.claude_uuid_for_tmux_name(tmux_name)
        if hasattr(session_manager, "claude_uuid_for_tmux_name")
        else None
    )
    state = agy_state.state_for_conversation(settings.get_state_dir(), cid)
    email = (state or {}).get("email")
    if not isinstance(email, str) or not email.strip():
        return None
    try:
        aid = agy_accounts.account_id_for_email(email)
    except agy_accounts.AgyAccountError:
        return None
    return aid if any(a.id == aid and a.provider == "antigravity" for a in accounts) else None


async def _resolve(app_state: Any, wanted: Dict[Key, Tuple[str, Optional[str]]]) -> None:
    try:
        from src.api.provider_ledger_routes import _config_path
        from src.core.provider_ledger import accounts_store, poller_scan

        accounts = poller_scan.with_auto_default(
            await asyncio.to_thread(accounts_store.list_accounts, _config_path())
        )
        socket = app_state.session_manager.tmux_socket_name()
        gate = asyncio.Semaphore(pane_account.READ_CONCURRENCY)

        async def one(key: Key, provider: str, conv_uuid: Optional[str]) -> None:
            started = _generation.get(key[0], 0)
            if provider == "antigravity":
                found = await asyncio.to_thread(_resolve_agy_account, app_state.session_manager, key[0], conv_uuid, accounts)
            else:
                found = await pane_account.resolve_pane_account(socket, key[0], provider, accounts, gate=gate)
            if _generation.get(key[0], 0) == started:
                _cache[key] = (found, time.monotonic())

        await asyncio.gather(*(one(k, p, cid) for k, (p, cid) in wanted.items()))
    except (FileNotFoundError, ValueError, OSError, RuntimeError) as exc:
        logger.warning("session_account_resolve_failed", error=type(exc).__name__)
        now = time.monotonic()
        for key in wanted:
            _cache.setdefault(key, (None, now))
    finally:
        _in_flight.difference_update(wanted)


def mark_session_account(app_state: Any, infos: Iterable[Any]) -> None:
    rows = list(infos)
    profiles = None
    if any(getattr(i, "agent_family", None) == "custom" for i in rows):
        from src.config import settings

        profiles = settings.get_launch_profiles()
    now = time.monotonic()
    wanted: Dict[Key, Tuple[str, Optional[str]]] = {}
    live: Set[Key] = set()
    for info in rows:
        provider = _provider_for(info, profiles)
        key = _key(info, profiles) if provider is not None else None
        if key is None or provider is None:
            info.account_id = None
            continue
        live.add(key)
        hit = _cache.get(key)
        info.account_id = hit[0] if hit else None
        stale = hit is None or (hit[0] is None and now - hit[1] >= RETRY_SECONDS)
        if stale and key not in _in_flight:
            wanted[key] = (provider, getattr(info, "claude_session_uuid", None))
    for key in [k for k in _cache if k not in live]:
        del _cache[key]
    if not wanted:
        return
    _in_flight.update(wanted)
    task = asyncio.get_running_loop().create_task(_resolve(app_state, wanted))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
