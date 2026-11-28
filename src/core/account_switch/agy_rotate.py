
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.config.provider_accounts import ProviderAccount
from src.core.account_switch import auto_switch, limit_rotate, store
from src.core.account_switch.decide import rank_candidates
from src.core.account_switch.rotate_state import RotationState
from src.core.agy import accounts as agy_accounts, ledger as agy_ledger
from src.core.agy.identity import row_is_agy
from src.core.agy.state import quota_exhausted, read_state
from src.core.attention.agy_conversation import agy_pid_under
from src.core.hosts.identity import is_remote_info
from src.core.provider_ledger import accounts_store
from src.core.session_respawn import LIVE_RESTART_REASON_USAGE_LIMIT_ROTATION
from src.models.activity_status import RESTING
from src.models.provider_ledger import LedgerSnapshot

logger = structlog.get_logger()

PROVIDER = "antigravity"

MAX_RESTARTS_PER_PASS = 4

RECORD_BLOCK_SECONDS = 5 * 3600

_RUNNING = False
_STATE = RotationState()


class CaptureError(Exception):

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _state_dir() -> Path:
    from src.config import settings

    return Path(settings.get_state_dir())


def _config_path() -> Path:
    from src.config import settings

    return Path(settings.auth_config_file).expanduser()


def activate_account(config_path: Path, account_id: str, *, state_dir: Optional[Path] = None) -> None:
    current = store.read_switch(config_path).active_for(PROVIDER)
    agy_accounts.activate(
        account_id, current_id=current, state_dir=state_dir or _state_dir(),
        move_pointer=lambda picked: store.set_active(config_path, PROVIDER, picked),
    )


def capture_account(config_path: Path, *, state_dir: Optional[Path] = None) -> Tuple[ProviderAccount, bool]:
    state = agy_ledger.newest_state(state_dir or _state_dir())
    if state is None:
        raise CaptureError("no_identity")
    email = str(state["email"]).strip()
    account_id = agy_accounts.account_id_for_email(email)
    try:
        agy_accounts.snapshot(account_id)
    except agy_accounts.AgyAccountError as exc:
        if exc.code == "no_live_login":
            raise CaptureError("no_live_login") from None
        raise
    display_name = (email.split("@", 1)[0].strip() or email)[:80]
    existing = next((a for a in accounts_store.list_accounts(config_path) if a.id == account_id), None)
    account = existing or ProviderAccount(id=account_id, name=display_name, provider=PROVIDER)
    if existing is None:
        accounts_store.upsert_account(config_path, account)
    store.set_active(config_path, PROVIDER, account_id)
    return account, existing is None


def live_agy_sessions(infos: List[Any], parents: Dict[int, int], commands: Dict[int, str], state_dir: Path) -> List[Tuple[Any, Optional[Dict[str, Any]]]]:
    out: List[Tuple[Any, Optional[Dict[str, Any]]]] = []
    for info in infos:
        if is_remote_info(info) or info.activity_status == "dead" or not info.tmux_session:
            continue
        if not row_is_agy({"agent_family": info.agent_family, "agent_type": info.agent_type}):
            continue
        pid = agy_pid_under(info.session.pty_pid, parents, commands)
        out.append((info, read_state(state_dir, pid)))
    return out


def pick_target(rows: List[Any], *, capped_id: str, threshold: float, now: datetime, has_copy=None) -> Optional[str]:
    has_copy = has_copy or agy_accounts.has_copy
    for row in rank_candidates(rows, provider=PROVIDER, active_account_id=capped_id, threshold_percent=threshold, now=now):
        if has_copy(row.id):
            return row.id
    return None


