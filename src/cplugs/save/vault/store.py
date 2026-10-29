
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import structlog

from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault import folders, retention, sidedb, units
from src.cplugs.save.vault.guard import CaptureGuard
from src.cplugs.save.vault.chunks import BlobStore
from src.cplugs.save.vault.identity import Identity
from src.cplugs.save.vault.ingest import Pacer, Partial, SliceExpired, SourceError, ingest_file
from src.cplugs.save.vault.manifest import FileEntry, Manifest, ManifestStore, SoleCopyError  # noqa: F401
from src.cplugs.sdk.blob_codec import BlobCorrupt, BlobMissing

logger = structlog.get_logger()

STATUS_WRITTEN = "written"
STATUS_UNCHANGED = "unchanged"
STATUS_NO_FILES = "no_files"
STATUS_FAILED = "failed"
STATUS_PARTIAL = "partial"

_locks: Dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def unit_lock(unit: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(unit, threading.Lock())


@dataclass(frozen=True)
class CaptureOutcome:

    status: str
    unit: str
    point_id: str = ""
    raw_bytes: int = 0
    new_chunks: int = 0
    failures: Tuple[str, ...] = ()
    damaged: int = 0
    detail: str = ""
    read_signatures: Mapping[str, Tuple[int, int]] = field(default_factory=dict)


def signature(files: Sequence[FileEntry]) -> Tuple[Tuple[str, str, str], ...]:
    return tuple(sorted((f.home, f.rel, f.chain_sha()) for f in files))


class Vault:

    def __init__(self, root: Path, *, codec: Optional[str] = None, clock=time.time,
                 on_change: Optional[Callable[[], None]] = None) -> None:
        self.root = Path(root)
        self._on_change = on_change
        self.blobs = BlobStore(self.root, codec)
        self.manifests = ManifestStore(self.root)
        self.guard = CaptureGuard()
        self.partials: Dict[str, Partial] = {}
        self._clock = clock

    def changed(self) -> None:
        if self._on_change is not None:
            self._on_change()

    def _stamp(self, now: Optional[datetime]) -> datetime:
        return now or datetime.fromtimestamp(self._clock(), timezone.utc)

    def _publish(self, unit: str, plan_kind: str, family: str, conversation_id: Optional[str], encoded: Optional[str],
                 files: List[FileEntry], prior: Optional[Manifest], identity: Identity, reason: str, now: datetime,
                 legacy_key: Optional[str] = None) -> Manifest:
        def pick(new, old):
            return new if new else old

        old = prior
        stamp = self.manifests.next_stamp(unit, now)
        manifest = Manifest(
            unit=unit, point_id=self.manifests.new_point_id(unit, reason, stamp), reason=reason,
            created_epoch=stamp.timestamp(), created_at=stamp.isoformat(), kind=plan_kind, family=family,
            conversation_id=conversation_id, session_uuid=pick(identity.session_uuid, old.session_uuid if old else None),
            project_uid=pick(identity.project_uid, old.project_uid if old else None),
            project_name=pick(identity.project_name, old.project_name if old else None),
            working_dir=pick(identity.working_dir, old.working_dir if old else None),
            encoded_folder=pick(encoded, old.encoded_folder if old else None),
            wrapper=pick(identity.wrapper, old.wrapper if old else None), title=pick(identity.title, old.title if old else None),
            legacy_key=legacy_key, files=sorted(files, key=lambda f: (f.home, f.rel)))
        self.blobs.sync_dirs()
        self.manifests.write(manifest)
        self.changed()
        return manifest

    def _supersedes(self, unit: str, prior: Optional[Manifest], *, conversation: bool = False) -> bool:
        if prior is None:
            return False
        if conversation:
            return (not self.manifests.is_pinned(unit, prior.point_id) and not self.manifests.is_kept(unit, prior.point_id)
                    and retention.may_replace(self, unit, prior))
        if not retention.read_state(self.root).get("over_cap"):
            return False
        return (prior.reason in K.ROTATING_REASONS and not self.manifests.is_pinned(unit, prior.point_id)
                and not self.manifests.is_kept(unit, prior.point_id))

    def _ingest_plan(self, plan: units.UnitPlan, prior_files: Dict[Tuple[str, str], FileEntry],
                     pace: Optional[Pacer]) -> Tuple[List[FileEntry], List[str], bool]:
        entries: List[FileEntry] = []
        failures: List[str] = []
        main_failed = False
        for planned in plan.files:
            try:
                entries.append(ingest_file(self.blobs, planned.path, role=planned.role, home=planned.home, rel=planned.rel,
                                           prior=prior_files.get((planned.home, planned.rel)), pace=pace, parked=self.partials))
            except FileNotFoundError:
                continue
            except SourceError as exc:
                failures.append(f"{planned.rel}: {exc}")
                main_failed = main_failed or planned.role in K.MAIN_ROLES
        return entries, failures, main_failed

    def _forget_progress(self, plan: units.UnitPlan) -> None:
        for planned in plan.files:
            self.partials.pop(str(planned.path), None)

    def _rewritten(self, prior_files: Dict[Tuple[str, str], FileEntry], entries: Sequence[FileEntry]) -> bool:
        for entry in entries:
            old = prior_files.get((entry.home, entry.rel))
            if old is not None and entry.role in K.MAIN_ROLES and (not entry.extends(old) or not self._tail_extends(old, entry)):
                return True
        return False

    def _tail_extends(self, old: FileEntry, new: FileEntry) -> bool:
        if not old.chunks:
            return True
        index = len(old.chunks) - 1
        if index >= len(new.chunks):
            return False
        if new.chunks[index].sha256 == old.chunks[index].sha256:
            return True
        try:
            return self.blobs.get(new.chunks[index]).startswith(self.blobs.get(old.chunks[index]))
        except (BlobMissing, BlobCorrupt):
            return False

    def _chunk_missing(self, entries: Sequence[FileEntry], seed_files: Dict[Tuple[str, str], FileEntry]) -> bool:
        return any(not self.blobs.on_disk(c.sha256) for f in entries if seed_files.get((f.home, f.rel)) is not f for c in f.chunks)

    def capture(self, plan: units.UnitPlan, identity: Identity, reason: str, *, pace: Optional[Pacer] = None,
                now: Optional[datetime] = None, legacy_key: Optional[str] = None) -> CaptureOutcome:
        unit = plan.unit
        with self.guard.capturing():
            self.blobs.revalidate()
            seed = self.manifests.newest(unit)
            seed_files = {(f.home, f.rel): f for f in (seed.files if seed else [])}
            before = self.blobs.new_blobs
            try:
                entries, failures, main_failed = self._ingest_plan(plan, seed_files, pace)
            except SliceExpired as exc:
                return CaptureOutcome(STATUS_PARTIAL, unit, detail=str(exc))
            except BaseException:
                self._forget_progress(plan)
                raise
            self._forget_progress(plan)
            with unit_lock(unit):
                prior = self.manifests.newest(unit)
                prior_files = {(f.home, f.rel): f for f in (prior.files if prior else [])}
                got = {(f.home, f.rel) for f in entries}
                carried = [f for key, f in prior_files.items() if key not in got]
                files = entries + carried
                if not files:
                    return CaptureOutcome(STATUS_FAILED if failures else STATUS_NO_FILES, unit, failures=tuple(failures))
                if main_failed:
                    return CaptureOutcome(STATUS_FAILED, unit, failures=tuple(failures), detail="the main file could not be read")
                damaged = sum(1 for f in carried for c in f.chunks if not self.blobs.has(c.sha256))
                if prior is not None and signature(files) == signature(prior.files):
                    seen = {f.source_path: (f.size_seen, f.mtime_ns) for f in entries}
                    return CaptureOutcome(STATUS_UNCHANGED, unit, prior.point_id, prior.raw_bytes(), 0, tuple(failures), damaged,
                                          read_signatures=seen)
                if self._chunk_missing(entries, seed_files):
                    return CaptureOutcome(STATUS_FAILED, unit, failures=tuple(failures), detail="a chunk is missing after it was written")
                if prior is not None and self._rewritten(prior_files, entries):
                    self.manifests.set_kept(unit, prior.point_id)
                    logger.warning("vault_conversation_rewritten", unit=unit, kept=prior.point_id)
                supersede = self._supersedes(unit, prior, conversation=plan.kind == units.KIND_CONVERSATION)
                main = next((f for f in files if f.role in K.MAIN_ROLES), None)
                wd = identity.working_dir or units.peek_working_dir(Path(main.source_path) if main else None)
                manifest = self._publish(unit, plan.kind, plan.family, plan.conversation_id, plan.encoded_folder, files, prior,
                                         replace(identity, working_dir=wd), reason, self._stamp(now), legacy_key)
                if supersede and prior is not None:
                    self.manifests.delete(unit, prior.point_id)
                return CaptureOutcome(STATUS_WRITTEN, unit, manifest.point_id, manifest.raw_bytes(), self.blobs.new_blobs - before,
                                      tuple(failures), damaged)

    def capture_side_databases(self, state_dir: Path, databases: Sequence[Tuple[str, Path]], *, pace: Optional[Pacer] = None,
                               now: Optional[datetime] = None) -> CaptureOutcome:
        unit = K.SIDE_DB_UNIT
        with self.guard.capturing(), unit_lock(unit):
            self.blobs.revalidate()
            prior = self.manifests.newest(unit)
            before = self.blobs.new_blobs
            entries = sidedb.ingest_databases(self.blobs, self.root / ".staging" / "side", Path(state_dir), databases, pace)
            prior_files = {(f.home, f.rel): f for f in (prior.files if prior else [])}
            got = {(f.home, f.rel) for f in entries}
            files = entries + [f for key, f in prior_files.items() if key not in got]
            if not files:
                return CaptureOutcome(STATUS_NO_FILES, unit)
            if prior is not None and signature(files) == signature(prior.files):
                return CaptureOutcome(STATUS_UNCHANGED, unit, prior.point_id, prior.raw_bytes())
            supersede = self._supersedes(unit, prior)
            manifest = self._publish(unit, units.KIND_SIDE_DBS, units.FAMILY_CLAUDE, None, None, files, prior, Identity(),
                                     K.REASON_FOLLOW, self._stamp(now))
            if supersede and prior is not None:
                self.manifests.delete(unit, prior.point_id)
            return CaptureOutcome(STATUS_WRITTEN, unit, manifest.point_id, manifest.raw_bytes(), self.blobs.new_blobs - before)

    def capture_folder(self, unit: str, root: Path, *, pace: Optional[Pacer] = None, now: Optional[datetime] = None) -> CaptureOutcome:
        unreadable: List[str] = []
        try:
            plan = folders.plan_folder(unit, Path(root), self.root, unreadable)
        except folders.FolderRefused as exc:
            logger.error("vault_folder_unit_refused", unit=unit, root=str(root), error=str(exc))
            return CaptureOutcome(STATUS_FAILED, unit, detail=str(exc))
        if plan is None:
            return CaptureOutcome(STATUS_NO_FILES, unit, detail=f"{root} is not there")
        with self.guard.capturing():
            self.blobs.revalidate()
            seed = self.manifests.newest(unit)
            seed_files = {(f.home, f.rel): f for f in (seed.files if seed else [])}
            before = self.blobs.new_blobs
            entries: List[FileEntry] = []
            failures: List[str] = []
            failed: set = set()
            try:
                for planned in plan.files:
                    key = (planned.home, planned.rel)
                    try:
                        entries.append(ingest_file(self.blobs, planned.path, role=planned.role, home=planned.home, rel=planned.rel,
                                                   prior=seed_files.get(key), pace=pace, parked=self.partials))
                    except FileNotFoundError:
                        continue
                    except SourceError as exc:
                        failures.append(f"{planned.rel}: {exc}")
                        failed.add(key)
            except SliceExpired as exc:
                return CaptureOutcome(STATUS_PARTIAL, unit, detail=str(exc))
            except BaseException:
                self._forget_progress(plan)
                raise
            self._forget_progress(plan)
            with unit_lock(unit):
                prior = self.manifests.newest(unit)
                prior_files = {(f.home, f.rel): f for f in (prior.files if prior else [])}
                got = {(f.home, f.rel) for f in entries}
                hidden = tuple(os.path.join(path, "") for path in unreadable)
                carried = [f for key, f in prior_files.items()
                           if key not in got and (key in failed or (f.source_path and f.source_path.startswith(hidden)))]
                files = entries + carried
                if not files:
                    return CaptureOutcome(STATUS_FAILED if failures else STATUS_NO_FILES, unit, failures=tuple(failures))
                if prior is not None and signature(files) == signature(prior.files):
                    return CaptureOutcome(STATUS_UNCHANGED, unit, prior.point_id, prior.raw_bytes(), 0, tuple(failures))
                if self._chunk_missing(entries, seed_files):
                    return CaptureOutcome(STATUS_FAILED, unit, failures=tuple(failures), detail="a chunk is missing after it was written")
                kept = {(f.home, f.rel) for f in files}
                gone = [key[1] for key in prior_files if key not in kept]
                if prior is not None and gone:
                    self.manifests.set_kept(unit, prior.point_id)
                    logger.info("vault_folder_files_deleted", unit=unit, kept=prior.point_id, deleted=len(gone), first=gone[0])
                supersede = self._supersedes(unit, prior)
                manifest = self._publish(unit, K.KIND_FOLDER, K.FAMILY_PLUGIN, None, None, files, prior,
                                         Identity(working_dir=str(root)), K.REASON_FOLLOW if prior else K.REASON_BACKFILL, self._stamp(now))
                if supersede and prior is not None:
                    self.manifests.delete(unit, prior.point_id)
                return CaptureOutcome(STATUS_WRITTEN, unit, manifest.point_id, manifest.raw_bytes(), self.blobs.new_blobs - before,
                                      tuple(failures))
