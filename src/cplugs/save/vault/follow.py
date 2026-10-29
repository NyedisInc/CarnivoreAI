
from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Deque, Dict, List, Optional, Sequence, Set, Tuple

import structlog

from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault import folders, health, retention, units
from src.cplugs.save.vault.identity import Identity, ProjectIndex
from src.cplugs.save.vault.location import VaultUnavailable
from src.cplugs.save.vault.manifest import Manifest
from src.cplugs.save.vault.legacy import LegacyProgress
from src.cplugs.save.vault.store import STATUS_FAILED, STATUS_PARTIAL, STATUS_UNCHANGED, STATUS_WRITTEN, Vault
from src.cplugs.sdk.vault_sources import VaultFolder
from src.cplugs.sdk.blob_codec import Throttle
from src.cplugs.sdk.vault_sources import SourceUnavailable

logger = structlog.get_logger()

SWEEP_SECONDS: float = 6 * 3600
SIDE_DB_SECONDS: float = 3600
ASSESS_SECONDS: float = 600
GC_SECONDS: float = 24 * 3600
GC_BUSY_RETRY_SECONDS: float = 60
RETRY_FIRST_SECONDS: float = 120
RETRY_MAX_SECONDS: float = 3600


@dataclass(frozen=True)
class SliceResult:

    captured: int = 0
    unchanged: int = 0
    failed: int = 0
    queued: int = 0
    more: bool = False
    unavailable: str = ""


def needs_capture(plan: units.UnitPlan, newest: Optional[Manifest], verified: Optional[Dict[str, Tuple[int, int]]] = None) -> bool:
    if newest is None:
        return True
    known = {(f.home, f.rel): f for f in newest.files}
    for planned in plan.files:
        entry = known.get((planned.home, planned.rel))
        if entry is None:
            return True
        try:
            st = os.stat(planned.path)
        except OSError:
            continue
        if verified is not None and verified.get(str(planned.path)) == (st.st_size, st.st_mtime_ns):
            continue
        if st.st_size != entry.size_seen or st.st_mtime_ns != entry.mtime_ns or entry.tail_due(st.st_mtime_ns, time.time()):
            return True
    return False


