
from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

import structlog

from src.core import resource_push
from src.core.argent import health, notices, row_state, store
from src.core.argent import settings as settings_module
from src.core.resource_push import topics
from src.cplugs.sdk import turn_events

logger = structlog.get_logger()

DOWN_AFTER, HEALTHY_NEEDED = 3, 3
ERRORS_N, ERRORS_WINDOW, ERRORS_SESSIONS = 5, 120.0, 3
COOLDOWN_SECONDS, RETETHER_GAP_SECONDS = 600.0, 3600.0
KEY_TTL_SECONDS, KEY_WARN_LEAD_SECONDS, EXPIRY_ROLL_GAP = 24 * 3600.0, 1800.0, 600.0
TAIL_BYTES, READ_BYTES = 64 * 1024, 4 * 1024 * 1024
REASON_DOWN, REASON_ERRORS, PAUSE_REASON = "gateway down", "gateway errors", "gateway errors"
TETHERED_STATES = (row_state.PENDING, "tethered")


@dataclass
class _State:

    failures: int = 0
    healthy: int = 0
    down_since: Optional[float] = None
    err_since: Optional[float] = None
    retether_at: Optional[float] = None
    key_notified: bool = False
    last_expiry_roll: float = 0.0
    errors: Deque[Tuple[float, str, int]] = field(default_factory=deque)
    offsets: Dict[str, int] = field(default_factory=dict)
    unsubscribe: Optional[Any] = None
    loop: Optional["asyncio.AbstractEventLoop"] = None
    busy: Set[str] = field(default_factory=set)


_state = _State()


def is_active() -> bool:
    return _state.down_since is not None or _state.err_since is not None


def _reason() -> str:
    return REASON_DOWN if _state.down_since is not None else REASON_ERRORS if _state.err_since is not None else ""


def tethered_count(tenant: str) -> int:
    return sum(1 for r in row_state.rows(tenant) if r["state"] in TETHERED_STATES)


def view_sync(tenant: str) -> Dict[str, Any]:
    from src.core.argent import rollout_store

    roll = rollout_store.current(tenant)
    since = _state.down_since or _state.err_since
    return {"active": is_active(), "reason": _reason(), "since": since, "tethered": tethered_count(tenant) if tenant else 0,
            "key_expiring": len(expiring_refs(tenant, time.time())) if tenant else 0,
            "rollout_paused": bool(roll and roll["state"] == rollout_store.PAUSED and roll["reason"] == PAUSE_REASON)}


def _changed() -> None:
    resource_push.notify(topics.ARGENT_STATUS)


def reset() -> None:
    open_notice = is_active()
    key_notified = _state.key_notified
    _state.failures = _state.healthy = 0
    _state.down_since = _state.err_since = None
    _state.retether_at, _state.key_notified = None, False
    _state.errors.clear()
    _state.offsets.clear()
    if open_notice:
        notices.outage_resolved()
        _changed()
    if key_notified:
        notices.key_expiring_resolved()



def expiring_refs(tenant: str, now: float, *, state_dir: Optional[Path] = None) -> Set[str]:
    cutoff = now - (KEY_TTL_SECONDS - KEY_WARN_LEAD_SECONDS)
    with closing(store.open_db(state_dir)) as conn:
        return {str(r[0]) for r in conn.execute("SELECT session_ref FROM row_keys WHERE tenant_id = ? AND status = 'live' AND "
            "((key_expires_at > 0 AND key_expires_at <= ?) OR (key_expires_at = 0 AND minted_at <= ?))", (tenant, now + KEY_WARN_LEAD_SECONDS, cutoff))}


def record_retether(tenant: str, ref: str, reason: str, *, state_dir: Optional[Path] = None, clock: Any = time.time) -> None:
    with closing(store.open_db(state_dir)) as conn:
        conn.execute("INSERT INTO retether (tenant_id, session_ref, last_at, reason) VALUES (?, ?, ?, ?) ON CONFLICT(tenant_id, session_ref) "
                     "DO UPDATE SET last_at = excluded.last_at, reason = excluded.reason", (tenant, ref, float(clock()), reason))


def retether_blocked(tenant: str, ref: str, now: float, *, state_dir: Optional[Path] = None) -> bool:
    with closing(store.open_db(state_dir)) as conn:
        row = conn.execute("SELECT last_at FROM retether WHERE tenant_id = ? AND session_ref = ?", (tenant, ref)).fetchone()
    return row is not None and now - float(row[0]) < RETETHER_GAP_SECONDS


