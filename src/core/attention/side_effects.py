
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional, Tuple

import structlog

from src.core import (
    claude_title_sync_apply,
    session_agent_infer_apply,
    session_conversation_rebind,
)
from src.core.attention.ask_toasts import AskToasts, HeldAsk
from src.core.attention.display import to_display
from src.core.attention.evidence import FAMILY_CODEX, STATE_NEEDS_USER
from src.core.attention.codex_identity import codex_bind_conversation
from src.core.attention.codex_reader import CODEX_RECORD_ABSENT
from src.core.attention.ledger import Transition
from src.core.attention.subagent_work import SubagentWorkStamp
from src.core.attention.registry_read import STALE_CAUSE_CONVERSATION
from src.core.attention.watcher import Observation, WatchTarget
from src.core.db_models import SESSION_CLAUDE_UUID_SOURCE_REGISTRY
from src.core.hosts.identity import instance_name, is_remote_backend
from src.core.swarm import guard as swarm_guard
from src.core.swarm import watch as swarm_watch
from src.core.session_activity import EVENT_PRE_TOOL_USE, EVENT_USER_PROMPT_SUBMIT, EVENT_STOP
from src.core.session_lineage_divergence import SESSION_START_SOURCE_REGISTRY
from src.core.session_status import STATUS_UNKNOWN
from src.core.toast_auto_ack import ACK_REASON_ANSWERED
from src.cplugs.sdk import transcript_events, turn_events

logger = structlog.get_logger()

LIFECYCLE_SESSION_START: str = "SessionStart"


def _naive_utc(at: Optional[datetime]) -> Optional[datetime]:
    if at is None:
        return None
    if at.tzinfo is None:
        return at
    return at.astimezone(timezone.utc).replace(tzinfo=None)


