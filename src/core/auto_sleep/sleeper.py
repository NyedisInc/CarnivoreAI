"""The auto-sleep pass: put agent sessions that have idled long enough to sleep.

EVERY CONDITION MUST HOLD, AND EACH ONE ALONE BLOCKS
(``tests/test_auto_sleep_sleeper.py`` breaks them one at a time):

10. MEASURED: nothing of the session's runs under its claude (rule 11 below
   judges it, with the timers and subagents, through :mod:`live_work`). The
   watcher's own observation carries the process-tree answer
   (``evidence.background_process``, ``src.core.background_work.measured``,
   issue #1185): ``running`` (a live Claude Code tool shell, a background
   Bash or a Monitor) keeps it awake, and so does ``unknown``, because an
   unmeasured tree is never idle. A transcript claim with no process behind
   it does not: it is retired upstream (``attention.background_claims``)
   and never reaches this pass. Codex, which is not measured (None), is
   judged by the rules above alone.

12. A SWARM BODY follows its own rule (:mod:`swarm_rule`, docs/swarm.md 4.6): it idles for ``swarm.auto_sleep_idle_minutes``,
   its pane's unread flag is ignored, nothing may be pending, its conversation id is not required, and it sleeps through
   ``swarm.body.sleep`` so its memory commit runs. Every condition above that is not about unread, idle minutes or the
   conversation id still applies to it, and the toggle in rule 1 governs it too.

THE SLEEP IS THE EXISTING ONE. The injected ``sleep`` callable is the action
``POST /sessions/{session_uuid}/sleep`` runs, so measured presence, the
close, and the asleep marker are the same code; there is no second teardown.

BOUNDED: at most :data:`MAX_SLEEPS_PER_PASS` sleeps per pass. A sleep that
landed is published as ``session.auto_slept``, which the browser toasts.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

import structlog

from src.core import session_change_notice
from src.core.account_switch.auto_restart import at_rest
from src.config.auto_sleep import AutoSleepConfig
from src.core.auto_sleep import live_work, swarm_rule, pane_listeners, store
from src.core.auto_sleep.idle_clock import IdleClock
from src.core.swarm import settings as swarm_settings
from src.core.notifications.sources import frames
from src.core.session_status import STATUS_FINISHED_UNREAD
from src.models.websocket import WSMessageType

logger = structlog.get_logger()

PASS_SECONDS = 30.0

AGENT_FAMILIES = frozenset({"claude", "codex"})

MAX_SLEEPS_PER_PASS = 3


def leased_member_rows(db_path: Path) -> Set[int]:
    from src.core.db import connect
    from src.core.layouts.lease import LEASES, SESSION_LEASES
    from src.core.layouts.store import member_row_ids_of

    active, held = LEASES.active(), SESSION_LEASES.active()
    if not (active or held) or not db_path.exists():
        return set()
    with closing(connect(db_path, create=False)) as conn:
        rows = member_row_ids_of(conn, active)
        if held:
            marks = ",".join("?" for _ in held)
            rows |= {int(r[0]) for r in conn.execute(
                f"SELECT id FROM sessions WHERE session_uuid IN ({marks})", tuple(held))}
        return rows


def viewer_count(manager: Any, session_id: str) -> int:
    return len(manager._registry.subscribers.get(session_id) or [])


def _read_row(db_path: Path, row_id: int) -> Optional[Dict[str, Any]]:
    from src.core.db import connect

    if not db_path.exists():
        return None
    with closing(connect(db_path, create=False)) as conn:
        found = conn.execute("SELECT * FROM sessions WHERE id = ?", (int(row_id),)).fetchone()
    return dict(found) if found is not None else None


def _default_config_path() -> Path:
    from src.config import settings

    return Path(settings.auth_config_file).expanduser()


def _default_db_path() -> Path:
    from src.config import settings
    from src.core.db import db_path_for

    return db_path_for(settings.get_state_dir())


class AutoSleeper:

    def __init__(
        self,
        app_state: Any,
        clock: IdleClock,
        *,
        sleep: Callable[[str], Awaitable[Any]],
        config_path: Optional[Callable[[], Path]] = None,
        db_path: Optional[Callable[[], Path]] = None,
        now: Optional[Callable[[], datetime]] = None,
        pass_seconds: float = PASS_SECONDS,
        listeners: Optional[Callable[[], pane_listeners.ListenerSnapshot]] = None,
    ) -> None:
        self._app_state = app_state
        self._clock = clock
        self._sleep = sleep
        self._config_path = config_path or _default_config_path
        self._db_path = db_path or _default_db_path
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.pass_seconds = pass_seconds
        self._take_listeners = listeners or pane_listeners.take_snapshot
        self._running = False
        self._swarm_member: Optional[swarm_rule.Member] = None
        self.holds: Dict[str, Tuple[str, live_work.SleepHold]] = {}

    async def run(self) -> None:
        logger.info("auto_sleep_started", pass_seconds=self.pass_seconds)
        while True:
            try:
                await self.pass_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "auto_sleep_pass_failed", error=str(exc), error_type=type(exc).__name__
                )
            await self._route_questions()
            await self._card_sweep()
            await asyncio.sleep(self.pass_seconds)

    async def _route_questions(self) -> None:
        from src.core.swarm import alerts, closeout, learning, routing, switch

        if not switch.is_on():
            return
        try:
            await routing.sweep(self._app_state)
            await learning.sweep(self._app_state)
            await alerts.sweep(self._app_state)
            await closeout.sweep(self._app_state)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("swarm_question_sweep_failed", error=str(exc), error_type=type(exc).__name__)

    async def _card_sweep(self) -> None:
        from src.core.swarm import switch
        from src.core.swarm.cards import sweep

        if not switch.is_on():
            return
        try:
            await sweep.run(self._app_state)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("swarm_card_sweep_failed", error=str(exc), error_type=type(exc).__name__)

    def _read_config(self) -> Dict[str, Any]:
        data = json.loads(self._config_path().read_text())
        if not isinstance(data, dict):
            raise ValueError("config.json is not an object")
        return data

    async def pass_once(self) -> List[str]:
        if self._running:
            return []
        self._running = True
        try:
            return await self._pass()
        finally:
            self._running = False

    async def _pass(self) -> List[str]:
        manager = getattr(self._app_state, "session_manager", None)
        if manager is None:
            return []
        self._clock.prune(manager._registry.sessions.keys())
        try:
            config = await asyncio.to_thread(self._read_config)
        except (OSError, ValueError) as exc:
            logger.warning("auto_sleep_config_unreadable", error=type(exc).__name__)
            return []
        settings = store.read_block(config)
        if not settings.enabled:
            return []
        now = self._now()
        try:
            members = await asyncio.to_thread(swarm_rule.read_members, self._db_path())
        except Exception as exc:  # noqa: BLE001
            logger.warning("auto_sleep_swarm_members_unreadable", error_type=type(exc).__name__)
            return []
        swarm_cfg = swarm_settings.read_block(config)
        swarm_names = {m.tmux_name for m in members.by_row.values()}
        due = [
            sid for sid in self._clock.idle_ids()
            if self._idle_long_enough(sid, now, settings, self._clock.is_unread(sid))
            or (swarm_names and self._swarm_due(manager, sid, now, swarm_cfg, swarm_names))
        ]
        if not due:
            return []
        keep_awake = set(settings.keep_awake)
        try:
            leased = await asyncio.to_thread(leased_member_rows, self._db_path())
        except Exception as exc:  # noqa: BLE001
            logger.warning("auto_sleep_layout_leases_unreadable", error_type=type(exc).__name__)
            return []
        slept: List[str] = []
        self.holds = {}
        snapshot = pane_listeners.PassSnapshot(self._take_listeners)
        for session_id in due:
            if len(slept) >= MAX_SLEEPS_PER_PASS:
                break
            uuid = await self._eligible(
                manager, session_id, keep_awake, leased, snapshot, settings=settings, members=members,
                swarm_cfg=swarm_cfg
            )
            if uuid is None:
                continue
            member = self._swarm_member
            outcome = await self._act(session_id, uuid, settings.idle_minutes, member)
            if outcome:
                slept.append(uuid)
        return slept

    def _swarm_due(self, manager: Any, session_id: str, now: datetime, swarm_cfg: Any, swarm_names: Set[str]) -> bool:
        tmux = getattr(manager._registry.sessions.get(session_id), "tmux_session", None)
        seconds = self._clock.sleep_seconds(session_id, now, unread=False)
        return tmux in swarm_names and seconds is not None and seconds >= swarm_cfg.auto_sleep_idle_minutes * 60

    def _idle_long_enough(
        self, session_id: str, now: datetime, settings: AutoSleepConfig, unread: bool
    ) -> bool:
        if unread and settings.unread_blocks_sleep:
            return False
        minutes = settings.unread_idle_minutes if unread else settings.idle_minutes
        seconds = self._clock.sleep_seconds(session_id, now, unread=unread)
        return seconds is not None and seconds >= minutes * 60

    async def _eligible(
        self, manager: Any, session_id: str, keep_awake: Set[str],
        leased: Optional[Set[int]], snapshot: pane_listeners.PassSnapshot,
        *, settings: AutoSleepConfig, members: Optional[swarm_rule.Members] = None, swarm_cfg: Any = None,
    ) -> Optional[str]:
        from src.core import session_sleep

        self._swarm_member = None
        info = await manager.get_session_info(session_id)
        if info is None or info.session is None or not info.tmux_session:
            return None
        swarm = members.by_row.get(info.session_row_id) if members is not None else None
        if info.agent_family not in AGENT_FAMILIES:
            return None
        watcher = getattr(manager, "_attention_watcher", None)
        observation = watcher.observation_for(session_id, now=self._now()) if watcher else None
        if observation is None or observation.stale:
            return None
        unread = bool(info.unread)
        if info.activity_hint is not None:
            return None
        if swarm is not None:
            if info.activity_status not in ("idle", STATUS_FINISHED_UNREAD):
                return None
            idle_for = self._clock.sleep_seconds(session_id, self._now(), unread=False)
            if swarm_cfg is None or idle_for is None or idle_for < swarm_cfg.auto_sleep_idle_minutes * 60:
                return None
        elif unread:
            if settings.unread_blocks_sleep or info.activity_status != STATUS_FINISHED_UNREAD:
                return None
        elif not at_rest(info):
            return None
        if swarm is None and not self._idle_long_enough(session_id, self._now(), settings, unread):
            return None
        if viewer_count(manager, session_id):
            return None
        if info.session_row_id is None:
            return None
        if leased and info.session_row_id in leased:
            return None
        try:
            row = await asyncio.to_thread(_read_row, self._db_path(), info.session_row_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("auto_sleep_row_unreadable", session_id=session_id,
                           error_type=type(exc).__name__)
            return None
        if row is None or not row.get("session_uuid"):
            return None
        if row.get("tmux_name") != info.tmux_session:
            return None
        uuid = str(row["session_uuid"])
        if uuid in keep_awake:
            return None
        if swarm is None and session_sleep.sleep_refusal(row) is not None:
            return None
        if swarm is not None:
            why = swarm_rule.pending_reason(swarm, members)
            if why is not None:
                logger.info("auto_sleep_swarm_pending", session_id=session_id, agent_id=swarm.agent_id, why=why)
                return None
        if self._hold(session_id, info, getattr(observation, "evidence", None), require_measured=False):
            return None
        if await self._serves(manager, session_id, snapshot):
            return None
        if await self._fresh_hold(manager, session_id, info):
            return None
        self._swarm_member = swarm
        return uuid

    def _hold(self, session_id: str, info: Any, evidence: Any, *, require_measured: bool) -> bool:
        hold = live_work.hold_for(evidence, require_measured=require_measured)
        if hold is None:
            return False
        self.holds[session_id] = (info.tmux_session, hold)
        logger.info("auto_sleep_kept_awake_live_work", session_id=session_id,
                    reasons=list(hold.reasons), timers_live=hold.timers_live,
                    subagents_running=hold.subagents_running,
                    background_count=hold.background_count, fresh=require_measured)
        return True

    async def _fresh_hold(self, manager: Any, session_id: str, info: Any) -> bool:
        read = getattr(manager, "_fresh_evidence", None)
        if read is None:
            reason, evidence = "no fresh reader wired", None
        else:
            try:
                evidence, reason = await read(session_id), "session not readable"
            except Exception as exc:  # noqa: BLE001
                evidence, reason = None, type(exc).__name__
        if evidence is None:
            logger.warning("auto_sleep_fresh_check_unreadable", session_id=session_id, reason=reason)
            self.holds[session_id] = (info.tmux_session, live_work.SleepHold(
                reasons=(live_work.REASON_UNMEASURED,),
                text="kept awake: could not re-check its timers and background work"))
            return True
        return self._hold(session_id, info, evidence, require_measured=True)

    async def _serves(
        self, manager: Any, session_id: str, snapshot: pane_listeners.PassSnapshot,
    ) -> bool:
        """True unless it is MEASURED that no process in the pane's tree listens on TCP.

        Inputs: manager - carries the registry. session_id (str).
          snapshot - this pass's shared listener snapshot.
        Output: bool - True keeps the session awake: a listener was found,
          or the answer could not be measured (logged).
        """
        backend = manager._registry.backends.get(session_id)
        pane_pid = None
        if backend is not None:
            pane_pid = await asyncio.to_thread(lambda: getattr(backend, "pid", None))
        if pane_pid is None:
            logger.warning("auto_sleep_listeners_unmeasurable", session_id=session_id,
                           reason="pane pid unknown")
            return True
        try:
            found = (await snapshot.get()).pane_listeners(int(pane_pid))
        except pane_listeners.MeasureError as exc:
            logger.warning("auto_sleep_listeners_unmeasurable", session_id=session_id,
                           reason=str(exc))
            return True
        if found:
            logger.debug("auto_sleep_kept_awake_listener", session_id=session_id,
                         pids=found[:5])
            return True
        return False

    async def _act(self, session_id: str, session_uuid: str, idle_minutes: int,
                   swarm_member: Optional[swarm_rule.Member] = None) -> bool:
        manager = self._app_state.session_manager
        info = await manager.get_session_info(session_id)
        name = (info.label or info.tmux_session) if info is not None else None
        try:
            result = (await swarm_rule.sleep_agent(self._app_state, swarm_member.agent_id) if swarm_member is not None
                      else await self._sleep(session_uuid))
        except Exception as exc:  # noqa: BLE001
            logger.warning("auto_sleep_failed", session_uuid=session_uuid,
                           error_type=type(exc).__name__, error=str(getattr(exc, "detail", exc)))
            return False
        status = getattr(result, "status", None)
        logger.info("auto_sleep_attempted", session_uuid=session_uuid, session_id=session_id,
                    status=status, code=getattr(result, "code", None), idle_minutes=idle_minutes)
        if status != "asleep":
            return False
        self._clock.forget(session_id)
        if swarm_member is not None and swarm_member.is_leader:
            return True
        session_change_notice.publish(self._app_state, {
            "type": WSMessageType.SESSION_AUTO_SLEPT,
            "session_id": session_id,
            "session_uuid": session_uuid,
            "session_name": name or getattr(result, "session_name", None),
            "idle_minutes": idle_minutes,
        })
        frames.auto_slept(session_id, session_uuid, name or getattr(result, "session_name", None), info)
        return True
