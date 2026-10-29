
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

import structlog
from fastapi import HTTPException

from src.core.pack.identity.home import ProjectMovedAway
from src.config.provider_account_switch import ProviderAccountSwitchConfig
from src.config.provider_accounts import ProviderAccount
from src.core.account_switch import limit_detect, limit_rotate, pane_account, store
from src.core.account_switch.rotate_state import RotationState
from src.core.attention.usage_limit import LimitStop
from src.core.hosts.identity import is_remote_info
from src.core.launch_profiles.resolve import LaunchProfileNotFound
from src.core.launch_profiles.secrets import SecretError
from src.core.provider_ledger import accounts_store, poller_scan
from src.core.provider_ledger.login_command import PROFILE_ENV_VARS
from src.core.session_delivery.bring_up import READY_STATUSES
from src.core.session_respawn import LIVE_RESTART_REASON_USAGE_LIMIT_ROTATION
from src.core.session_resume_target import CONVERSATION_RESUMED
from src.core.swarm.switch import BodyHeld
from src.core.tmux_discovery import tmux_argv_prefix
from src.models.provider_ledger import LedgerSnapshot

logger = structlog.get_logger()

PROVIDER = "claude"

RESTARTABLE_STATUSES = frozenset({"idle"})

QUIET_SECONDS = 120

MAX_RECORD_AGE_SECONDS = 8 * 24 * 3600

MAX_RESTARTS_PER_PASS = 3

SKIP_LOG_REPEAT_SECONDS = 10 * 60

TRANSCRIPT_TAIL_BYTES = 256 * 1024

_RUNNING = False

_SKIP_LOGGED: Dict[str, Tuple[str, float]] = {}

_STATE = RotationState()


@dataclass(frozen=True)
class Restart:

    tmux_session: str
    session_id: str
    from_account_id: str
    to_account_id: str
    ok: bool


def at_rest(info: Any) -> bool:
    """Is this row idle with nothing of its own still running?

    Description: ``idle`` alone is not enough. Claude's registry ``shell`` status is a REST status ("idle AND a
      shell command claude started is still open", issue #261) and survives only as ``activity_hint``; any hint
      at all refuses. No longer the rotation's gate (a limit stop never reads idle); the auto-sleeper reuses it.
    Inputs: info (SessionInfo) - wrapper fields ``activity_status`` and ``activity_hint`` (gotcha 1).
    Output: bool.
    """
    return info.activity_status in RESTARTABLE_STATUSES and info.activity_hint is None


def log_skip(name: str, gate: str, now: float, **extra: Any) -> None:
    last = _SKIP_LOGGED.get(name)
    if last is not None and last[0] == gate and now - last[1] < SKIP_LOG_REPEAT_SECONDS:
        return
    _SKIP_LOGGED[name] = (gate, now)
    logger.info("auto_restart_skipped", tmux_session=name, gate=gate, **extra)


def read_transcript_tail(path: Path) -> List[Dict[str, Any]]:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > TRANSCRIPT_TAIL_BYTES:
                handle.seek(size - TRANSCRIPT_TAIL_BYTES)
                handle.readline()
            raw = handle.read()
    except OSError as exc:
        logger.debug("auto_restart_transcript_unreadable", error=type(exc).__name__)
        return []
    records: List[Dict[str, Any]] = []
    for line in raw.splitlines():
        try:
            record = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


async def _tmux_output(socket: str, *args: str) -> Optional[str]:
    """One tmux command's stdout, or None when it could not answer."""
    argv = tmux_argv_prefix(socket) + list(args)
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return None
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), pane_account.READ_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return None
    return stdout.decode("utf-8", errors="replace") if proc.returncode == 0 else None


