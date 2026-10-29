
from __future__ import annotations

import asyncio
import copy
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.core import resource_push
from src.core import session_journal_store as store
from src.core.resource_push import topics as resource_topics
from src.core.boot_time import (
    CHANGE_CANNOT_DETERMINE,
    CHANGE_REBOOTED,
    BootTime,
    compare_boots,
    read_boot_time,
)
from src.core.session_journal_measure import Measurement, measure
from src.core.session_journal_observe import live_entries, observe
from src.core.swarm import switch as swarm_switch
from src.core.notifications.sources import restore as restore_source
from src.core.session_restore_offer import (
    OFFER_OPEN,
    REASON_TMUX_SERVER_GONE,
    build_offer,
    choose_reason,
    fold_offer,
    offer_candidates,
)

logger = structlog.get_logger()

ENABLE_ENV: str = "CLOUDE_SESSION_JOURNAL"
INTERVAL_ENV: str = "CLOUDE_SESSION_JOURNAL_INTERVAL"
DEFAULT_INTERVAL_SECONDS: int = 30
MIN_INTERVAL_SECONDS: int = 5
_FALSEY = {"0", "false", "no", "off"}
_TRUTHY = {"1", "true", "yes", "on"}

JOURNAL_LOCK = threading.Lock()

BOOT_PASS_ATTEMPTS: int = 3


def journal_enabled() -> bool:
    raw = os.environ.get(ENABLE_ENV)
    if raw is not None:
        value = raw.strip().lower()
        if value in _TRUTHY:
            return True
        if value in _FALSEY:
            return False
    return os.environ.get("CLOUDE_TEST_MODE", "").strip().lower() not in _TRUTHY


def interval_seconds() -> int:
    try:
        return max(MIN_INTERVAL_SECONDS, int(os.environ.get(INTERVAL_ENV, DEFAULT_INTERVAL_SECONDS)))
    except ValueError:
        return DEFAULT_INTERVAL_SECONDS


def _log_events(state_dir: Path, events) -> None:
    for event, text in events:
        store.append_human_log(state_dir, event, text)
        logger.info("session_journal_event", journal_event=event, detail=text)


def _offerable_rows(rows):
    held = swarm_switch.held_row_ids()
    return [r for r in rows if r.get("id") not in held] if held else rows


def _set_offer(journal: Dict[str, Any], state_dir: Path, m: Measurement, reason: str,
               boot: Optional[BootTime], previous_epoch: Optional[int], now: str) -> None:
    candidates = offer_candidates(journal, _offerable_rows(m.rows), live_instances=m.live_instances(),
                                  dead_instances=m.dead_instances())
    previous = journal.get("offer")
    if previous and previous.get("state") == OFFER_OPEN:
        held = {c.get("instance"): c.get("reason") or previous.get("reason")
                for c in previous.get("candidates") or []}
        candidates = [dict(c, reason=held[c["instance"]]) if held.get(c["instance"]) else c
                      for c in candidates]
    offer = build_offer(
        candidates, reason=reason, now_iso=now,
        boot_epoch=boot.epoch if boot and boot.measured else None,
        previous_boot_epoch=previous_epoch, previous=previous,
    )
    if offer is None:
        if previous and previous.get("state") == OFFER_OPEN:
            closed = dict(previous)
            closed.update({"state": "superseded", "decided_at": now})
            journal["offer"] = closed
            store.append_human_log(state_dir, "restore_offer_withdrawn", "nothing left to reopen")
        return
    if not previous or previous.get("id") != offer["id"]:
        names = ", ".join(c.get("title") or c.get("tmux_name") for c in candidates)
        store.append_human_log(state_dir, "restore_offered", f"reason={reason} count={len(candidates)} sessions={names}")
        logger.info("session_restore_offered", reason=reason, count=len(candidates))
        restore_source.on_offered(offer.get("id"))
    journal["offer"] = offer


def _log_offer(state_dir: Path, offer: Dict[str, Any], previous: Optional[Dict[str, Any]]) -> None:
    cands = offer.get("candidates") or []
    names = ", ".join(c.get("title") or c.get("tmux_name") or "?" for c in cands)
    folded = offer.get("folded_from")
    event = "restore_offer_folded" if folded else "restore_offered"
    extra = f" folded_into_new_id_from={folded}" if folded else ""
    store.append_human_log(state_dir, event,
                           f"reason={offer.get('reason')} count={len(cands)}{extra} sessions={names}")
    logger.info("session_restore_offered", reason=offer.get("reason"), count=len(cands),
                folded_from=folded, had_open=bool(previous and previous.get("state") == OFFER_OPEN))
    restore_source.on_offered(offer.get("id"))


def mutate_journal(state_dir: Path, fn) -> Any:
    with JOURNAL_LOCK:
        loaded = store.load_journal(state_dir)
        if loaded.outcome == store.LOAD_UNREADABLE:
            logger.error("session_journal_unreadable", detail=loaded.detail,
                         path=str(store.journal_path(state_dir)))
            return None
        journal = loaded.journal
        offer_before = copy.deepcopy(journal.get("offer"))
        result, changed = fn(journal)
        if changed:
            store.ensure_private(state_dir)
            store.save_journal(state_dir, journal)
            if journal.get("offer") != offer_before:
                resource_push.notify(resource_topics.RESTORE_OFFER)
        return result


