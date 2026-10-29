
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

WORKING_STATES = frozenset({"working", "working_subagent"})
LIVE_SOURCES = frozenset({"registry", "pane"})
IN_USE_ACTIONS = frozenset({"session_restart", "session_stop", "session_delete", "session_purge"})
_IN_FLIGHT_KEYS = frozenset({"agents", "tasks", "dialog", "working"})


def summarize(info: Any, registry: Any = None) -> Optional[dict]:
    status = info.activity_status or ""
    source = info.status_source or "none"
    signals: list = []
    for key, count in (("agents", info.subagents_running or 0), ("tasks", info.background_open or 0)):
        if count:
            signals.append({"key": key, "params": {"count": str(count)}})
    if status == "question":
        signals.append({"key": "dialog"})
    if status in WORKING_STATES:
        if source in LIVE_SOURCES:
            signals.append({"key": "working", "params": {"source": source}})
        else:
            seen = info.session.last_activity
            seen = seen.astimezone(timezone.utc).replace(tzinfo=None) if seen.tzinfo else seen
            signals.append({"key": "stale_working", "params": {"since": seen.date().isoformat(), "source": source}})
    viewers = len(registry.subscribers.get(info.session.id) or ()) if registry is not None else 0
    if viewers:
        signals.append({"key": "viewers", "params": {"count": str(viewers)}})
    if not signals:
        return None
    in_flight = any(s["key"] in _IN_FLIGHT_KEYS for s in signals)
    return {"in_flight": in_flight, "in_view": not in_flight, "signals": signals, "status": status}


_BLOCKED_IN_FLIGHT = frozenset({"session_delete", "session_purge"})


def blocks_beast(usage: Optional[dict], action: str = "") -> bool:
    return bool(usage and usage["in_flight"] and action in _BLOCKED_IN_FLIGHT)


def display_parts(usage: Optional[dict]) -> dict:
    if not usage:
        return {}
    return {"tone": "alert" if usage["in_flight"] else "quiet", "parts": usage["signals"]}


def _words(signal: dict) -> str:
    p = signal.get("params") or {}
    return {
        "agents": f"{p.get('count')} background agents running",
        "tasks": f"{p.get('count')} background tasks running",
        "dialog": "dialog open",
        "working": f"working ({p.get('source')} reports a turn running)",
        "stale_working": f"claims working, only the {p.get('source')} says so, no activity since {p.get('since')}",
        "viewers": f"open in {p.get('count')} windows",
    }[signal["key"]]


def warning(usage: dict) -> str:
    said = ", ".join(_words(s) for s in usage["signals"])
    if usage["in_flight"]:
        return (f"this session is in use: {said}. Acting on it stops that work, so it waits for the "
                "owner's approval unless Beast Mode is armed (a delete always waits).")
    return f"note: {said}. Nothing proven running in it."
