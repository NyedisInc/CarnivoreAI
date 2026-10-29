
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Optional

import structlog

from src.core.attention.evidence import STATE_NEEDS_USER
from src.core.attention.ledger import AttentionLedger
from src.core.attention.restart_floor import RestartFloors
from src.core.attention.screen_read import shared_screens
from src.core.attention.side_effects import AttentionSideEffects
from src.core.attention.watcher import DEFAULT_TICK_SECONDS, AttentionWatcher
from src.core.attention.wiring_builders import (
    ObservationHooks,
    build_inbox,
    make_announce_rename,
    make_fresh_evidence,
    make_list_targets,
    make_on_observation,
    make_raise_toast,
    make_read_policy,
)
from src.core.approvals.auto_answer.engine import AutoAnswerEngine
from src.core.approvals.auto_answer.record import record_and_announce
from src.core.attention_history.wiring import build_recorder
from src.core.attention_reader import AttentionEvidenceReader
from src.core.beast_prompts.wiring import build_engine as build_beast_prompts
from src.core.notifications.sources.died import DiedTracker
from src.core.pipeline.feed import LiveFeed
from src.core.skill_watch.wiring import attach_tripwire, make_notice_raiser
from src.models import ToastAckMessage

logger = structlog.get_logger()


def build_attention_watcher(
    manager: Any,
    *,
    app_state: Any = None,
    broadcast: Optional[Callable[[str, str], Awaitable[Any]]] = None,
    tick_seconds: float = DEFAULT_TICK_SECONDS,
    idle_clock: Optional[Any] = None,
) -> AttentionWatcher:
    send = _sync_sender(broadcast)
    effects = AttentionSideEffects(
        manager,
        broadcast_toast_ack=lambda session_id, toast_id: send(
            session_id, ToastAckMessage(toast_id=toast_id).model_dump_json()
        ),
        broadcast_rename=make_announce_rename(send, app_state),
    )
    restart_floors = RestartFloors()
    ledger = AttentionLedger()
    read_evidence = AttentionEvidenceReader(
        manager, effects.instance_for, publish_status_map=manager.publish_status_map,
        restart_floors=restart_floors,
        watch_codex_rollouts=lambda: True,
        ask_open=lambda key: ledger.confirmed_state(key) == STATE_NEEDS_USER,
        screens=shared_screens(),
    )
    attach_tripwire(read_evidence, app_state)
    list_targets = make_list_targets(manager, effects)
    inbox, journal_state_dir = build_inbox(manager, app_state, lambda: watcher)
    hooks = ObservationHooks(
        inbox=inbox,
        history=build_recorder(journal_state_dir),
        died_tracker=DiedTracker(manager, app_state),
        beast_prompts=build_beast_prompts(lambda: manager, lambda: watcher),
        auto_answer=AutoAnswerEngine(app_state, lambda: manager, on_pressed=record_and_announce(lambda: manager)),
        pipeline_feed=LiveFeed(paths_for=lambda: read_evidence.paths_for, rollout_for=lambda: read_evidence.rollout_for),
        raise_skill_notice=make_notice_raiser(manager, app_state, send),
    )

    policy_store = getattr(manager, "_notification_policy_store", None)

    watcher = AttentionWatcher(
        list_targets=list_targets,
        read_evidence=read_evidence,
        restart_floors=restart_floors,
        raise_toast=make_raise_toast(manager, effects, send, app_state, lambda: watcher),
        set_unread=effects.set_unread,
        on_busy_edge=effects.on_busy_edge,
        on_done_edge=effects.on_done_edge,
        on_transition=hooks.history.on_transition,
        on_observation=make_on_observation(manager, app_state, effects, hooks, idle_clock),
        read_policy=make_read_policy(manager) if policy_store is not None else None,
        ledger=ledger,
        tick_seconds=tick_seconds,
        watch_paths=read_evidence.watch_paths,
    )
    manager._attention_watcher = watcher
    manager._fresh_evidence = make_fresh_evidence(list_targets, read_evidence)
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