def direct_rows(tenant: str) -> List[str]:
    return [r["session_ref"] for r in row_state.rows(tenant) if r["state"] == row_state.NOT_TETHERED and r["reason"] == "argent down at launch"]



async def on_report(report: health.HealthReport, enabled: bool) -> None:
    if not enabled:
        if is_active() or _state.key_notified or _state.failures or _state.errors:
            reset()
        return
    now = time.time()
    if report.state == health.DOWN:
        _state.failures += 1
        _state.healthy = 0
    elif report.state == health.UP:
        _state.failures = 0
        _state.healthy += 1
    else:
        _state.failures = 0
        if report.state == health.CAP_TOO_LOW:
            _state.healthy = 0
    tenant = await asyncio.to_thread(_tenant)
    if _state.down_since is None and _state.failures >= DOWN_AFTER:
        _state.down_since, _state.retether_at = now, None
        await _announce(tenant)
    elif _state.down_since is not None and _state.healthy >= HEALTHY_NEEDED:
        _state.retether_at, _state.down_since = _state.down_since + COOLDOWN_SECONDS, None
        await _settle()
    await _evaluate(tenant, now)
    if _state.retether_at is not None and now >= _state.retether_at and _state.healthy >= HEALTHY_NEEDED:
        _state.retether_at = None
        await _retether(tenant)
    if tenant and report.state == health.UP:
        await _watch_keys(tenant, now)


def _tenant() -> str:
    from src.core.argent import rollout

    return rollout.tenant_id()


async def _announce(tenant: str) -> None:
    count = await asyncio.to_thread(tethered_count, tenant) if tenant else 0
    notices.outage(count, _reason())
    _changed()


async def _settle() -> None:
    if not is_active():
        notices.outage_resolved()
        _changed()



def _purge(now: float) -> None:
    while _state.errors and now - _state.errors[0][0] > ERRORS_WINDOW:
        _state.errors.popleft()


def signal_raised() -> bool:
    if not _state.errors:
        return False
    if any(status == 413 for _, _, status in _state.errors):
        return True
    per: Dict[str, int] = {}
    for _, sid, _ in _state.errors:
        per[sid] = per.get(sid, 0) + 1
    return len(_state.errors) >= ERRORS_N and (max(per.values()) >= ERRORS_N or len(per) >= ERRORS_SESSIONS)


async def _evaluate(tenant: str, now: float) -> None:
    _purge(now)
    if signal_raised():
        if any(status == 413 for _, _, status in _state.errors):
            from src.core.argent import rollout

            await rollout.pause(PAUSE_REASON)
        if _state.err_since is None:
            was_active = is_active()
            _state.err_since = now
            if not was_active:
                await _announce(tenant)
            else:
                _changed()
    elif _state.err_since is not None:
        _state.err_since = None
        if _state.down_since is None:
            await _settle()
            await _resume_paused()
        else:
            _changed()


async def _resume_paused() -> None:
    from src.core.argent import rollout, rollout_store

    tenant = await asyncio.to_thread(_tenant)
    roll = await asyncio.to_thread(rollout_store.current, tenant)
    if roll is not None and roll["state"] == rollout_store.PAUSED and roll["reason"] == PAUSE_REASON:
        await rollout.resume()
        rollout.ensure_running()


def scan_transcript(path: Path, key: str, now: float) -> List[Tuple[float, int]]:
    try:
        size = os.stat(path).st_size
        offset = _state.offsets.get(key)
        mid_line = offset is None
        offset = max(0, size - TAIL_BYTES) if offset is None else (offset if offset <= size else 0)
        with open(path, "rb") as handle:
            handle.seek(offset)
            data = handle.read(min(READ_BYTES, size - offset))
    except OSError:
        return []
    _state.offsets[key] = offset + len(data)
    lines = data.split(b"\n")
    if mid_line and offset > 0:
        lines = lines[1:]
    found: List[Tuple[float, int]] = []
    for raw in lines:
        if b"isApiErrorMessage" not in raw:
            continue
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        status = record.get("apiErrorStatus") if isinstance(record, dict) else None
        if not isinstance(record, dict) or record.get("isApiErrorMessage") is not True or isinstance(status, bool) or not isinstance(status, int):
            continue
        if status != 413 and not 500 <= status <= 599:
            continue
        when = _when(record.get("timestamp"), now)
        if now - when <= ERRORS_WINDOW:
            found.append((when, status))
    return found


def _when(stamp: Any, now: float) -> float:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return now