class SessionEvidence:

    def __init__(self, manager: Any) -> None:
        self._manager = manager
        self._seen: Dict[str, Tuple[Path, Tuple[int, int], Optional[LimitStop]]] = {}

    async def limit_stop(self, info: Any) -> Optional[LimitStop]:
        stop = await self._transcript_stop(info)
        if stop is not None:
            return stop
        out = await _tmux_output(self._manager._tmux_socket_name(), "capture-pane", "-p", "-t", f"={info.tmux_session}:")
        label = limit_detect.pane_stop_label(out)
        if label is None:
            return None
        now = datetime.now(timezone.utc)
        conversation = await asyncio.to_thread(self._manager._claude_uuid_for_tmux_name, info.tmux_session)
        return LimitStop(
            uuid=f"{limit_detect.PANE_STOP_PREFIX}{conversation or info.tmux_session}:{label}:{now.date().isoformat()}",
            timestamp=now, resets_at=None, rate_limit_type=None,
        )

    async def _transcript_stop(self, info: Any) -> Optional[LimitStop]:
        from src.core.session_token_usage.claude_reader import locate_transcript

        name = info.tmux_session
        uuid = await asyncio.to_thread(self._manager._claude_uuid_for_tmux_name, name)
        if not uuid:
            return None
        working_dir = info.session.working_dir if info.session is not None else None
        location = await asyncio.to_thread(locate_transcript, uuid, working_dir=working_dir)
        if location.path is None:
            return None
        try:
            stat = await asyncio.to_thread(location.path.stat)
        except OSError:
            return None
        signature = (stat.st_mtime_ns, stat.st_size)
        cached = self._seen.get(name)
        if cached is not None and cached[0] == location.path and cached[1] == signature:
            return cached[2]
        records = await asyncio.to_thread(read_transcript_tail, location.path)
        stop = limit_detect.last_limit_stop(records)
        if stop is not None and stop.uuid is None:
            stop = None
        self._seen[name] = (location.path, signature, stop)
        return stop

    async def body_started_at(self, info: Any) -> Optional[datetime]:
        watcher = getattr(self._manager, "_attention_watcher", None)
        observation = watcher.observation_for(info.session.id) if watcher is not None else None
        if observation is None:
            return None
        registry = observation.evidence.registry
        starts = [
            at for at in (registry.started_at if registry.known else None, observation.evidence.process_floor_at)
            if at is not None
        ]
        try:
            return max(starts) if starts else None
        except TypeError:
            return None

    async def resumable(self, name: str) -> bool:
        socket = self._manager._tmux_socket_name()
        target = await asyncio.to_thread(
            self._manager._resume_target_for_tmux_name, name, socket
        )
        return target.outcome == CONVERSATION_RESUMED

    async def quiet_seconds(self, name: str) -> Optional[float]:
        out = await _tmux_output(
            self._manager._tmux_socket_name(),
            "display-message", "-p", "-t", f"={name}:", "#{window_activity}",
        )
        try:
            return time.time() - int((out or "").strip())
        except ValueError:
            return None


async def restart_blocked_sessions(
    manager: Any,
    snapshot: LedgerSnapshot,
    accounts: List[ProviderAccount],
    switch: ProviderAccountSwitchConfig,
    *,
    app_state: Any = None,
    now: Optional[datetime] = None,
    monotonic: Callable[[], float] = time.monotonic,
    evidence: Optional[Any] = None,
    read_profile: Callable[..., Awaitable[pane_account.PaneProfile]] = pane_account.read_pane_profile,
    current_switch: Optional[Callable[[], ProviderAccountSwitchConfig]] = None,
    rotation: Optional[Any] = None,
    state: Optional[RotationState] = None,
) -> List[Restart]:
    global _RUNNING
    if not switch.auto_switch or _RUNNING:
        return []
    _RUNNING = True
    try:
        return await _pass(
            manager, snapshot, accounts, switch,
            now=now or datetime.now(timezone.utc),
            monotonic=monotonic,
            evidence=evidence or SessionEvidence(manager),
            read_profile=read_profile,
            current_switch=current_switch or _default_switch,
            rotation=rotation or limit_rotate.Rotation(app_state, _config_path),
            state=state or _STATE,
        )
    finally:
        _RUNNING = False


def _restartable(info: Any, stop: Optional[LimitStop]) -> bool:
    if info.activity_status == "dead":
        return False
    return info.activity_hint is None or limit_detect.is_pane_stop(stop)


async def _quiet_for(evidence: Any, name: str, stop: LimitStop, now: datetime) -> Optional[float]:
    """How long has this limit-stopped pane been quiet? Output: seconds, or None when the pane could not be measured.

    Description: the longer of the tmux silence and the age of the stop record, because Claude's limit screen
      repaints forever while the transcript says it stopped long ago. No record timestamp: tmux alone.
    Inputs: evidence; name (tmux session); stop (LimitStop); now (aware datetime). Example: tmux 2 s, record
      3 minutes old -> 180.0.
    """
    tmux_quiet = await evidence.quiet_seconds(name)
    if tmux_quiet is None or stop.timestamp is None:
        return tmux_quiet
    return max(tmux_quiet, (now - stop.timestamp).total_seconds())


def _ready(info: Any) -> bool:
    return info.activity_status in READY_STATUSES and info.activity_hint is None


