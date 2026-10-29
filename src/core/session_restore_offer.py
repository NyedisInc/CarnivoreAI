"""
Description: PURE. It decides from the journal, the ``sessions`` rows and one
  measured listing; the background task and the routes do the measuring and
  the writing.

  WHY. The reason is chosen from measurements and the words follow it:
    reboot            the kernel boot time moved.
    tmux_server_gone  same boot, and the socket has no server at all.
    sessions_gone     same boot, the server is up, some sessions vanished.
    unknown_boot      the boot time could not be read. It does NOT claim a
                      reboot: an unmeasurable boot time is not a reboot.
  tmux being gone is never, on its own, evidence of a reboot.

  DECLINING IS REMEMBERED PER INSTANCE. A declined instance is not offered
  again, so the page does not nag on every load; the same row dying again
  under a NEW instance is a new event and is offered.

  LEAVING A ROW UNTICKED IS NOT DECLINING IT (1.11.1). An accept closes the
  offer, so nothing unticked comes back on the next page load, but it is not
  written to ``declined`` either: the next event that builds an offer (a
  boot, the terminal server going away) may offer it again. Only "not now"
  declines. Before 1.11.1 an unticked row was declined, which made the
  pre-tick rule (older sessions start unticked) a silent way of declining
  every older session on the first accept.
"""

from __future__ import annotations

import uuid as _uuid
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from src.core.boot_time import CHANGE_CANNOT_DETERMINE, CHANGE_REBOOTED
from src.core.session_journal_observe import GONE_PANE_DEAD, STATE_LIVE, instance_key

REASON_REBOOT: str = "reboot"
REASON_TMUX_SERVER_GONE: str = "tmux_server_gone"
REASON_SESSIONS_GONE: str = "sessions_gone"
REASON_UNKNOWN_BOOT: str = "unknown_boot"

OFFER_OPEN: str = "open"
OFFER_DECLINED: str = "declined"
OFFER_ACCEPTED: str = "accepted"

SOURCE_JOURNAL: str = "journal"

CLOSED_BY_USER: str = "closed_by_user"

SLEPT_BY_USER: str = "slept_by_user"

SLEPT_BY_TIMER: str = "slept_by_timer"

USER_STOPPED: frozenset = frozenset({CLOSED_BY_USER, SLEPT_BY_USER})

PANE_DEAD: str = "pane_dead"

NEVER_OFFERED: frozenset = USER_STOPPED | {SLEPT_BY_TIMER, PANE_DEAD}


def choose_reason(boot_change: str, server_running: bool) -> str:
    if boot_change == CHANGE_REBOOTED:
        return REASON_REBOOT
    if boot_change == CHANGE_CANNOT_DETERMINE:
        return REASON_UNKNOWN_BOOT
    if not server_running:
        return REASON_TMUX_SERVER_GONE
    return REASON_SESSIONS_GONE


def _declined(declined: Mapping[str, Any], session_uuid: str, instance: str) -> bool:
    rec = declined.get(session_uuid)
    return bool(rec) and rec.get("instance") == instance


def offer_candidates(
    journal: Mapping[str, Any],
    rows: Iterable[Mapping[str, Any]],
    *,
    live_instances: Set[Tuple[str, Optional[int]]],
    dead_instances: Optional[Set[Tuple[str, Optional[int]]]] = None,
) -> List[Dict[str, Any]]:
    rows = list(rows)
    by_uuid = {r.get("session_uuid"): r for r in rows if r.get("session_uuid")}
    declined = journal.get("declined") or {}
    live_uuids = {
        r.get("session_uuid") for r in rows
        if (r.get("tmux_name"), r.get("tmux_created_epoch")) in live_instances
    }
    dead = dead_instances or set()
    out: Dict[str, Dict[str, Any]] = {}

    for key, entry in (journal.get("sessions") or {}).items():
        su = entry.get("session_uuid")
        if not su or su in live_uuids:
            continue
        instance = (entry.get("tmux_name"), entry.get("tmux_epoch"))
        if instance in live_instances or instance in dead or entry.get("gone_reason") == GONE_PANE_DEAD:
            continue
        row = by_uuid.get(su)
        if row is None or row.get("archived_at") or row.get("lifecycle_source") in NEVER_OFFERED:
            continue
        was_live = entry.get("state") == STATE_LIVE or entry.get("gone_reason")
        if not was_live or _declined(declined, su, key):
            continue
        if (row.get("tmux_name"), row.get("tmux_created_epoch")) != (entry.get("tmux_name"), entry.get("tmux_epoch")):
            continue
        out[su] = _candidate(row, entry, key, SOURCE_JOURNAL)

    return sorted(out.values(), key=lambda c: ((c.get("title") or c.get("tmux_name") or "").lower(), c["session_uuid"]))


