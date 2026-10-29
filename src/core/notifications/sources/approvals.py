
from __future__ import annotations

from typing import Any, Callable, List, Optional, Tuple

import structlog

from src.core.approvals.extract import KIND_TRUST
from src.core.notifications import contracts
from src.core.notifications.sources import common
from src.core.session_startup_gate import detect_startup_prompt

logger = structlog.get_logger(__name__)

TYPE_AGENT_ACTION = "approval.agent_action"
TYPE_FOLDER_TRUST = "approval.folder_trust"


def is_folder_trust_dialog(dialog: Any) -> bool:
    """True only for the real startup trust dialog: its kind is trust AND its own text carries a startup-prompt marker.

    The kind alone is a substring match on "trust" (``approvals.extract._classify``), so a permission prompt about
    ``trust_utils.py`` or a question that mentions trust would pass it. The startup gate's marker list
    (``session_startup_gate.STARTUP_PROMPT_MARKERS``) is the evidence the dialog really is claude's or codex's trust screen.
    Example: is_folder_trust_dialog(SimpleNamespace(kind="folder_trust", question="Do you trust the contents of this directory?", body="", rows=())) is True
    """
    if dialog is None or dialog.kind != KIND_TRUST:
        return False
    labels = [str(getattr(r, "label", "")) for r in getattr(dialog, "rows", ())]
    text = "\n".join([str(getattr(dialog, "question", "")), str(getattr(dialog, "body", "")), *labels])
    return detect_startup_prompt(text) is True


class ApprovalsSource:

    def __init__(self, get_watcher: Callable[[], Any], get_manager: Callable[[], Any],
                 get_pending_store: Callable[[], Any]) -> None:
        self._watcher = get_watcher
        self._manager = get_manager
        self._store = get_pending_store

    def on_gain(self, gained: List[Tuple[str, str]]) -> None:
        for source, item_id in gained:
            try:
                event = self._agent_action(item_id) if source == "agent_action" else (
                    self._folder_trust(item_id) if source == "dialog" else None)
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                logger.warning("approvals_source_item_failed", source=source, error_type=type(exc).__name__)
                continue
            if event is not None:
                contracts.emit(event)

    def _agent_action(self, item_id: str) -> Optional[contracts.NotifyEvent]:
        row = next((r for r in self._store().list() if r.get("id") == item_id), None)
        if row is None or str(row.get("target_session_id") or "").startswith("remote:"):
            return None
        return contracts.NotifyEvent(
            type_id=TYPE_AGENT_ACTION, kind="agent_action", title=common.type_title(TYPE_AGENT_ACTION),
            ts=common.now(), severity=contracts.SEVERITY_WARN, instance_key=item_id, open_item=True,
            **common.session_fields(self._manager(), row.get("target_session_id") or None),
        )

    def _folder_trust(self, item_id: str) -> Optional[contracts.NotifyEvent]:
        session_id, _ = item_id.removeprefix("dlg:").rsplit(":", 1)
        watcher = self._watcher()
        observation = watcher.observation_for(session_id) if watcher is not None else None
        dialog = getattr(getattr(observation, "evidence", None), "dialog", None)
        if not is_folder_trust_dialog(dialog) or session_id.startswith("remote:"):
            return None
        return contracts.NotifyEvent(
            type_id=TYPE_FOLDER_TRUST, kind="folder_trust", title=common.type_title(TYPE_FOLDER_TRUST),
            ts=common.now(), instance_key=item_id, **common.session_fields(self._manager(), session_id),
        )