class Engine:

    def __init__(self, open_vault: Callable[[], Vault], state_dir: Path, sources: Callable[[], units.Sources], *,
                 rows: Optional[Callable[[], List[dict]]] = None, projects: Optional[Callable[[], List[dict]]] = None,
                 side_dbs: Optional[Callable[[], Sequence[Tuple[str, Path]]]] = None,
                 folders: Optional[Callable[[], Sequence[VaultFolder]]] = None,
                 cap_bytes: Callable[[], int] = lambda: K.DEFAULT_HISTORY_CAP_BYTES,
                 legacy: Optional[Callable[[Vault, Throttle], LegacyProgress]] = None, throttle: Optional[Throttle] = None,
                 clock: Callable[[], float] = time.time) -> None:
        self._open, self._state_dir, self._sources = open_vault, Path(state_dir), sources
        self._rows, self._projects, self._side_dbs, self._folders = rows, projects, side_dbs, folders
        self._folders_at = 0.0
        self._cap, self._legacy = cap_bytes, legacy
        self.throttle = throttle or Throttle(K.DUTY_CYCLE, K.SLICE_SECONDS)
        self._clock = clock
        self._queue: Deque[Tuple[str, str]] = deque()
        self._queued: Set[str] = set()
        self._retry: Dict[str, Tuple[float, int]] = {}
        self._index: Optional[Dict[str, Tuple[int, int]]] = None
        self._verified: Dict[str, Tuple[int, int]] = {}
        self._swept_at: Optional[float] = None
        self._side_at = self._assess_at = self._gc_at = 0.0
        self._legacy_pending = legacy is not None
        self._legacy_retry_at = 0.0
        self._legacy_failed = 0
        self._assessed_cap: Optional[int] = None
        self._progress_at: Optional[float] = None
        self._last_uncovered: Optional[int] = None
        self._dirty_since_assess = False
        self._damaged = 0
        self._uncovered_units: Optional[Set[str]] = None
        self._started_at = clock()

    def _enqueue(self, unit: str, family: str, front: bool = False) -> None:
        if unit in self._queued:
            return
        self._queued.add(unit)
        (self._queue.appendleft if front else self._queue.append)((unit, family))

    def enqueue_unit(self, unit: str, family: str) -> None:
        """Ask for a unit to be captured soon (a lifecycle event the hook could not capture itself). Output: None."""
        self._enqueue(unit, family, front=True)

    def cancel(self) -> None:
        self.throttle.cancel()

    def _load_index(self, vault: Vault) -> Dict[str, Tuple[int, int]]:
        index: Dict[str, Tuple[int, int]] = {}
        for unit in vault.manifests.units():
            newest = vault.manifests.newest(unit)
            if newest is not None:
                index.update({f.source_path: (f.size_seen, f.mtime_ns) for f in newest.files})
        return index

    def _refresh_index(self, vault: Vault, unit: str) -> None:
        newest = vault.manifests.newest(unit)
        if self._index is not None and newest is not None:
            self._index.update({f.source_path: (f.size_seen, f.mtime_ns) for f in newest.files})

    def _sweep(self, vault: Vault, sources: units.Sources, now: float) -> None:
        skipped: List[str] = []
        plans = units.scan_all(sources, units.Scanner(sources), skipped)
        todo: List[Tuple[float, str, str]] = []
        on_disk = len(skipped)
        uncovered_units: Set[str] = {f"?{name}" for name in skipped}
        for unit, plan in plans.items():
            newest = vault.manifests.newest(unit)
            if plan.kind == units.KIND_CONVERSATION:
                on_disk += 1
                if newest is None:
                    uncovered_units.add(unit)
            if needs_capture(plan, newest, self._verified):
                main = plan.main_path() or (plan.files[0].path if plan.files else None)
                try:
                    mtime = os.stat(main).st_mtime if main else 0.0
                except OSError:
                    mtime = 0.0
                todo.append((mtime, unit, plan.family))
        for _mtime, unit, family in sorted(todo, reverse=True):
            self._enqueue(unit, family)
        self._swept_at = now
        self._index = None
        self._uncovered_units = uncovered_units
        health.update(self._state_dir, swept_at=now, on_disk=on_disk, **self._coverage(now))
        logger.info("vault_sweep", on_disk=on_disk, uncovered=len(uncovered_units), queued=len(todo))

    def _coverage(self, now: float) -> Dict[str, object]:
        count = len(self._uncovered_units or ())
        if not count:
            self._progress_at = self._last_uncovered = None
            return {"uncovered": 0, "uncovered_since": None}
        if self._progress_at is None:
            self._progress_at = health.read(self._state_dir).get("uncovered_since") or now
        if self._last_uncovered is not None and count < self._last_uncovered:
            self._progress_at = now
        self._last_uncovered = count
        return {"uncovered": count, "uncovered_since": self._progress_at}

    def _follow(self, vault: Vault) -> bool:
        if self._rows is None:
            return False
        try:
            rows = self._rows()
        except SourceUnavailable as exc:
            logger.warning("vault_follow_manifest_unavailable", error=str(exc))
            return False
        if self._index is None:
            self._index = self._load_index(vault)
        for row in rows:
            conv = row.get("conversation_id")
            if not conv or row.get("gone_at") or row.get("dataless") or row.get("status") == "gone":
                continue
            signature = (row["size"], row["mtime_ns"])
            if self._index.get(row["path"]) != signature and self._verified.get(row["path"]) != signature:
                self._enqueue(conv, row.get("family") or units.FAMILY_CLAUDE)
        return True

    def _identity(self, plan: units.UnitPlan, index: ProjectIndex) -> Identity:
        return index.complete(Identity(working_dir=units.peek_working_dir(plan.main_path())))

    def _project_index(self) -> ProjectIndex:
        if self._projects is None:
            return ProjectIndex()
        try:
            return ProjectIndex(self._projects())
        except SourceUnavailable as exc:
            logger.warning("vault_projects_unavailable", error=str(exc))
            return ProjectIndex()

    @staticmethod
    def _stat_signatures(plan: units.UnitPlan) -> Dict[str, Tuple[int, int]]:
        found: Dict[str, Tuple[int, int]] = {}
        for planned in plan.files:
            try:
                st = os.stat(planned.path)
            except OSError:
                continue
            found[str(planned.path)] = (st.st_size, st.st_mtime_ns)
        return found

    def _backoff(self, unit: str, now: float) -> None:
        attempts = self._retry.get(unit, (0.0, 0))[1] + 1
        self._retry[unit] = (now + min(RETRY_MAX_SECONDS, RETRY_FIRST_SECONDS * 2 ** (attempts - 1)), attempts)

    def _drain(self, vault: Vault, sources: units.Sources, now: float) -> Tuple[int, int, int]:
        captured = unchanged = failed = 0
        projects = self._project_index()
        scanner = units.Scanner(sources)
        held: List[Tuple[str, str]] = []
        handled = 0
        while self._queue and not self.throttle.cancelled and (handled == 0 or not self.throttle.expired()):
            unit, family = self._queue.popleft()
            self._queued.discard(unit)
            if self._retry.get(unit, (0.0, 0))[0] > now:
                held.append((unit, family))
                continue
            handled += 1
            plan = units.plan_for(sources, unit, family, scanner)
            if plan is None:
                continue
            prior = vault.manifests.newest(unit)
            seen = self._stat_signatures(plan)
            outcome = vault.capture(plan, self._identity(plan, projects), K.REASON_FOLLOW if prior else K.REASON_BACKFILL,
                                    pace=self.throttle)
            self._damaged += outcome.damaged
            if outcome.status == STATUS_PARTIAL:
                self._enqueue(unit, family, front=True)
                break
            if outcome.status == STATUS_FAILED or outcome.failures:
                failed += 1
                self._backoff(unit, now)
                logger.warning("vault_capture_incomplete", unit=unit, status=outcome.status, failures=list(outcome.failures)[:3])
            else:
                self._retry.pop(unit, None)
            if outcome.status == STATUS_WRITTEN:
                captured += 1
                self._dirty_since_assess = True
            elif outcome.status != STATUS_FAILED:
                unchanged += 1
                if outcome.status == STATUS_UNCHANGED and not outcome.failures:
                    self._verified.update(seen)
            self._refresh_index(vault, unit)
            if self._uncovered_units is not None and vault.manifests.newest(unit) is not None:
                self._uncovered_units.discard(unit)
        for unit, family in held:
            self._enqueue(unit, family)
        return captured, unchanged, failed

    def _ready(self, now: float) -> int:
        return sum(1 for unit, _family in self._queue if self._retry.get(unit, (0.0, 0))[0] <= now)

    def _legacy_due(self, now: float) -> bool:
        return self._legacy_pending and self._legacy is not None and now >= self._legacy_retry_at

    def _maintain(self, vault: Vault, now: float) -> None:
        if self._side_dbs is not None and now - self._side_at >= SIDE_DB_SECONDS:
            self._side_at = now
            outcome = vault.capture_side_databases(self._state_dir, list(self._side_dbs()), pace=self.throttle)
            self._dirty_since_assess |= outcome.status == STATUS_WRITTEN
        if self._folders is not None and now - self._folders_at >= SIDE_DB_SECONDS and not self.throttle.cancelled:
            if self._capture_folders(vault):
                self._folders_at = now
        if self._legacy_due(now):
            progress = self._legacy(vault, self.throttle)
            self._legacy_failed = progress.failed
            self._legacy_pending = progress.more or progress.failed > 0
            self._legacy_retry_at = now + K.LEGACY_RETRY_SECONDS if progress.failed and not progress.more else 0.0
            self._dirty_since_assess = True
        cap = self._cap()
        if (self._dirty_since_assess or cap != self._assessed_cap) and now - self._assess_at >= ASSESS_SECONDS:
            self._assess_at, self._dirty_since_assess, self._assessed_cap = now, False, cap
            retention.assess(vault, self._cap, now=now, pace=self.throttle)
        if now - self._gc_at >= GC_SECONDS:
            if retention.collect_garbage(vault, now=now).get("busy"):
                self._gc_at = now - GC_SECONDS + GC_BUSY_RETRY_SECONDS
            else:
                self._gc_at = now

    def _capture_folders(self, vault: Vault) -> bool:
        rows: List[dict] = []
        complete = True
        for folder in self._folders():
            if folder.opted_out:
                rows.append(folders.status_row(vault.manifests, folder.unit, folder.root, folders.STATUS_SWITCHED_OFF,
                                               "switched off in the backup menu"))
                continue
            if folder.root is None:
                rows.append(folders.status_row(vault.manifests, folder.unit, None, "no_root", "the plugin's folder setting is blank"))
                continue
            if not complete:
                rows.append(folders.status_row(vault.manifests, folder.unit, folder.root, STATUS_PARTIAL))
                continue
            outcome = vault.capture_folder(folder.unit, folder.root, pace=self.throttle)
            complete = outcome.status != STATUS_PARTIAL
            self._dirty_since_assess |= outcome.status == STATUS_WRITTEN
            if outcome.status == STATUS_FAILED or outcome.failures:
                logger.warning("vault_folder_capture_incomplete", unit=folder.unit, status=outcome.status, detail=outcome.detail,
                               failures=list(outcome.failures)[:3])
            rows.append(folders.status_row(vault.manifests, folder.unit, folder.root, outcome.status,
                                           outcome.detail or "; ".join(outcome.failures[:3])))
        health.update(self._state_dir, folders=rows)
        return complete

    def run_slice(self) -> SliceResult:
        self.throttle.begin_slice()
        now = self._clock()
        if self.throttle.cancelled:
            return SliceResult()
        try:
            vault = self._open()
        except VaultUnavailable as exc:
            health.update(self._state_dir, unavailable=str(exc), started_at=self._started_at)
            logger.error("vault_unavailable", error=str(exc))
            return SliceResult(unavailable=str(exc))
        sources = self._sources()
        if self._swept_at is None or now - self._swept_at >= SWEEP_SECONDS:
            self._sweep(vault, sources, now)
        elif not self._follow(vault) and not self._queue:
            self._sweep(vault, sources, now)
        captured, unchanged, failed = self._drain(vault, sources, now)
        ready = self._ready(now)
        if not ready and not self.throttle.cancelled:
            self._maintain(vault, now)
        state = retention.read_state(vault.root)
        last_ok = now if not failed else health.read(self._state_dir).get("last_ok_at", now)
        coverage = self._coverage(now) if self._uncovered_units is not None else {}
        health.update(self._state_dir, active=True, unavailable="", started_at=self._started_at, last_ok_at=last_ok,
                      pending=len(self._queue), over_cap=bool(state.get("over_cap")), damaged=self._damaged,
                      legacy_unmigrated=self._legacy_failed, **coverage)
        return SliceResult(captured, unchanged, failed, len(self._queue), bool(ready) or self._legacy_due(now))