def _candidate(row: Mapping[str, Any], entry: Optional[Mapping[str, Any]], key: str, source: str) -> Dict[str, Any]:
    entry = entry or {}
    return {
        "session_uuid": row.get("session_uuid"),
        "instance": key,
        "reason": None,
        "source": source,
        "tmux_name": row.get("tmux_name"),
        "tmux_epoch": row.get("tmux_created_epoch"),
        "title": row.get("title"),
        "folder": entry.get("cwd") or row.get("working_dir"),
        "conversation_measured": entry.get("conversation_measured"),
        "conversation_recorded": row.get("claude_session_uuid"),
        "argv": entry.get("argv"),
        "observed_flags": entry.get("observed_flags"),
        "agent_type": row.get("agent_type"),
        "last_seen_live": entry.get("last_seen_live") or row.get("last_seen_running_at"),
        "last_work_at": row.get("last_work_at"),
        "group": entry.get("group"),
        "pinned_theme": row.get("pinned_theme"),
    }


def build_offer(
    candidates: List[Dict[str, Any]],
    *,
    reason: str,
    now_iso: str,
    boot_epoch: Optional[int],
    previous_boot_epoch: Optional[int],
    previous: Optional[Mapping[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    if not candidates:
        return None
    candidates = [c if c.get("reason") else {**c, "reason": reason} for c in candidates]
    instances = sorted(c["instance"] for c in candidates)
    if previous and previous.get("state") == OFFER_OPEN and sorted(previous.get("instances") or []) == instances:
        kept = dict(previous)
        kept["candidates"] = candidates
        return kept
    return {
        "id": _uuid.uuid4().hex,
        "state": OFFER_OPEN,
        "reason": reason,
        "created_at": now_iso,
        "boot_epoch": boot_epoch,
        "previous_boot_epoch": previous_boot_epoch,
        "instances": instances,
        "candidates": candidates,
    }


def fold_offer(
    previous: Optional[Mapping[str, Any]],
    fresh: List[Dict[str, Any]],
    *,
    reason: str,
    now_iso: str,
    boot_epoch: Optional[int],
) -> Tuple[Optional[Dict[str, Any]], bool]:
    kept: List[Dict[str, Any]] = []
    if previous and previous.get("state") == OFFER_OPEN:
        kept = [dict(c, reason=c.get("reason") or previous.get("reason")) for c in previous.get("candidates") or []]
    held = {c["instance"] for c in kept}
    added = [dict(c, reason=reason) for c in fresh if c["instance"] not in held]
    if not added:
        if kept:
            return dict(previous), False
        return None, False
    added_uuids = {c["session_uuid"] for c in added}
    merged = [c for c in kept if c["session_uuid"] not in added_uuids] + added
    merged.sort(key=lambda c: ((c.get("title") or c.get("tmux_name") or "").lower(), c["session_uuid"]))
    offer = build_offer(merged, reason=reason, now_iso=now_iso, boot_epoch=boot_epoch,
                        previous_boot_epoch=(previous or {}).get("previous_boot_epoch") if kept else None)
    if kept:
        offer["folded_from"] = previous.get("id")
    return offer, True


def decline(journal: Dict[str, Any], offer_id: str, now_iso: str) -> bool:
    offer = journal.get("offer")
    if not offer or offer.get("id") != offer_id or offer.get("state") != OFFER_OPEN:
        return False
    declined = dict(journal.get("declined") or {})
    for c in offer.get("candidates") or []:
        declined[c["session_uuid"]] = {"instance": c["instance"], "at": now_iso, "offer_id": offer_id}
    journal["declined"] = declined
    offer = dict(offer)
    offer.update({"state": OFFER_DECLINED, "decided_at": now_iso})
    journal["offer"] = offer
    return True


def settle_accept(
    journal: Dict[str, Any],
    offer_id: str,
    results: List[Dict[str, Any]],
    now_iso: str,
) -> bool:
    offer = journal.get("offer")
    if not offer or offer.get("id") != offer_id or offer.get("state") != OFFER_OPEN:
        return False
    offer = dict(offer)
    offer.update({"state": OFFER_ACCEPTED, "decided_at": now_iso, "results": results})
    journal["offer"] = offer
    return True
