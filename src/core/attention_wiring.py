
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, List, Optional, Sequence, Tuple

import structlog

from src.core import session_change_notice
from src.core.mcp import pending
from src.core.attention_history.wiring import build_recorder
from src.core.attention.display import activity_hint_for, to_display
from src.core.attention.evidence import FAMILY_CODEX, REASON_QUESTION, STATE_NEEDS_USER, Evidence
from src.core.attention.ledger import AttentionLedger, Transition
from src.core.attention.restart_floor import RestartFloors
from src.core.attention.side_effects import AttentionSideEffects
from src.core.attention.toast_detail import detail_for
from src.core.notifications.sources import toast as toast_source
from src.core.notifications.sources.approvals import ApprovalsSource
from src.core.notifications.sources.died import DiedTracker
from src.core.attention.watcher import (
    DEFAULT_TICK_SECONDS,
    AttentionWatcher,
    Observation,
    WatchTarget,
)
from src.core.auto_sleep.idle_seed import SeedResult, pick_idle_seed
from src.core.auto_sleep.idle_seed_paths import resolve_claude_seed, resolve_codex_seed
from src.core.hook_event_presentation import hook_event_presentation, question_toast_title
from src.core.approvals.auto_answer.engine import AutoAnswerEngine
from src.core.approvals.auto_answer.record import record_and_announce
from src.core.approvals.inbox import ApprovalsInbox, DialogProvider
from src.core.approvals.startup_prompt_provider import StartupPromptProvider, journal_writer
from src.core.beast_prompts.wiring import build_engine as build_beast_prompts
from src.core.pipeline.feed import LiveFeed
from src.core.session_status import STATUS_UNKNOWN
from src.core.skill_watch.wiring import attach_tripwire, make_notice_raiser
from src.core.unread_store import UnreadStore
from src.models import SessionRenamedMessage, ToastAckMessage, ToastNewMessage

logger = structlog.get_logger()


from src.core.attention_reader import AttentionEvidenceReader


