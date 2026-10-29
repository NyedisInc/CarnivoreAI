from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Coroutine, List, Optional, Sequence, Set, Tuple

import structlog

from src.core import session_change_notice
from src.core.attention.listing_marks import marks_stamp
from src.core.attention.display import activity_hint_for, to_display
from src.core.attention.evidence import FAMILY_CODEX, REASON_QUESTION, STATE_NEEDS_USER, Evidence, EvidenceIdentity
from src.core.attention.ledger import Transition
from src.core.attention.side_effects import AttentionSideEffects
from src.core.attention.toast_detail import detail_for
from src.core.attention.watcher import AttentionWatcher, Observation, WatchTarget
from src.core.auto_sleep.idle_seed import SeedResult, pick_idle_seed
from src.core.auto_sleep.idle_seed_paths import resolve_claude_seed, resolve_codex_seed
from src.core.approvals.inbox import ApprovalsInbox, DialogProvider
from src.core.approvals.startup_prompt_provider import StartupPromptProvider, journal_writer
from src.core.hook_event_presentation import hook_event_presentation, question_toast_title
from src.core.mcp import pending
from src.core.notifications.sources import toast as toast_source
from src.core.notifications.sources.approvals import ApprovalsSource
from src.core.session_status import STATUS_UNKNOWN
from src.core.unread_store import UnreadStore
from src.models import SessionRenamedMessage, ToastNewMessage

logger = structlog.get_logger()

Send = Callable[[str, str], None]


def make_announce_rename(send: Send, app_state: Any) -> Callable[[str, str], None]:
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

    return announce_rename


def make_list_targets(manager: Any, effects: AttentionSideEffects) -> Callable[[], Sequence[WatchTarget]]:
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

    return list_targets


def make_raise_toast(manager: Any, effects: AttentionSideEffects, send: Send, app_state: Any, get_watcher: Callable[[], AttentionWatcher]) -> Callable[[WatchTarget, str, Transition], None]:
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
        observation = get_watcher().observation_for(target.session_id)
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

    return raise_toast


def idle_seed_thunk(manager: Any, target: WatchTarget, observation: Observation) -> Callable[[], SeedResult]:

    def _seed() -> SeedResult:
        evidence = observation.evidence
        identity = EvidenceIdentity.coerce(evidence.identity) or EvidenceIdentity(None, None, None, None, None)
        tmux_name, session_started_epoch, uuid = identity.tmux_name, identity.epoch, identity.conversation_uuid
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


def make_read_policy(manager: Any) -> Callable[[WatchTarget], Tuple[bool, Any]]:
    def read_policy(target: WatchTarget) -> Tuple[bool, Any]:
        return (True, manager.notification_policy_stamp(target.session_id))

    return read_policy


def make_fresh_evidence(list_targets: Callable[[], Sequence[WatchTarget]], read_evidence: Any) -> Callable[[str], Any]:
    async def fresh_evidence(session_id: str) -> Optional[Evidence]:
        target = next((t for t in list_targets() if t.session_id == session_id), None)
        if target is None:
            return None
        return await asyncio.to_thread(read_evidence.read_fresh, target, datetime.now(timezone.utc))

    return fresh_evidence


def build_inbox(manager: Any, app_state: Any, get_watcher: Callable[[], AttentionWatcher]) -> Tuple[ApprovalsInbox, Callable[[], Path]]:
    inbox = ApprovalsInbox(lambda frame: session_change_notice.publish(app_state, frame))
    inbox.register(DialogProvider(get_watcher, lambda: manager))

    def journal_state_dir() -> Path:
        from src.config import settings

        return settings.get_state_dir()

    inbox.register(StartupPromptProvider(get_watcher, lambda: manager,
                                         on_first_seen=journal_writer(journal_state_dir, get_watcher)))
    agent_actions = pending.get_store()
    inbox.register(pending.AgentActionProvider(agent_actions, lambda: manager))
    agent_actions.subscribe(inbox.refresh)
    if app_state is not None:
        app_state.approvals_inbox = inbox
    inbox.on_gain_ids(ApprovalsSource(get_watcher, lambda: manager, pending.get_store).on_gain)
    return inbox, journal_state_dir


@dataclass(frozen=True)
class ObservationHooks:

    inbox: ApprovalsInbox
    history: Any
    died_tracker: Any
    beast_prompts: Any
    auto_answer: Any
    pipeline_feed: Any
    raise_skill_notice: Callable[[WatchTarget, Any], None]


def make_on_observation(
    manager: Any, app_state: Any, effects: AttentionSideEffects, hooks: ObservationHooks, idle_clock: Optional[Any],
) -> Callable[[WatchTarget, Observation], None]:
    inbox, history, died_tracker = hooks.inbox, hooks.history, hooks.died_tracker
    beast_prompts, auto_answer, pipeline_feed = hooks.beast_prompts, hooks.auto_answer, hooks.pipeline_feed
    raise_skill_notice = hooks.raise_skill_notice
    published: dict[str, tuple] = {}
    marks: dict[str, tuple] = {}

    async def mirror_native(session_id: str) -> None:
        from src.core.crosstalk.native_mirror import mirror

        info = await manager.get_session_info(session_id=session_id)
        if info is not None:
            await mirror(SimpleNamespace(state=app_state), info)

    mirror_tasks: Set["asyncio.Task[None]"] = set()

    def mirror_done(task: asyncio.Task) -> None:
        if not task.cancelled() and task.exception() is not None:
            logger.warning('crosstalk_native_mirror_failed', error_type=type(task.exception()).__name__)

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
                seed=idle_seed_thunk(manager, target, observation),
                unread=unread,
            )
        mark_stamp = marks_stamp(observation.evidence)
        if marks.get(target.session_id, mark_stamp) != mark_stamp:
            publisher = getattr(app_state, 'listing_publisher', None)
            if publisher is not None:
                publisher.wake()
        marks[target.session_id] = mark_stamp
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
                spawn_held(mirror_native(target.session_id), mirror_tasks, mirror_done)
            messaging = getattr(app_state, 'messaging', None)
            if messaging is not None:
                messaging.on_status(target.session_id, display)
        for session_id in set(published) - manager._registry.sessions.keys():
            del published[session_id]
            marks.pop(session_id, None)
        auto_answer.forget(manager._registry.sessions.keys())

    return on_observation


def spawn_held(coro: Coroutine[Any, Any, None], held: Set["asyncio.Task[None]"],
               on_done: Callable[["asyncio.Task[None]"], None]) -> "asyncio.Task[None]":
    task = asyncio.create_task(coro)
    held.add(task)
    task.add_done_callback(held.discard)
    task.add_done_callback(on_done)
    return task