async def handle_turn_end(session_id: str) -> int:
    from src.core.argent import fallback_spend, session_ref, work_items
    from src.core.session_token_usage import claude_reader
    from src.core.session_transcript_presence import CONVERSATION_PRESENT

    manager = fallback_spend.session_manager()
    if manager is None or session_id in _state.busy:
        return 0
    _state.busy.add(session_id)
    try:
        cfg = await asyncio.to_thread(settings_module.read)
        info = await manager.get_session_info(session_id)
        if not cfg.enabled or info is None or info.session is None or not info.tmux_session or str(info.session.id).startswith("remote:"):
            return 0
        if (info.agent_family or "claude") != "claude":
            return 0
        tenant = await asyncio.to_thread(work_items.current_tenant)
        if not tenant or (await asyncio.to_thread(row_state.lookup, tenant, info.tmux_session))["state"] not in TETHERED_STATES:
            return 0
        uuid = await asyncio.to_thread(manager.claude_uuid_for_tmux_name, info.tmux_session)
        found = await asyncio.to_thread(claude_reader.locate_transcript, uuid, working_dir=info.session.working_dir or "") if uuid else None
        if found is None or found.outcome != CONVERSATION_PRESENT:
            return 0
        now = time.time()
        records = await asyncio.to_thread(scan_transcript, found.path, session_id, now)
        for when, status in records:
            _state.errors.append((when, await asyncio.to_thread(session_ref.ref_for_name, tenant, info.tmux_session), status))
        if records:
            logger.info("argent_gateway_errors_seen", count=len(records))
            await _evaluate(tenant, now)
        return len(records)
    except (OSError, ValueError) as exc:
        logger.warning("argent_outage_turn_end_failed", error_type=type(exc).__name__)
        return 0
    finally:
        _state.busy.discard(session_id)


def _on_turn_end(session_id: Optional[str]) -> None:
    if session_id and _state.loop is not None and not _state.loop.is_closed():
        _state.loop.create_task(handle_turn_end(session_id))



async def _watch_keys(tenant: str, now: float) -> None:
    from src.core.argent import rollout, rollout_store

    refs = await asyncio.to_thread(expiring_refs, tenant, now)
    if not refs:
        if _state.key_notified:
            _state.key_notified = False
            notices.key_expiring_resolved()
        return
    if not _state.key_notified:
        _state.key_notified = True
        notices.key_expiring(len(refs))
    roll = await asyncio.to_thread(rollout_store.current, tenant)
    if (roll is None or roll["state"] not in (rollout_store.RUNNING, rollout_store.PAUSED)) and now - _state.last_expiry_roll >= EXPIRY_ROLL_GAP:
        _state.last_expiry_roll = now
        await rollout.begin("on")
        rollout.ensure_running()


async def _retether(tenant: str) -> None:
    from src.core.argent import rollout, rollout_store

    roll = await asyncio.to_thread(rollout_store.current, tenant)
    if roll is not None and roll["state"] == rollout_store.PAUSED and roll["reason"] == PAUSE_REASON:
        await rollout.resume()
        rollout.ensure_running()
    elif (roll is None or roll["state"] != rollout_store.RUNNING) and tenant and await asyncio.to_thread(direct_rows, tenant):
        await rollout.begin("on")
        rollout.ensure_running()


async def restart_direct(manager: Any) -> Dict[str, Any]:
    from src.core.argent import rollout
    from src.core.hosts.identity import is_remote_info

    if not is_active():
        raise LookupError("no_outage")
    tenant = await asyncio.to_thread(_tenant)
    engine = rollout.RolloutEngine(manager)
    restarted, waiting = 0, {}
    for info in await manager.list_session_infos():
        if info.agent_family not in rollout.FAMILIES or not info.tmux_session or info.session is None or is_remote_info(info):
            continue
        if (await asyncio.to_thread(row_state.lookup, tenant, info.tmux_session))["state"] not in TETHERED_STATES:
            continue
        outcome = await engine.restart_direct(info)
        if outcome == "ok":
            restarted += 1
        else:
            waiting[outcome] = waiting.get(outcome, 0) + 1
    return {"restarted": restarted, "waiting": waiting}


def start() -> None:
    if _state.unsubscribe is not None:
        return
    _state.loop = asyncio.get_running_loop()
    _state.unsubscribe = turn_events.subscribe(_on_turn_end)


def stop() -> None:
    unsubscribe, _state.unsubscribe = _state.unsubscribe, None
    if unsubscribe is not None:
        unsubscribe()
    reset()
    _state.loop = None
    _state.busy.clear()


def is_running() -> bool:
    return _state.unsubscribe is not None