async def _restart_one(manager: Any, rotation: Any, info: Any) -> bool:
    from src.core.launch_profiles.resolve import LaunchProfileNotFound
    from src.core.launch_profiles.secrets import SecretError
    from src.core.pack.identity.home import ProjectMovedAway
    from src.core.sessions.guarded_paste import PasteRefused
    from src.core.swarm.switch import BodyHeld

    try:
        result = await manager.respawn_session(
            info.tmux_session, live_restart_confirmed=True, require_agent_resume=True, persist_account=False,
            live_restart_reason=LIVE_RESTART_REASON_USAGE_LIMIT_ROTATION,
        )
    except (LaunchProfileNotFound, SecretError, ProjectMovedAway, BodyHeld, ValueError) as exc:
        logger.info("agy_rotation_restart_refused", tmux_session=info.tmux_session, error=type(exc).__name__)
        return False
    if not (isinstance(result, dict) and result.get("ok") is True and result.get("kind") == "agent"):
        logger.warning("agy_rotation_restart_not_ok", tmux_session=info.tmux_session)
        return False
    if await rotation.wait_ready(info.session.id):
        ready = await manager.get_session_info(info.session.id)
        if ready is not None:
            try:
                await rotation.paste_continue(ready, await rotation.session_uuid(ready))
            except PasteRefused as exc:
                logger.info("agy_rotation_continue_refused", tmux_session=info.tmux_session, code=exc.code)
    return True


async def rotate(manager: Any, app_state: Any, snapshot: LedgerSnapshot, accounts: List[ProviderAccount], switch: Any, *,
                 config_path: Path, state_dir: Path, now: datetime, parents: Dict[int, int], commands: Dict[int, str]) -> List[str]:
    sessions = live_agy_sessions(await manager.list_session_infos(), parents, commands, state_dir)
    if not any(quota_exhausted(state) for _, state in sessions):
        return []
    capped_id = switch.active_for(PROVIDER)
    if capped_id is None or not any(a.id == capped_id and a.provider == PROVIDER for a in accounts):
        logger.info("agy_rotation_skip", gate="no_active_account")
        return []
    record = "agy:%s:%d" % (capped_id, int(now.timestamp() // RECORD_BLOCK_SECONDS))
    allowed, why = _STATE.may_restart(record)
    if not allowed:
        logger.info("agy_rotation_skip", gate=why or "attempt_limit")
        return []
    target = pick_target(snapshot.accounts, capped_id=capped_id, threshold=switch.threshold_percent, now=now)
    if target is None:
        logger.info("agy_rotation_skip", gate="no_target")
        return []
    _STATE.record_attempt(record)
    try:
        await asyncio.to_thread(activate_account, config_path, target, state_dir=state_dir)
    except (agy_accounts.AgyAccountError, FileNotFoundError, ValueError, OSError) as exc:
        logger.warning("agy_rotation_swap_failed", target=target, error=type(exc).__name__)
        return []
    auto_switch.record_switch(app_state, provider=PROVIDER, from_account_id=capped_id, to_account_id=target, reason="limit_rotated")
    rotation = limit_rotate.Rotation(app_state, lambda: config_path)
    todo = [info for info, state in sessions if quota_exhausted(state) or (info.activity_status in RESTING and info.activity_hint is None)]
    semaphore = asyncio.Semaphore(MAX_RESTARTS_PER_PASS)

    async def one(info: Any) -> Optional[str]:
        async with semaphore:
            return info.tmux_session if await _restart_one(manager, rotation, info) else None

    restarted = [name for name in await asyncio.gather(*(one(i) for i in todo)) if name]
    logger.info("agy_limit_rotated", from_account_id=capped_id, to_account_id=target, restarted=len(restarted), sessions=len(sessions))
    return restarted


async def after_pass(snapshot: LedgerSnapshot, app_state: Any = None) -> List[str]:
    global _RUNNING
    manager = getattr(app_state, "session_manager", None) if app_state is not None else None
    if manager is None or _RUNNING:
        return []
    path = _config_path()
    try:
        switch = await asyncio.to_thread(store.read_switch, path)
        if not switch.auto_switch or switch.active_for(PROVIDER) is None:
            return []
        accounts = await asyncio.to_thread(accounts_store.list_accounts, path)
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.warning("agy_rotation_config_unreadable", error=type(exc).__name__)
        return []
    if not any(a.provider == PROVIDER for a in accounts):
        return []
    from src.core.claude_resume_argv import list_process_table

    rows = await asyncio.to_thread(list_process_table)
    if not rows:
        return []
    _RUNNING = True
    try:
        return await rotate(manager, app_state, snapshot, accounts, switch, config_path=path, state_dir=_state_dir(),
                            now=datetime.now(timezone.utc), parents={r.pid: r.ppid for r in rows}, commands={r.pid: r.command for r in rows})
    finally:
        _RUNNING = False
