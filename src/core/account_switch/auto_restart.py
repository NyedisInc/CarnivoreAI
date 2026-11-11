
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
from src.core.attention.screen_read import capture_screen, read_screen, shared_screens
from src.core.attention.screen_reuse import ScreenReuse
from src.core.attention.usage_limit import LimitStop
from src.core.hosts.identity import is_remote_info
from src.core.launch_profiles.resolve import LaunchProfileNotFound
from src.core.launch_profiles.secrets import SecretError
from src.core.provider_ledger import accounts_store, poller_scan
from src.core.provider_ledger.login_command import PROFILE_ENV_VARS
from src.core.session_delivery import bring_up
from src.core.session_delivery.bring_up import READY_STATUSES
from src.core.session_respawn import LIVE_RESTART_REASON_USAGE_LIMIT_ROTATION
from src.core.session_resume_target import CONVERSATION_RESUMED
from src.core.swarm.switch import BodyHeld
from src.core.tmux_control.reader import control_read_async
from src.core.tmux_discovery import tmux_argv_prefix
from src.models.provider_ledger import LedgerSnapshot

logger = structlog.get_logger()

PROVIDER = "claude"

RESTARTABLE_STATUSES = frozenset({"idle"})

QUIET_SECONDS = 120

MAX_RECORD_AGE_SECONDS = 8 * 24 * 3600

MAX_RESTARTS_PER_PASS = 4

SKIP_LOG_REPEAT_SECONDS = 10 * 60

TRANSCRIPT_TAIL_BYTES = 256 * 1024