class AttentionSideEffects:

    def __init__(
        self,
        manager: Any,
        *,
        broadcast_toast_ack: Optional[Callable[[str, str], None]] = None,
        broadcast_rename: Optional[Callable[[str, str], None]] = None,
        ask_toasts: Optional[AskToasts] = None,
    ) -> None:
        self._manager = manager
        self._broadcast_toast_ack = broadcast_toast_ack
        self._broadcast_rename = broadcast_rename
        self._bound_conversations: dict = {}
        self._subagent_work = SubagentWorkStamp(manager)
        self._asks = ask_toasts if ask_toasts is not None else AskToasts()


    def instance_for(
        self, session_id: str
    ) -> Tuple[Optional[str], Optional[int]]:
        backend = self._manager._registry.backends.get(session_id)
        tmux_name = instance_name(backend)
        if not tmux_name:
            tmux_name = self._manager.hook_tokens.name_for(session_id)
        epoch = self._manager._instance_epochs.get(session_id)
        return (tmux_name or None), epoch

    def _remote(self, session_id: str) -> bool:
        return is_remote_backend(self._manager._registry.backends.get(session_id))


    def set_unread(self, target: WatchTarget) -> None:
        tmux_name, _epoch = self.instance_for(target.session_id)
        if not tmux_name:
            return
        self._manager._unread_store.set_flag(
            tmux_name,
            "auto",
            True,
            epoch=self._manager._unread_epoch(tmux_name),
        )

    def on_busy_edge(self, target: WatchTarget, transition: Transition) -> None:
        session_id = target.session_id
        self.withdraw_answered_ask(target, transition)
        swarm_guard.on_session_busy(target.key, transition.at)
        tmux_name, _epoch = self.instance_for(session_id)
        if self._remote(session_id):
            tmux_name = None
        self._guard(
            "attention_work_stamp_failed",
            session_id,
            self._stamp_work,
            session_id,
            tmux_name,
        )
        self._guard(
            "attention_auto_ack_failed",
            session_id,
            self._auto_ack,
            session_id,
            EVENT_PRE_TOOL_USE,
            transition.at,
        )


    def on_done_edge(self, target: WatchTarget, transition: Transition) -> None:
        self.withdraw_answered_ask(target, transition)
        self._guard(
            "attention_auto_ack_failed", target.session_id,
            self._auto_ack, target.session_id, EVENT_STOP, transition.at,
        )
        turn_events.publish_turn_end(target.session_id)
        swarm_guard.on_session_idle(target.key, transition.at)

    def on_observation(
        self, target: WatchTarget, observation: Observation
    ) -> None:
        session_id = target.session_id
        if self._remote(session_id):
            from src.core.hosts.remote_resume import bind_conversation

            self._guard("attention_conversation_bind_failed", session_id,
                        bind_conversation, self._manager, session_id, observation.evidence)
            return
        self._guard("swarm_watch_failed", session_id, swarm_watch.on_observation, target, observation)
        tmux_name, epoch = self.instance_for(session_id)
        if observation.transcript_appended and transcript_events.listening():
            transcript_events.publish_append(session_id, tmux_name)
        registry = observation.evidence.registry
        codex = observation.evidence.agent_family == FAMILY_CODEX
        registry_present = registry.known
        registry_started = registry.instance_present

        if codex:
            self._guard(
                "attention_conversation_bind_failed", session_id,
                self._bind_codex, session_id, tmux_name,
                observation.evidence.codex_bind_uuid, epoch,
            )
            facts = observation.evidence.codex
            registry_started = bool(facts and (
                facts.record.verdict != CODEX_RECORD_ABSENT or facts.transcript.readable
            ))
        else:
            self._guard(
                "attention_conversation_bind_failed",
                session_id,
                self._bind_conversation,
                session_id,
                tmux_name,
                registry,
                epoch,
            )
        self._guard(
            "attention_startup_gate_failed",
            session_id,
            self._record_started,
            tmux_name,
            epoch,
            registry_started,
        )
        self._guard(
            "attention_agent_inference_failed",
            session_id,
            self._infer_agent,
            session_id,
            tmux_name,
            registry_present or observation.transcript_appended,
        )
        self._guard(
            "attention_activity_state_failed",
            session_id,
            self._persist_state,
            observation,
            tmux_name,
            epoch,
        )
        if observation.new_user_prompt_at is not None:
            self._guard(
                "attention_work_stamp_failed",
                session_id,
                self._stamp_work,
                session_id,
                tmux_name,
            )
            if observation.verdict.state != STATE_NEEDS_USER:
                self._guard(
                    "attention_auto_ack_failed",
                    session_id,
                    self._auto_ack,
                    session_id,
                    EVENT_USER_PROMPT_SUBMIT,
                    observation.new_user_prompt_at,
                )
        if observation.transcript_appended and not codex:
            self._guard(
                "attention_title_sync_failed", session_id, self._sync_title, session_id
            )
        if not codex:
            self._guard(
                "attention_subagent_work_stamp_failed", session_id,
                self._subagent_work.observe, session_id, tmux_name,
                observation.evidence.subagents,
            )


    def _bind_codex(
        self, session_id: str, tmux_name: Optional[str], uuid: Optional[str],
        epoch: Optional[int],
    ) -> None:
        codex_bind_conversation(
            self._manager, session_id=session_id, tmux_name=tmux_name,
            thread_uuid=uuid, epoch=epoch, pane_owned=True,
        )

    def _bind_conversation(
        self,
        session_id: str,
        tmux_name: Optional[str],
        record: Any,
        epoch: Optional[int] = None,
    ) -> None:
        from src.core.session_lineage import LINEAGE_UNRESOLVED

        if not tmux_name:
            return
        if not record.known or record.stale_cause == STALE_CAUSE_CONVERSATION:
            if record.stale_cause == STALE_CAUSE_CONVERSATION:
                session_conversation_rebind.rebind_conversation_uuid(
                    self._manager,
                    session_id=session_id,
                    tmux_name=tmux_name,
                    epoch=epoch,
                    registry_uuid=record.record_session_uuid,
                )
            return
        claude_uuid = record.session_uuid
        if not claude_uuid:
            return
        if self._bound_conversations.get(session_id) == claude_uuid:
            return
        result = self._manager.record_claude_lifecycle_event(
            session_id,
            LIFECYCLE_SESSION_START,
            {
                "session_id": claude_uuid,
                "source": SESSION_START_SOURCE_REGISTRY,
            },
            uuid_source=SESSION_CLAUDE_UUID_SOURCE_REGISTRY,
            tmux_name=tmux_name,
        )
        if result.outcome == LINEAGE_UNRESOLVED:
            logger.debug(
                "attention_conversation_bind_unresolved",
                session_id=session_id,
                claude_uuid=claude_uuid,
                detail=result.detail,
            )
            return
        self._bound_conversations[session_id] = claude_uuid

    def _record_started(
        self, tmux_name: Optional[str], epoch: Optional[int], present: bool
    ) -> None:
        if not present or not tmux_name:
            return
        self._manager._startup_gate_ledger.record_hook(tmux_name, epoch=epoch)

    def _infer_agent(
        self, session_id: str, tmux_name: Optional[str], triggered: bool
    ) -> None:
        if not triggered or not tmux_name:
            return
        session_agent_infer_apply.apply_agent_inference(
            self._manager, session_id, tmux_name
        )

    def _persist_state(
        self,
        observation: Observation,
        tmux_name: Optional[str],
        epoch: Optional[int],
    ) -> None:
        if not tmux_name:
            return
        state = to_display(
            observation.verdict, unread=False, tmux_status=STATUS_UNKNOWN
        )
        self._manager._persist_settled_activity_state(tmux_name, state, epoch)

    def _stamp_work(self, session_id: str, tmux_name: Optional[str]) -> None:
        if not tmux_name:
            return
        self._manager._persist_work_stamp(session_id, tmux_name, None)

    def _auto_ack(
        self, session_id: str, event_kind: str, cutoff: Optional[datetime]
    ) -> None:
        acked = self._manager.auto_ack_toasts(
            session_id, event_kind, _naive_utc(cutoff)
        )
        send = self._broadcast_toast_ack
        if send is None:
            return
        for toast_id in acked or ():
            send(session_id, toast_id)

    def hold_ask(self, target: WatchTarget, transition: Transition, toast: Any) -> None:
        self._guard("attention_ask_hold_failed", target.session_id, self._asks.hold,
                    target.key, toast.session_id, toast.id, transition.reason)

    def withdraw_answered_ask(self, target: WatchTarget, transition: Transition) -> None:
        held = self._asks.take_answered(target.key, transition.state, transition.reason)
        if held is None:
            return
        self._guard("attention_ask_withdraw_failed", held.session_id, self._withdraw, held,
                    transition)

    def _withdraw(self, held: HeldAsk, transition: Transition) -> None:
        if not self._manager._toast_inbox.ack(held.session_id, held.toast_id, ACK_REASON_ANSWERED):
            return
        logger.info("attention_ask_toast_withdrawn", session_id=held.session_id,
                    toast_id=held.toast_id, ask_reason=held.reason, state=transition.state,
                    reason=transition.reason)
        if self._broadcast_toast_ack is not None:
            self._broadcast_toast_ack(held.session_id, held.toast_id)

    def _sync_title(self, session_id: str) -> None:
        result = claude_title_sync_apply.sync_claude_title(
            self._manager, session_id
        )
        title = result.broadcast_title
        send = self._broadcast_rename
        if title and send is not None:
            send(session_id, title)


    def _guard(
        self, event: str, session_id: str, job: Callable, *args: Any
    ) -> None:
        try:
            job(*args)
        except Exception as exc:
            logger.warning(
                event,
                session_id=session_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