def build_attention_watcher(
    manager: Any,
    *,
    app_state: Any = None,
    broadcast: Optional[Callable[[str, str], Awaitable[Any]]] = None,
    tick_seconds: float = DEFAULT_TICK_SECONDS,
    idle_clock: Optional[Any] = None,
) -> AttentionWatcher:
    send = _sync_sender(broadcast)

    def announce_rename(session_id: str, new_name: str) -> None:
        send(
            session_id,
            SessionRenamedMessage(
                session_id=session_id, new_name=new_name
            ).model_dump_json(),
        )
        session_change_notice.publish(
            app_state,
            session_change_notice.build_rename_notice(
                session_id=session_id, new_name=new_name
            ),
        )

    effects = AttentionSideEffects(
        manager,
        broadcast_toast_ack=lambda session_id, toast_id: send(
            session_id, ToastAckMessage(toast_id=toast_id).model_dump_json()
        ),
        broadcast_rename=announce_rename,
    )
    restart_floors = RestartFloors()
    ledger = AttentionLedger()
    read_evidence = AttentionEvidenceReader(
        manager, effects.instance_for, publish_status_map=manager.publish_status_map,
        restart_floors=restart_floors,
        watch_codex_rollouts=lambda: True,
        ask_open=lambda key: ledger.confirmed_state(key) == STATE_NEEDS_USER,
    )
    attach_tripwire(read_evidence, app_state)
    raise_skill_notice = make_notice_raiser(manager, app_state, send)

    def list_targets() -> Sequence[WatchTarget]:
        targets: List[WatchTarget] = []
        for session_id in manager._registry.listable_ids():
            backend = manager._registry.backends.get(session_id)
            if getattr(backend, "_attention_restarting", False):
                continue
            tmux_name, epoch = effects.instance_for(session_id)
            if not tmux_name:
                continue
            targets.append(
                WatchTarget(
                    session_id=session_id,
                    key=UnreadStore.compose_key(tmux_name, epoch),
                    generation=(id(backend), getattr(backend, "_attention_generation", 0)),
                )
            )
        return targets

    def raise_toast(
        target: WatchTarget, kind: str, transition: Transition
    ) -> None:
        asking = transition.state == STATE_NEEDS_USER
        if asking:
            effects.withdraw_answered_ask(target, transition)
        title, body = hook_event_presentation(kind, {})
        if kind == "PermissionRequest" and transition.reason == REASON_QUESTION:
            title = question_toast_title(transition.verdict.activity_hint)
        toast = manager.record_toast(
            session_id=target.session_id,
            kind=kind,
            title=title,
            body=body or None,
            notify_type=toast_source.attention_notify_type(kind, transition.reason),
        )
        observation = watcher.observation_for(target.session_id)
        transcript = getattr(getattr(observation, "evidence", None), "transcript", None)
        toast = manager._toast_inbox.describe(
            toast.session_id,
            toast.id,
            detail_for(transition.reason, getattr(transcript, "toast_facts", None)),
        ) or toast
        if asking:
            effects.hold_ask(target, transition, toast)
        payload = ToastNewMessage(toast=toast).model_dump_json()
        send(target.session_id, payload)
        session_change_notice.publish(app_state, json.loads(payload))

    def _idle_seed_thunk(target: WatchTarget, observation: Observation) -> Callable[[], SeedResult]:

        def _seed() -> SeedResult:
            evidence = observation.evidence
            identity = evidence.identity or (None, None, None, None, None)
            _socket, tmux_name, session_started_epoch, _pid, uuid = identity
            if evidence.agent_family == FAMILY_CODEX:
                candidates, floor = resolve_codex_seed(
                    codex=evidence.codex,
                    codex_session_uuid=uuid,
                    session_started_epoch=session_started_epoch,
                )
            else:
                session = manager._registry.sessions.get(target.session_id)
                cwd = getattr(session, "working_dir", None)
                from src.config import settings

                candidates, floor = resolve_claude_seed(
                    registry=evidence.registry,
                    cwd=cwd,
                    claude_session_uuid=uuid,
                    tmux_name=tmux_name,
                    session_started_epoch=session_started_epoch,
                    config_path=Path(settings.auth_config_file).expanduser(),
                )
            return pick_idle_seed(
                now=observation.observed_at, process_started_at=floor, candidates=candidates
            )

        return _seed

    published: dict[str, tuple] = {}

    async def mirror_native(session_id: str) -> None:
        from src.core.crosstalk.native_mirror import mirror

        info = await manager.get_session_info(session_id=session_id)
        if info is not None:
            await mirror(SimpleNamespace(state=app_state), info)

    def mirror_done(task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception() is not None:
            logger.warning('crosstalk_native_mirror_failed', error_type=type(task.exception()).__name__)
    inbox = ApprovalsInbox(lambda frame: session_change_notice.publish(app_state, frame))
    inbox.register(DialogProvider(lambda: watcher, lambda: manager))
    def journal_state_dir() -> Path:
        from src.config import settings

        return settings.get_state_dir()

    inbox.register(StartupPromptProvider(lambda: watcher, lambda: manager,
                                         on_first_seen=journal_writer(journal_state_dir, lambda: watcher)))
    agent_actions = pending.get_store()
    inbox.register(pending.AgentActionProvider(agent_actions, lambda: manager))
    agent_actions.subscribe(inbox.refresh)
    if app_state is not None:
        app_state.approvals_inbox = inbox
    inbox.on_gain_ids(ApprovalsSource(lambda: watcher, lambda: manager, pending.get_store).on_gain)

    died_tracker = DiedTracker(manager, app_state)
    beast_prompts = build_beast_prompts(lambda: manager, lambda: watcher)
    auto_answer = AutoAnswerEngine(app_state, lambda: manager, on_pressed=record_and_announce(lambda: manager))

    pipeline_feed = LiveFeed(paths_for=lambda: read_evidence.paths_for, rollout_for=lambda: read_evidence.rollout_for)

    history = build_recorder(journal_state_dir)

    def on_observation(target: WatchTarget, observation: Observation) -> None:
        inbox.refresh()
        history.on_observation(target, observation)
        died_tracker.observe(target, observation)
        beast_prompts.on_observation(target, observation)
        auto_answer.on_observation(target, observation)
        effects.on_observation(target, observation)
        findings = getattr(getattr(observation.evidence, "skills", None), "tripwire", ())
        if findings:
            raise_skill_notice(target, findings)
        verdict = observation.verdict
        decision = getattr(observation.evidence, "screen_decision", None)
        logger.debug("attention_status_decided", session_id=target.session_id, state=verdict.state,
                     reason=verdict.reason, tier=verdict.tier, stale=observation.stale,
                     screen_read=getattr(decision, "read", None), screen_reason=getattr(decision, "reason", None))
        name, epoch = effects.instance_for(target.session_id)
        read_unread = getattr(manager, "_is_unread", None)
        unread = bool(read_unread(name, epoch)) if callable(read_unread) and name else False
        display = to_display(verdict, unread=unread, tmux_status=STATUS_UNKNOWN)
        pipeline_feed.on_observation(target.session_id, observation, display)
        if idle_clock is not None:
            idle_clock.observe(
                target.session_id, target.key,
                to_display(verdict, unread=False, tmux_status=STATUS_UNKNOWN),
                verdict.activity_hint or activity_hint_for(observation.evidence.registry),
                observation.observed_at,
                seed=_idle_seed_thunk(target, observation),
                unread=unread,
            )
        stamp = (display, verdict.reason, verdict.tier, verdict.activity_hint, unread)
        if published.get(target.session_id) != stamp:
            session_change_notice.publish_attention_status(
                app_state, manager, target.session_id,
                activity_status=display,
            )
            published[target.session_id] = stamp
            git_watch = getattr(app_state, 'git_status_watch', None)
            if git_watch is not None:
                git_watch.on_status(target.session_id, display)
            dispatcher = getattr(app_state, 'crosstalk_dispatcher', None)
            if dispatcher is not None:
                dispatcher.on_status(target.session_id, display)
                task = asyncio.create_task(mirror_native(target.session_id))
                task.add_done_callback(mirror_done)
            messaging = getattr(app_state, 'messaging', None)
            if messaging is not None:
                messaging.on_status(target.session_id, display)
        for session_id in set(published) - manager._registry.sessions.keys():
            del published[session_id]
        auto_answer.forget(manager._registry.sessions.keys())

    policy_store = getattr(manager, "_notification_policy_store", None)

    def read_policy(target: WatchTarget) -> Tuple[bool, Any]:
        return (True, manager.notification_policy_stamp(target.session_id))

    watcher = AttentionWatcher(
        list_targets=list_targets,
        read_evidence=read_evidence,
        restart_floors=restart_floors,
        raise_toast=raise_toast,
        set_unread=effects.set_unread,
        on_busy_edge=effects.on_busy_edge,
        on_done_edge=effects.on_done_edge,
        on_transition=history.on_transition,
        on_observation=on_observation,
        read_policy=read_policy if policy_store is not None else None,
        ledger=ledger,
        tick_seconds=tick_seconds,
        watch_paths=read_evidence.watch_paths,
    )
    manager._attention_watcher = watcher

    async def fresh_evidence(session_id: str) -> Optional[Evidence]:
        target = next((t for t in list_targets() if t.session_id == session_id), None)
        if target is None:
            return None
        return await asyncio.to_thread(read_evidence.read_fresh, target, datetime.now(timezone.utc))

    manager._fresh_evidence = fresh_evidence
    return watcher


def _sync_sender(
    broadcast: Optional[Callable[[str, str], Awaitable[Any]]],
) -> Callable[[str, str], None]:
    pending: set = set()

    def settle(task: "asyncio.Task") -> None:
        pending.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.warning(
                "attention_broadcast_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )

    def send(session_id: str, payload: str) -> None:
        if broadcast is None:
            return
        try:
            task = asyncio.ensure_future(broadcast(session_id, payload))
        except RuntimeError as exc:
            logger.debug(
                "attention_broadcast_unscheduled",
                session_id=session_id,
                error=str(exc),
            )
            return
        pending.add(task)
        task.add_done_callback(settle)

    return send
