
from __future__ import annotations

from typing import Any, Dict, Hashable, Optional


class ViewerFocusTracker:

    def __init__(self) -> None:
        self._focus: Dict[str, Dict[Hashable, bool]] = {}

    def report(self, session_id: str, socket_key: Hashable, focused: bool) -> None:
        self._focus.setdefault(session_id, {})[socket_key] = bool(focused)

    def forget(self, session_id: str, socket_key: Hashable) -> None:
        sockets = self._focus.get(session_id)
        if sockets is None:
            return
        sockets.pop(socket_key, None)
        if not sockets:
            del self._focus[session_id]

    def state(self, session_id: str, socket_key: Hashable) -> Optional[bool]:
        return self._focus.get(session_id, {}).get(socket_key)


def get_tracker(session_manager: Any) -> ViewerFocusTracker:
    tracker = getattr(session_manager, "_viewer_focus", None)
    if tracker is None:
        tracker = ViewerFocusTracker()
        try:
            session_manager._viewer_focus = tracker
        except (AttributeError, TypeError):
            pass
    return tracker


def report_focus(session_manager: Any, session_id: str, socket_key: Hashable, focused: bool, *, marks_viewed: bool = True) -> None:
    get_tracker(session_manager).report(session_id, socket_key, focused)
    if focused and marks_viewed:
        session_manager.mark_session_viewed(session_id)


def is_watched(session_manager: Any, session_id: str) -> bool:
    negotiator = getattr(session_manager, "_terminal_size_negotiator", None)
    if negotiator is None:
        return False
    tracker = get_tracker(session_manager)
    return any(
        tracker.state(session_id, key) is not False
        for key in negotiator.visible_keys(session_id)
    )