def boot_pass(state_dir: Path, settings: Any, socket_name: str, db_path: Path) -> Dict[str, Any]:
    boot = read_boot_time()
    m = measure(settings, socket_name, db_path)
    now = store.now_iso()

    def fn(journal):
        previous = (journal.get("boot") or {}).get("epoch")
        change = compare_boots(previous, boot)
        summary = {"boot_change": change, "boot_epoch": boot.epoch, "previous_boot_epoch": previous,
                   "listing_ok": m.listing_ok, "listing_complete": m.listing_complete,
                   "journal_live": len(live_entries(journal))}
        if change == CHANGE_REBOOTED:
            store.append_human_log(state_dir, "reboot_detected", f"boot time {previous} -> {boot.epoch}")
        elif change == CHANGE_CANNOT_DETERMINE:
            store.append_human_log(state_dir, "boot_time_unmeasured", boot.detail)
        if m.listing_complete and m.rows_ok:
            if not m.server_running and live_entries(journal) and change != CHANGE_REBOOTED:
                store.append_human_log(state_dir, "tmux_server_gone", f"{len(live_entries(journal))} sessions were live")
            _set_offer(journal, state_dir, m, choose_reason(change, m.server_running), boot, previous, now)
        else:
            store.append_human_log(state_dir, "restore_offer_not_evaluated",
                                   f"listing_complete={m.listing_complete} rows_ok={m.rows_ok}")
        result = observe(journal, listing_ok=m.listing_ok, listing_complete=m.listing_complete,
                         panes=m.panes, rows_by_instance=m.rows_by_instance(), groups=m.groups, now_iso=now)
        journal.clear()
        journal.update(result.journal)
        journal["socket"] = socket_name
        if boot.measured:
            journal["boot"] = {"epoch": boot.epoch, "source": boot.source, "recorded_at": now}
        _log_events(state_dir, result.events)
        offer = journal.get("offer") or {}
        summary["offer_state"] = offer.get("state")
        summary["offer_count"] = len(offer.get("candidates") or []) if offer.get("state") == OFFER_OPEN else 0
        return summary, True

    summary = mutate_journal(state_dir, fn) or {"journal": "unreadable"}
    logger.info("session_journal_boot_pass", **summary)
    return summary


def observe_pass(state_dir: Path, settings: Any, socket_name: str, db_path: Path) -> Dict[str, Any]:
    m = measure(settings, socket_name, db_path)
    now = store.now_iso()

    def fn(journal):
        had_live = bool(live_entries(journal))
        result = observe(journal, listing_ok=m.listing_ok, listing_complete=m.listing_complete,
                         panes=m.panes, rows_by_instance=m.rows_by_instance(), groups=m.groups, now_iso=now)
        changed = result.changed
        new = result.journal
        if had_live and m.listing_complete and m.rows_ok and not m.server_running:
            store.append_human_log(state_dir, "tmux_server_gone", "the socket has no server")
            fresh = offer_candidates(journal, _offerable_rows(m.rows), live_instances=m.live_instances(),
                                     dead_instances=m.dead_instances())
            previous = new.get("offer")
            offer, minted = fold_offer(previous, fresh, reason=REASON_TMUX_SERVER_GONE, now_iso=now,
                                       boot_epoch=(journal.get("boot") or {}).get("epoch"))
            if minted:
                _log_offer(state_dir, offer, previous)
                new["offer"] = offer
                changed = True
        journal.clear()
        journal.update(new)
        _log_events(state_dir, result.events)
        return {"changed": changed, "events": len(result.events)}, changed

    return mutate_journal(state_dir, fn) or {"journal": "unreadable"}


class SessionJournalScheduler:

    def __init__(self, state_dir: Path, settings: Any, socket_name: str, db_path: Path) -> None:
        self.state_dir = Path(state_dir)
        self.settings = settings
        self.socket_name = socket_name
        self.db_path = Path(db_path)
        self.interval = interval_seconds()
        self.enabled = journal_enabled()
        self.boot_summary: Optional[Dict[str, Any]] = None
        self._cancel = threading.Event()
        self._task: Optional[asyncio.Task] = None

    def start(self) -> bool:
        if not self.enabled:
            logger.info("session_journal_disabled", env=ENABLE_ENV)
            return False
        if self._task is not None and not self._task.done():
            return False
        self._cancel.clear()
        self._task = asyncio.create_task(self._loop())
        logger.info("session_journal_started", interval_seconds=self.interval,
                    journal=str(store.journal_path(self.state_dir)))
        return True

    async def _loop(self) -> None:
        first = True
        boot_failures = 0
        while not self._cancel.is_set():
            try:
                if first:
                    self.boot_summary = await asyncio.to_thread(
                        boot_pass, self.state_dir, self.settings, self.socket_name, self.db_path)
                    first = False
                else:
                    await asyncio.to_thread(
                        observe_pass, self.state_dir, self.settings, self.socket_name, self.db_path)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                if first:
                    boot_failures += 1
                    first = boot_failures < BOOT_PASS_ATTEMPTS
                logger.warning("session_journal_pass_crashed", error=f"{type(exc).__name__}: {exc}",
                               boot_failures=boot_failures, boot_retry_pending=first)
            if self._cancel.is_set():
                break
            await asyncio.sleep(self.interval)

    async def aclose(self, timeout: float = 10.0) -> None:
        self._cancel.set()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout=timeout)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