async def _pass(manager, snapshot, accounts, switch, *, now, monotonic, evidence, read_profile,
                current_switch, rotation, state) -> List[Restart]:
    rows = [row for row in snapshot.accounts if row.provider == PROVIDER]
    socket = manager._tmux_socket_name()
    made: List[Restart] = []
    seen: Set[str] = set()
    names = {row.id: row.name for row in rows if row.name}
    infos = await manager.list_session_infos()
    if not state.baselined():
        await _take_baseline(infos, evidence, state, now)
    for info in infos:
        name = info.tmux_session
        if info.agent_family != PROVIDER or not name or info.session is None:
            continue
        if is_remote_info(info):
            continue
        seen.add(name)

        def skip(gate: str, _name: str = name, **extra: Any) -> None:
            log_skip(_name, gate, monotonic(), **extra)

        stop = await evidence.limit_stop(info) if info.activity_status != "dead" else None
        if not _restartable(info, stop):
            skip("dead_or_shell_open", status=info.activity_status, hint=info.activity_hint)
            continue
        if stop is None:
            skip("no_limit_stop")
            continue
        if stop.timestamp is None or (now - stop.timestamp).total_seconds() > MAX_RECORD_AGE_SECONDS:
            skip("stale_record")
            continue
        record_id = stop.uuid
        if state.pre_existing(record_id):
            skip("pre_existing")
            continue
        if state.continue_sent(record_id):
            skip("already_continued")
            continue
        account_id = pane_account.account_for_profile(
            accounts, PROVIDER, await read_profile(socket, name, PROFILE_ENV_VARS[PROVIDER])
        )
        if account_id is None:
            skip("account_unknown")
            continue
        if stop.resets_at is not None and stop.resets_at > now:
            state.note_cap(account_id, stop.resets_at.timestamp())
        session_uuid = await rotation.session_uuid(info)
        if session_uuid is None:
            skip("no_durable_key")
            continue

        def notice(outcome: str, to_id: str, moved: bool = False) -> None:
            if state.claim_notice(record_id, outcome):
                rotation.notify(outcome, session=name, from_account_id=account_id, to_account_id=to_id,
                                limit_kind=stop.kind, moved=moved, from_name=names.get(account_id, ""),
                                to_name=names.get(to_id, ""))

        try:
            pinned = await rotation.pin_for(session_uuid)
        except limit_rotate.PinUnreadable:
            skip("pin_unreadable")
            continue
        if pinned:
            notice(limit_rotate.PINNED, account_id)
            skip("pinned")
            continue
        quiet = await _quiet_for(evidence, name, stop, now)
        if quiet is None or quiet < QUIET_SECONDS:
            skip("quiet_window", quiet_seconds=None if quiet is None else int(quiet))
            continue
        started = await evidence.body_started_at(info)
        if started is not None and started > stop.timestamp:
            if not _ready(info):
                skip("restarted_not_ready", status=info.activity_status)
                continue
            if await _continue(manager, evidence, rotation, state, info, stop, session_uuid, quiet_floor=True, now=now):
                notice(limit_rotate.RESUMED, account_id)
            else:
                skip("continue_not_sent")
            continue
        if len(made) >= MAX_RESTARTS_PER_PASS:
            skip("pass_limit")
            continue
        allowed, gate = state.may_restart(record_id)
        if not allowed:
            skip(gate)
            continue
        if not await evidence.resumable(name):
            skip("would_not_resume")
            continue
        in_place = stop.resets_at is not None and stop.resets_at <= now
        target_id = account_id if in_place else await limit_rotate.pick_target(
            rows, accounts, capped_id=account_id, threshold=switch.threshold_percent, now=now,
            launchable=rotation.launchable, excluded=state.capped_accounts(),
        )
        if target_id is None:
            skip("no_target")
            continue
        if not (await asyncio.to_thread(current_switch)).auto_switch:
            skip("recheck_switch_changed")
            continue
        fresh = await manager.get_session_info(info.session.id)
        fresh_stop = await evidence.limit_stop(fresh) if fresh is not None and fresh.activity_status != "dead" else None
        if fresh is None or not _restartable(fresh, fresh_stop):
            skip("recheck_not_restartable")
            continue
        if fresh_stop is None or fresh_stop.uuid != record_id:
            skip("recheck_new_last_turn")
            continue
        quiet = await _quiet_for(evidence, name, fresh_stop, now)
        if quiet is None or quiet < QUIET_SECONDS:
            skip("recheck_quiet_window")
            continue
        try:
            if await rotation.pin_for(session_uuid):
                skip("recheck_pinned")
                continue
        except limit_rotate.PinUnreadable:
            skip("pin_unreadable")
            continue
        _SKIP_LOGGED.pop(name, None)
        state.record_attempt(record_id)
        moved = False
        if not in_place:
            moved = await rotation.move_pointer(accounts, switch, account_id, target_id)
        ok = await _restart(manager, socket, name, accounts, target_id, read_profile, skip)
        logger.info(
            "provider_account_auto_restarted", tmux_session=name, from_account_id=account_id,
            to_account_id=target_id, ok=ok, in_place=in_place,
        )
        made.append(Restart(name, info.session.id, account_id, target_id, ok))
        if not ok:
            notice(limit_rotate.FAILED, target_id)
            continue
        if not await rotation.wait_ready(info.session.id):
            notice(limit_rotate.FAILED, target_id)
            continue
        ready = await manager.get_session_info(info.session.id)
        if ready is not None and await _continue(manager, evidence, rotation, state, ready, stop, session_uuid):
            notice(limit_rotate.CONTINUED if in_place else limit_rotate.ROTATED, target_id, moved)
        else:
            notice(limit_rotate.FAILED, target_id)
    for gone in [n for n in _SKIP_LOGGED if n not in seen]:
        del _SKIP_LOGGED[gone]
    return made


