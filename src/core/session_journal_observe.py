
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from src.core.session_journal_store import iso_to_epoch
from src.core.session_restore_rules import pick_conversation

LAST_SEEN_HEARTBEAT_SECONDS: int = 300
GONE_RETENTION_SECONDS: int = 30 * 24 * 3600

STATE_LIVE: str = "live"
STATE_GONE: str = "gone"

GONE_ABSENT: str = "absent_from_listing"
GONE_PANE_DEAD: str = "pane_dead"

EVENT_SEEN: str = "session_seen"
EVENT_GONE: str = "session_gone"
EVENT_CONVERSATION: str = "conversation_changed"
EVENT_DISAGREE: str = "conversation_disagrees_with_record"

STABLE_FIELDS: Tuple[str, ...] = (
    "tmux_name", "tmux_epoch", "session_uuid", "row_id", "title", "group",
    "pinned_theme", "agent_type", "working_dir", "cwd", "claude_pid", "argv",
    "observed_flags", "conversation_measured", "conversation_measured_source",
    "conversation_recorded", "conversation_agree", "state", "gone_reason",
)


@dataclass(frozen=True)
class PaneFacts:

    name: str
    epoch: Optional[int]
    dead: bool = False
    claude_pid: Optional[int] = None
    argv: Optional[str] = None
    observed_flags: Optional[List[str]] = None
    conversation: Optional[str] = None
    conversation_source: Optional[str] = None
    cwd: Optional[str] = None


@dataclass
class ObserveResult:

    journal: Dict[str, Any]
    events: List[Tuple[str, str]] = field(default_factory=list)
    changed: bool = False


def instance_key(name: str, epoch: Optional[int]) -> str:
    return f"{name}@{epoch if epoch is not None else 'unknown'}"


def _entry(pane: PaneFacts, row: Optional[Mapping[str, Any]], group: Optional[str]) -> Dict[str, Any]:
    recorded = (row or {}).get("claude_session_uuid")
    _uuid, _src, agree = pick_conversation(pane.conversation, recorded)
    return {
        "tmux_name": pane.name,
        "tmux_epoch": pane.epoch,
        "session_uuid": (row or {}).get("session_uuid"),
        "row_id": (row or {}).get("id"),
        "title": (row or {}).get("title"),
        "group": group,
        "pinned_theme": (row or {}).get("pinned_theme"),
        "agent_type": (row or {}).get("agent_type"),
        "working_dir": (row or {}).get("working_dir"),
        "cwd": pane.cwd,
        "claude_pid": pane.claude_pid,
        "argv": pane.argv,
        "observed_flags": pane.observed_flags,
        "conversation_measured": pane.conversation,
        "conversation_measured_source": pane.conversation_source,
        "conversation_recorded": recorded,
        "conversation_agree": agree,
        "state": STATE_GONE if pane.dead else STATE_LIVE,
        "gone_reason": GONE_PANE_DEAD if pane.dead else None,
    }


def _label(entry: Mapping[str, Any]) -> str:
    title = entry.get("title")
    name = entry.get("tmux_name")
    return f"{name} ({title})" if title and title != name else str(name)


def observe(
    journal: Dict[str, Any],
    *,
    listing_ok: bool,
    listing_complete: bool,
    panes: List[PaneFacts],
    rows_by_instance: Mapping[Tuple[str, Optional[int]], Mapping[str, Any]],
    groups: Mapping[str, str],
    now_iso: str,
) -> ObserveResult:
    out = dict(journal)
    sessions: Dict[str, Dict[str, Any]] = {k: dict(v) for k, v in (journal.get("sessions") or {}).items()}
    events: List[Tuple[str, str]] = []
    changed = False
    now = iso_to_epoch(now_iso) or 0.0

    if not listing_ok:
        return ObserveResult(journal=journal, events=[], changed=False)

    seen_keys = set()
    for pane in panes:
        key = instance_key(pane.name, pane.epoch)
        seen_keys.add(key)
        row = rows_by_instance.get((pane.name, pane.epoch))
        fresh = _entry(pane, row, groups.get((row or {}).get("session_uuid")))
        prior = sessions.get(key)
        if prior is None:
            fresh["first_seen"] = now_iso
            fresh["last_seen_live"] = None if pane.dead else now_iso
            fresh["gone_at"] = now_iso if pane.dead else None
            sessions[key] = fresh
            changed = True
            events.append((EVENT_SEEN, f"{_label(fresh)} conversation={fresh['conversation_measured'] or fresh['conversation_recorded'] or 'none'} cwd={fresh['cwd']}"))
            if fresh["conversation_measured"] and fresh["conversation_recorded"] and not fresh["conversation_agree"]:
                events.append((EVENT_DISAGREE, f"{_label(fresh)} process={fresh['conversation_measured']} record={fresh['conversation_recorded']}"))
            continue
        if prior.get("conversation_measured") and fresh["conversation_measured"] \
                and prior.get("conversation_measured") != fresh["conversation_measured"]:
            events.append((EVENT_CONVERSATION, f"{_label(fresh)} {prior.get('conversation_measured')} -> {fresh['conversation_measured']}"))
        if fresh["state"] == STATE_GONE and prior.get("state") == STATE_LIVE:
            events.append((EVENT_GONE, f"{_label(fresh)} reason={GONE_PANE_DEAD}"))
            fresh["gone_at"] = now_iso
        else:
            fresh["gone_at"] = prior.get("gone_at") if fresh["state"] == STATE_GONE else None
        if fresh["conversation_measured"] is None and prior.get("conversation_measured") and not pane.dead:
            for f in ("conversation_measured", "conversation_measured_source"):
                fresh[f] = prior.get(f)
        fresh["first_seen"] = prior.get("first_seen") or now_iso
        last = prior.get("last_seen_live")
        if fresh["state"] == STATE_LIVE and (
            last is None or now - (iso_to_epoch(last) or 0.0) >= LAST_SEEN_HEARTBEAT_SECONDS
        ):
            fresh["last_seen_live"] = now_iso
            changed = True
        else:
            fresh["last_seen_live"] = last
        if any(fresh.get(f) != prior.get(f) for f in STABLE_FIELDS):
            changed = True
        sessions[key] = fresh

    if listing_complete:
        for key, entry in list(sessions.items()):
            if key in seen_keys:
                continue
            if entry.get("state") == STATE_LIVE:
                entry["state"] = STATE_GONE
                entry["gone_reason"] = GONE_ABSENT
                entry["gone_at"] = now_iso
                changed = True
                events.append((EVENT_GONE, f"{_label(entry)} reason={GONE_ABSENT} last_seen_live={entry.get('last_seen_live')}"))
            gone_at = iso_to_epoch(entry.get("gone_at"))
            if entry.get("state") == STATE_GONE and gone_at and now - gone_at > GONE_RETENTION_SECONDS:
                del sessions[key]
                changed = True

    out["sessions"] = sessions
    return ObserveResult(journal=out, events=events, changed=changed)


def live_entries(journal: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {
        k: v for k, v in (journal.get("sessions") or {}).items()
        if v.get("state") == STATE_LIVE
    }