PANE_REUSE_SECONDS = 300.0

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
    answered = await control_read_async(socket, args)
    if answered is not None:
        return answered.decode("utf-8", errors="replace")
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

    def __init__(self, manager: Any, screens: Optional[ScreenReuse] = None) -> None:
        self._manager = manager
        self._screens = screens if screens is not None else shared_screens()
        self._seen: Dict[str, Tuple[Path, Tuple[int, int], Optional[LimitStop]]] = {}

    async def limit_stop(self, info: Any, *, row: Optional[Dict[str, Any]] = None, force: bool = False) -> Optional[LimitStop]:
        stop = await self._transcript_stop(info)
        if stop is not None:
            return stop
        out = await self._pane_screen(info.tmux_session, row or {}, force)
        label = limit_detect.pane_stop_label(out)
        if label is None:
            return None
        now = datetime.now(timezone.utc)
        conversation = await asyncio.to_thread(self._manager.claude_uuid_for_tmux_name, info.tmux_session)
        return LimitStop(
            uuid=f"{limit_detect.PANE_STOP_PREFIX}{conversation or info.tmux_session}:{label}:{now.date().isoformat()}",
            timestamp=now, resets_at=None, rate_limit_type=None,
        )

    async def _pane_screen(self, name: str, row: Dict[str, Any], force: bool) -> Optional[str]:
        socket = self._manager.tmux_socket_name()
        return await asyncio.to_thread(
            read_screen, self._screens, (socket, name), row, lambda: capture_screen(socket, name),
            force=force, max_reuse_seconds=PANE_REUSE_SECONDS,
        )

    async def _transcript_stop(self, info: Any) -> Optional[LimitStop]:
        from src.core.session_token_usage.claude_reader import locate_transcript

        name = info.tmux_session
        uuid = await asyncio.to_thread(self._manager.claude_uuid_for_tmux_name, name)
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

    async def body_pid(self, info: Any) -> Optional[int]:
        watcher = getattr(self._manager, "_attention_watcher", None)
        observation = watcher.observation_for(info.session.id) if watcher is not None else None
        if observation is None:
            return None
        registry = observation.evidence.registry
        return registry.pid if registry.known else None

    async def resumable(self, name: str) -> bool:
        socket = self._manager.tmux_socket_name()
        target = await asyncio.to_thread(
            self._manager._resume_target_for_tmux_name, name, socket
        )
        return target.outcome == CONVERSATION_RESUMED

    async def quiet_seconds(self, name: str) -> Optional[float]:
        out = await _tmux_output(
            self._manager.tmux_socket_name(),
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
    tmux_quiet = await evidence.quiet_seconds(name)
    if tmux_quiet is None or stop.timestamp is None:
        return tmux_quiet
    return max(tmux_quiet, (now - stop.timestamp).total_seconds())


def _ready(info: Any) -> bool:
    return info.activity_status in READY_STATUSES and info.activity_hint is None


async def _pass(manager, snapshot, accounts, switch, *, now, monotonic, evidence, read_profile,
                current_switch, rotation, state) -> List[Restart]:
    rows = [row for row in snapshot.accounts if row.provider == PROVIDER]
    socket = manager.tmux_socket_name()
    made: List[Restart] = []
    jobs: List[_Job] = []
    seen: Set[str] = set()
    names = {row.id: row.name for row in rows if row.name}
    infos = await manager.list_session_infos()
    panes = await asyncio.to_thread(manager._build_tmux_status_map)
    if not state.baselined():
        await _take_baseline(infos, evidence, state, now)
    local = {i.tmux_session: i for i in infos if i.tmux_session and i.session is not None and not is_remote_info(i)}
    await asyncio.gather(*(
        _deliver_owed(manager, evidence, rotation, state, record_id, owed, local.get(owed.get("tmux")), names)
        for record_id, owed in state.owed_records().items()
    ))
    for info in infos:
        name = info.tmux_session
        if info.agent_family != PROVIDER or not name or info.session is None:
            continue
        if is_remote_info(info):
            continue
        seen.add(name)

        def skip(gate: str, _name: str = name, **extra: Any) -> None:
            log_skip(_name, gate, monotonic(), **extra)

        stop = await evidence.limit_stop(info, row=panes.get(name)) if info.activity_status != "dead" else None
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
        if state.owed(record_id) is not None:
            skip("continue_owed")
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

        notice = _notifier(state, rotation, record_id, name, account_id, stop.kind, names)

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
        if len(jobs) >= MAX_RESTARTS_PER_PASS:
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
        jobs.append(_Job(info, name, stop, account_id, target_id, in_place, session_uuid, notice, skip, names))
    results = await asyncio.gather(*(
        _rotate_one(manager, socket, evidence, rotation, state, read_profile, accounts, switch, current_switch, now, job)
        for job in jobs
    ))
    made.extend(r for r in results if r is not None)
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
        fresh_stop = await evidence.limit_stop(fresh, force=True) if fresh is not None else None
        quiet = await _quiet_for(evidence, info.tmux_session, stop, now or datetime.now(timezone.utc))
        if fresh is None or not _ready(fresh) or fresh_stop is None or fresh_stop.uuid != stop.uuid \
                or quiet is None or quiet < QUIET_SECONDS:
            return False
    return await _type_continue(rotation, state, info, stop.uuid, session_uuid) is None


async def _type_continue(rotation, state, info, record_id: str, session_uuid: Optional[str]) -> Optional[str]:
    try:
        await rotation.paste_continue(info, session_uuid)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        code = str(detail.get("code", "refused"))
        logger.info("limit_rotation_continue_refused", tmux_session=info.tmux_session, code=code)
        return code
    state.mark_continue_sent(record_id)
    return None


@dataclass
class _Job:

    info: Any
    name: str
    stop: LimitStop
    account_id: str
    target_id: str
    in_place: bool
    session_uuid: str
    notice: Callable[..., None]
    skip: Callable[..., None]
    names: Dict[str, str]


def _notifier(state, rotation, record_id: str, name: str, from_id: str, kind: str, names: Dict[str, str]):
    def notice(outcome: str, to_id: str, moved: bool = False) -> None:
        if state.claim_notice(record_id, outcome):
            rotation.notify(outcome, session=name, from_account_id=from_id, to_account_id=to_id, limit_kind=kind,
                            moved=moved, from_name=names.get(from_id, ""), to_name=names.get(to_id, ""))

    return notice


async def _rotate_one(manager, socket, evidence, rotation, state, read_profile, accounts, switch, current_switch,
                      now: datetime, job: _Job) -> Optional[Restart]:
    info, name, stop, skip, notice = job.info, job.name, job.stop, job.skip, job.notice
    record_id, account_id, target_id = stop.uuid, job.account_id, job.target_id
    if not (await asyncio.to_thread(current_switch)).auto_switch:
        skip("recheck_switch_changed")
        return None
    fresh = await manager.get_session_info(info.session.id)
    fresh_stop = (
        await evidence.limit_stop(fresh, force=True) if fresh is not None and fresh.activity_status != "dead" else None
    )
    if fresh is None or not _restartable(fresh, fresh_stop):
        skip("recheck_not_restartable")
        return None
    if fresh_stop is None or fresh_stop.uuid != record_id:
        skip("recheck_new_last_turn")
        return None
    quiet = await _quiet_for(evidence, name, fresh_stop, now)
    if quiet is None or quiet < QUIET_SECONDS:
        skip("recheck_quiet_window")
        return None
    try:
        if await rotation.pin_for(job.session_uuid):
            skip("recheck_pinned")
            return None
    except limit_rotate.PinUnreadable:
        skip("pin_unreadable")
        return None
    _SKIP_LOGGED.pop(name, None)
    state.record_attempt(record_id)
    moved = False
    if not job.in_place:
        moved = await rotation.move_pointer(accounts, switch, account_id, target_id)
    ok = await _restart(manager, socket, name, accounts, target_id, read_profile, skip)
    logger.info(
        "provider_account_auto_restarted", tmux_session=name, from_account_id=account_id,
        to_account_id=target_id, ok=ok, in_place=job.in_place,
    )
    restart = Restart(name, info.session.id, account_id, target_id, ok)
    if not ok:
        notice(limit_rotate.FAILED, target_id)
        return restart
    landed = await manager.get_session_info(info.session.id)
    if landed is None:
        notice(limit_rotate.FAILED, target_id)
        return restart
    state.owe_continue(record_id, {
        "tmux": name, "epoch": landed.session.tmux_created_epoch, "pid": None, "uuid": job.session_uuid,
        "outcome": limit_rotate.CONTINUED if job.in_place else limit_rotate.ROTATED, "from_id": account_id,
        "to_id": target_id, "kind": stop.kind, "moved": moved,
    })
    if await rotation.wait_ready(info.session.id):
        ready = await manager.get_session_info(info.session.id)
        await _deliver_owed(manager, evidence, rotation, state, record_id, state.owed(record_id), ready, job.names)
    return restart


async def _deliver_owed(manager, evidence, rotation, state, record_id: str, owed: Optional[Dict[str, Any]],
                        info: Optional[Any], names: Dict[str, str]) -> None:
    if owed is None or state.continue_sent(record_id):
        return
    notice = _notifier(state, rotation, record_id, owed["tmux"], owed["from_id"], owed["kind"], names)

    def abandon(reason: str) -> None:
        logger.warning("limit_rotation_continue_abandoned", tmux_session=owed["tmux"], reason=reason)
        state.drop_owed(record_id)
        notice(limit_rotate.FAILED, owed["to_id"])

    if info is None:
        if state.owed_expired(record_id):
            abandon("pane_gone")
        return
    if info.activity_status == "dead":
        abandon("pane_dead")
        return
    if info.session.tmux_created_epoch != owed["epoch"]:
        abandon("different_pane")
        return
    pid = await evidence.body_pid(info)
    if pid is not None and owed["pid"] is not None and pid != owed["pid"]:
        abandon("different_claude")
        return
    if pid is not None and owed["pid"] is None:
        state.bind_owed_pid(record_id, pid)
        owed = state.owed(record_id)
    if pid is None or not await rotation.ready_to_continue(info):
        if state.owed_expired(record_id):
            abandon("not_ready")
        return
    code = await _type_continue(rotation, state, info, record_id, owed["uuid"])
    if code is None:
        notice(owed["outcome"], owed["to_id"], owed["moved"])
    elif code in bring_up.GONE_CODES:
        abandon(code)
    elif code == "paste_not_submitted":
        state.mark_continue_sent(record_id)
        abandon(code)
    elif state.owed_expired(record_id):
        abandon(code)


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
