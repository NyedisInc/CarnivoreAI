
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Protocol, Tuple

import structlog

from src.core import resource_push
from src.core.approvals.ask_questions import served_fields
from src.core.approvals.bounds import valid_items
from src.core.approvals.extract import unreadable_dialog
from src.core.approvals.plain_answer import plain_no_label, plain_yes_label, summary_line
from src.core.attention.evidence import REASON_INPUT, STATE_NEEDS_USER
from src.core.attention.startup_screen import shown_screen
from src.core.resource_push import topics as resource_topics

logger = structlog.get_logger()

Signature = FrozenSet[Tuple[str, str, str]]
DEBOUNCE_SECONDS: float = 0.3


class Provider(Protocol):

    def signature(self) -> Signature:
        pass

    async def items(self) -> List[Dict[str, Any]]:
        pass


class DialogProvider:

    def __init__(self, get_watcher: Callable[[], Any], get_manager: Callable[[], Any]) -> None:
        self._watcher = get_watcher
        self._manager = get_manager
        self._first_seen: Dict[Tuple[str, str], str] = {}

    def _open(self) -> List[Tuple[str, Any]]:
        watcher = self._watcher()
        if watcher is None:
            return []
        found = []
        for session_id in watcher.observed_session_ids():
            observation = watcher.observation_for(session_id)
            if observation is None or str(session_id).startswith("remote:"):
                continue
            dialog = observation.evidence.dialog
            if (dialog is None and observation.verdict.state == STATE_NEEDS_USER
                    and observation.verdict.reason != REASON_INPUT and shown_screen(observation) is None):
                dialog = unreadable_dialog(observation.evidence.agent_family)
            if dialog is not None:
                found.append((session_id, dialog))
        return found

    def signature(self) -> Signature:
        current = self._open()
        keys = {(sid, d.fingerprint) for sid, d in current}
        now = datetime.now(timezone.utc).isoformat()
        for key in keys:
            self._first_seen.setdefault(key, now)
        for key in set(self._first_seen) - keys:
            del self._first_seen[key]
        return frozenset(("dialog", item_id(sid, d.fingerprint), d.fingerprint) for sid, d in current)

    async def items(self) -> List[Dict[str, Any]]:
        manager = self._manager()
        out: List[Dict[str, Any]] = []
        if manager is None:
            return out
        self.signature()
        for session_id, dialog in self._open():
            info = await manager.get_session_info(session_id)
            if info is None or str(info.session.id).startswith("remote:"):
                continue
            item = {
                "id": item_id(session_id, dialog.fingerprint), "source": "dialog", "host": "local",
                "session_id": info.session.id, "session_name": info.label or info.tmux_session,
                "tmux_session": info.tmux_session, "project": info.project_name,
                "family": dialog.family, "kind": dialog.kind, "question": dialog.question,
                "body": dialog.body, "options": list(dialog.options),
                "rows": [{"label": r.label, "role": r.role, "checked": r.checked, "description": r.description}
                         for r in dialog.rows],
                "question_index": dialog.question_index, "question_total": len(dialog.tabs) or None,
                "tabs": [{"title": t.title, "answered": t.answered} for t in dialog.tabs],
                "multi_select": dialog.multi_select, "has_other": dialog.has_other,
                "fingerprint": dialog.fingerprint, "startup_kind": dialog.startup_kind,
                "plain_yes": plain_yes_label(dialog), "plain_no": plain_no_label(dialog),
                "summary": summary_line(dialog) if plain_yes_label(dialog) else None,
                "created_at": self._first_seen.get((session_id, dialog.fingerprint)),
            }
            out.append({**item, **await served_fields(info, self._watcher(), dialog)})
        return out


def item_id(session_id: str, fingerprint: str) -> str:
    return f"dlg:{session_id}:{fingerprint[:16]}"


class ApprovalsInbox:

    def __init__(self, publish: Callable[[Dict[str, Any]], Any],
                 debounce: float = DEBOUNCE_SECONDS) -> None:
        self._publish = publish
        self._debounce = debounce
        self._providers: List[Provider] = []
        self._last: Signature = frozenset()
        self._timer: Optional[asyncio.TimerHandle] = None
        self._gain_listeners: List[Callable[[], None]] = []
        self._gain_id_listeners: List[Callable[[List[Tuple[str, str]]], None]] = []
        self.version = 0

    def on_gain(self, listener: Callable[[], None]) -> None:
        self._gain_listeners.append(listener)

    def on_gain_ids(self, listener: Callable[[List[Tuple[str, str]]], None]) -> None:
        self._gain_id_listeners.append(listener)

    def register(self, provider: Provider) -> None:
        self._providers.append(provider)

    def _signature(self) -> Signature:
        merged: set = set()
        for provider in self._providers:
            try:
                merged |= provider.signature()
            except (AttributeError, KeyError, ValueError) as exc:
                logger.warning("approvals_signature_failed", error_type=type(exc).__name__)
        return frozenset(merged)

    def refresh(self) -> bool:
        signature = self._signature()
        if signature == self._last:
            return False
        gained = {entry[1] for entry in signature} - {entry[1] for entry in self._last}
        gained_pairs = sorted((e[0], e[1]) for e in signature if e[1] in gained)
        self._last = signature
        self.version += 1
        if gained:
            for listener in self._gain_listeners:
                try:
                    listener()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("approvals_gain_listener_failed", error_type=type(exc).__name__)
        for id_listener in self._gain_id_listeners if gained else ():
            try:
                id_listener(gained_pairs)
            except Exception as exc:  # noqa: BLE001
                logger.warning("approvals_gain_id_listener_failed", error_type=type(exc).__name__)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._emit()
            return True
        if self._timer is None:
            self._timer = loop.call_later(self._debounce, self._emit)
        return True

    def _emit(self) -> None:
        self._timer = None
        self._publish({"type": "approvals", "version": self.version, "count": len(self._last)})
        resource_push.notify(resource_topics.APPROVALS)

    async def list_items(self) -> List[Dict[str, Any]]:
        self.refresh()
        out: List[Dict[str, Any]] = []
        for provider in self._providers:
            out += await provider.items()
        return sorted(valid_items(out), key=lambda i: i.get("created_at") or "")