async def _take_baseline(infos, evidence, state, now) -> None:
    records: Dict[str, Optional[float]] = {}
    scanned = False
    for info in infos:
        if info.agent_family != PROVIDER or not info.tmux_session or info.session is None or is_remote_info(info):
            continue
        scanned = True
        stop = await evidence.limit_stop(info)
        if stop is not None and stop.uuid is not None:
            records[stop.uuid] = stop.resets_at.timestamp() if stop.resets_at is not None else None
    if scanned:
        state.take_baseline(records)
        logger.info("limit_rotation_baseline_taken", records=len(records))


async def _restart(manager, socket, name, accounts, target_id, read_profile, skip) -> bool:
    try:
        result = await manager.respawn_session(
            name, live_restart_confirmed=True, require_agent_resume=True, account_id=target_id,
            account_pinned=False, persist_account=False, live_restart_reason=LIVE_RESTART_REASON_USAGE_LIMIT_ROTATION,
        )
    except (LaunchProfileNotFound, SecretError):
        skip("launch_profile_unavailable")
        return False
    except ProjectMovedAway:
        skip("project_moved_away")
        return False
    except BodyHeld:
        skip("swarm_off")
        return False
    except ValueError:
        skip("target_not_launchable")
        return False
    after = pane_account.account_for_profile(
        accounts, PROVIDER, await read_profile(socket, name, PROFILE_ENV_VARS[PROVIDER])
    )
    return (
        isinstance(result, dict)
        and result.get("ok") is True
        and result.get("kind") == "agent"
        and result.get("conversation") == CONVERSATION_RESUMED
        and after == target_id
    )


async def _continue(manager, evidence, rotation, state, info, stop, session_uuid, *, quiet_floor: bool = False,
                    now: Optional[datetime] = None) -> bool:
    if quiet_floor:
        fresh = await manager.get_session_info(info.session.id)
        fresh_stop = await evidence.limit_stop(fresh) if fresh is not None else None
        quiet = await _quiet_for(evidence, info.tmux_session, stop, now or datetime.now(timezone.utc))
        if fresh is None or not _ready(fresh) or fresh_stop is None or fresh_stop.uuid != stop.uuid \
                or quiet is None or quiet < QUIET_SECONDS:
            return False
    try:
        await rotation.paste_continue(info, session_uuid)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        logger.info("limit_rotation_continue_refused", tmux_session=info.tmux_session, code=detail.get("code", "refused"))
        return False
    state.mark_continue_sent(stop.uuid)
    return True


def _config_path() -> Path:
    from src.config import settings

    return Path(settings.auth_config_file).expanduser()


def _default_switch() -> ProviderAccountSwitchConfig:
    return store.read_switch(_config_path())


async def after_pass(
    snapshot: LedgerSnapshot,
    app_state: Any = None,
    *,
    config_path: Optional[Callable[[], Path]] = None,
) -> List[Restart]:
    manager = getattr(app_state, "session_manager", None) if app_state is not None else None
    if manager is None:
        return []
    path = config_path() if config_path is not None else _config_path()
    try:
        switch = await asyncio.to_thread(store.read_switch, path)
        if not switch.auto_switch:
            return []
        accounts = poller_scan.with_auto_default(await asyncio.to_thread(accounts_store.list_accounts, path))
    except (FileNotFoundError, ValueError, OSError) as exc:
        logger.warning("account_auto_restart_config_unreadable", error=type(exc).__name__)
        return []
    return await restart_blocked_sessions(
        manager, snapshot, accounts, switch, app_state=app_state
    )
