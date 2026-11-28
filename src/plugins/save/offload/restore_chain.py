
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import structlog

from src.plugins.save.offload import constants as C, homes as homes_mod, push
from src.plugins.save.offload.ledger import Entry, Ledger, LedgerUnreadable
from src.plugins.save.vault import constants as K
from src.plugins.save.vault import restore
from src.plugins.save.vault.manifest import FileEntry, Manifest, ManifestError, check_unit
from src.plugins.save.vault.store import Vault
from src.plugins.sdk import transcript_files as tf
from src.plugins.sdk.blob_codec import PlaceConflict, place_no_clobber

logger = structlog.get_logger()

STATUS_WRITTEN = restore.STATUS_WRITTEN
STATUS_ALREADY_PRESENT = restore.STATUS_ALREADY_PRESENT
STATUS_DISK_NEWER = "disk_newer"
STATUS_CONFLICT = "conflict"
STATUS_FAILED = "failed"
STATUS_NO_POINT = "no_vault_point"
STATUS_WOULD_WRITE = "would_write"
STATUS_PRESENT_ELSEWHERE = "present_elsewhere"


@dataclass
class ConversationRestore:

    conversation_id: str
    status: str
    point_id: Optional[str] = None
    written: int = 0
    already_present: int = 0
    disk_newer: int = 0
    conflicts: List[str] = field(default_factory=list)
    bytes: int = 0
    detail: str = ""
    notes: List[str] = field(default_factory=list)
    path: str = ""


class FolderUnsearchable(restore.RestoreError):

    def __init__(self, path: Path, message: str) -> None:
        super().__init__(message)
        self.path = path


def classify(entry: FileEntry, dest: Path) -> str:
    if not os.path.lexists(dest):
        return STATUS_WRITTEN
    if not dest.is_file() or dest.is_symlink():
        return STATUS_CONFLICT
    if restore.file_matches(dest, entry):
        return STATUS_ALREADY_PRESENT
    return STATUS_DISK_NEWER if restore.starts_with_entry(dest, entry) else STATUS_CONFLICT


def _main_first(entries: Iterable[FileEntry]) -> List[FileEntry]:
    return sorted(entries, key=lambda e: 0 if e.role in (K.ROLE_TRANSCRIPT, K.ROLE_CODEX_ROLLOUT) else 1)


def _summary(base: ConversationRestore, plan: Dict[str, List[Path]]) -> ConversationRestore:
    base.already_present = len(plan.get(STATUS_ALREADY_PRESENT, []))
    base.disk_newer = len(plan.get(STATUS_DISK_NEWER, []))
    base.conflicts = [str(p) for p in plan.get(STATUS_CONFLICT, [])]
    return base


def restore_conversation(vault: Vault, conversation_id: str, homes: Dict[str, Path], *, dry_run: bool = False,
                         ledger: Optional[Ledger] = None, folder: Optional[str] = None) -> ConversationRestore:
    check_unit(conversation_id)
    probe = ConversationRestore(conversation_id, STATUS_FAILED)
    try:
        offload = _offload_of(ledger, conversation_id, probe, dry_run)
    except LedgerUnreadable as exc:
        probe.detail = f"ledger unreadable: it cannot be told whether this conversation is offloaded, so nothing was written ({str(exc)[:200]})"
        return probe
    out = _restore_from_point(vault, conversation_id, homes, offload, probe, dry_run=dry_run, folder=folder)
    if offload is not None and not dry_run and out.status not in C.RESTORE_OK_STATUSES:
        _keep(offload, out)
    return out


def _restore_from_point(vault: Vault, conversation_id: str, homes: Dict[str, Path], offload: Optional["Offload"], probe: ConversationRestore, *,
                        dry_run: bool, folder: Optional[str]) -> ConversationRestore:
    try:
        point = _point_of(vault, conversation_id, offload)
    except ManifestError as exc:
        logger.error("offload_restore_point_unreadable", conversation_id=conversation_id, error=str(exc)[:300])
        probe.detail = f"the point this conversation was offloaded against cannot be read: {str(exc)[:200]}"
        return probe
    if point is None:
        return ConversationRestore(conversation_id, STATUS_NO_POINT, detail="the vault holds no point of this conversation", notes=probe.notes)
    out = ConversationRestore(conversation_id, STATUS_FAILED, point.point_id, notes=probe.notes)
    if point.family != "claude" or point.main() is None:
        out.detail = "only a Claude conversation with a transcript can be restored here"
        return out
    try:
        destination = homes_mod.point_destination(homes, point, folder)
        if _stops_before_writing(homes, point, destination, out):
            return out
        _note_folder(out, point, homes, destination)
        plan: Dict[str, List[Path]] = {}
        todo: List[FileEntry] = []
        for entry in point.files:
            dest = destination(entry)
            state = classify(entry, dest)
            plan.setdefault(state, []).append(dest)
            if state == STATUS_WRITTEN:
                todo.append(entry)
        _summary(out, plan)
        if plan.get(STATUS_CONFLICT):
            out.status, out.detail = STATUS_CONFLICT, f"a different file is already at {out.conflicts[0]}; nothing of this conversation was written"[:300]
            return out
        if dry_run:
            out.status = STATUS_WOULD_WRITE if todo else _settled(out)
            out.written = len(todo)
            return out
        if offload is not None and todo:
            offload.ledger.update(conversation_id, state=C.STATE_RESTORING)
        _write(vault, point, todo, destination, out, offload)
        if offload is not None and out.status in C.RESTORE_OK_STATUSES:
            _settle(offload, point, destination, out)
    except (restore.RestoreError, OSError, ManifestError, LedgerUnreadable) as exc:
        logger.warning("offload_restore_failed", conversation_id=conversation_id, point_id=point.point_id, error_type=type(exc).__name__, error=str(exc)[:300])
        out.status, out.detail = STATUS_FAILED, str(exc)[:300]
    return out


def _point_of(vault: Vault, conversation_id: str, offload: Optional["Offload"]) -> Optional[Manifest]:
    if offload is not None:
        return vault.manifests.read(offload.entry.unit, offload.entry.point_id)
    return vault.manifests.newest(conversation_id)


def _stops_before_writing(homes: Dict[str, Path], point: Manifest, destination: Callable[[FileEntry], Path], out: ConversationRestore) -> bool:
    main = point.main()
    if main is None:
        return False
    target, recorded = destination(main), restore.homes_destination(homes)(main)
    if os.path.lexists(target):
        return False
    try:
        found = recorded if recorded != target and os.path.lexists(recorded) else _found_in_corpus(_corpus_roots(homes), point.unit, target)
    except FolderUnsearchable as exc:
        out.status, out.path = STATUS_FAILED, str(exc.path)
        out.detail = f"{exc.path} could not be read, so it cannot be told whether this conversation is already on disk there; nothing was written ({exc})"[:300]
        logger.warning("offload_restore_folder_unsearchable", conversation_id=point.unit, path=str(exc.path), error=str(exc)[:200])
        return True
    if found is None:
        return False
    out.status, out.path = STATUS_PRESENT_ELSEWHERE, str(found)
    out.notes.append(f"present_elsewhere: {found} ({classify(main, found)})")
    out.detail = f"this conversation is already on disk at {found}; a restore never moves it, so nothing was written"[:300]
    logger.info("offload_restore_present_elsewhere", conversation_id=point.unit, path=str(found))
    return True


def _projects_root(homes: Dict[str, Path]) -> Path:
    projects = homes.get(homes_mod.HOME_CLAUDE_PROJECTS)
    return Path(projects) if projects is not None else Path(homes[homes_mod.HOME_CLAUDE]) / "projects"


def _corpus_roots(homes: Dict[str, Path]) -> Tuple[Path, ...]:
    return tf.projects_roots_with_profiles(_projects_root(homes))


def _found_in_corpus(roots: Sequence[Path], conversation_id: str, target: Path) -> Optional[Path]:
    for root in roots:
        found = tf.family_conversation_presence("claude", conversation_id, corpus_root=root)
        if found.outcome == tf.CONVERSATION_PRESENT and found.path is not None:
            if Path(found.path) != target:
                return Path(found.path)
            continue
        if found.missing and found.unreadable:
            raise FolderUnsearchable(found.unreadable_folder or root, "a project folder could not be read")
        if not found.missing and root.exists():
            raise FolderUnsearchable(root, found.detail or "the projects folder could not be listed")
    return None


def _note_folder(out: ConversationRestore, point: Manifest, homes: Dict[str, Path], destination: Callable[[FileEntry], Path]) -> None:
    main = point.main()
    if main is not None and destination(main) != restore.homes_destination(homes)(main):
        out.notes.append(f"restored_into: {destination(main).parent}")


def _settled(out: ConversationRestore) -> str:
    return STATUS_DISK_NEWER if out.disk_newer else STATUS_ALREADY_PRESENT


@dataclass(frozen=True)
class Offload:

    ledger: Ledger
    entry: Entry

    def held_path(self, file: FileEntry) -> Optional[Path]:
        if not self.entry.holding_dir:
            return None
        held = Path(self.entry.holding_dir) / file.home / file.rel
        return held if held.is_file() and not held.is_symlink() else None


def _offload_of(ledger: Optional[Ledger], conversation_id: str, out: ConversationRestore, dry_run: bool = False) -> Optional[Offload]:
    if ledger is None:
        return None
    try:
        entry = ledger.get(conversation_id)
    except LedgerUnreadable as exc:
        logger.error("offload_ledger_unreadable_for_restore", conversation_id=conversation_id, dry_run=dry_run, error=str(exc)[:200])
        if not dry_run:
            raise
        out.notes.append(f"ledger_unreadable: {exc}")
        return None
    return Offload(ledger, entry) if entry is not None else None


def _place_held(held: Path, dest: Path) -> None:
    try:
        place_no_clobber(held, dest, strict=True)
    except PlaceConflict:
        raise restore.RestoreConflict([dest]) from None


def _place_one(vault: Vault, point: Manifest, entry: FileEntry, dest: Path, out: ConversationRestore, offload: Optional[Offload] = None) -> bool:
    held = offload.held_path(entry) if offload is not None else None
    try:
        if held is not None and restore.file_matches(held, entry):
            dest.parent.mkdir(parents=True, exist_ok=True)
            _place_held(held, dest)
        else:
            restore.write_entry(vault.blobs, entry, dest, imported=point.reason == K.REASON_IMPORT, strict=True)
    except restore.RestoreConflict:
        late = classify(entry, dest)
        if late == STATUS_ALREADY_PRESENT:
            out.already_present += 1
        elif late == STATUS_DISK_NEWER:
            out.disk_newer += 1
        else:
            out.conflicts.append(str(dest))
            out.detail = "a different file appeared while restoring; the files placed before it stay"
            return False
        return True
    if restore.file_matches(dest, entry):
        pass
    elif restore.starts_with_entry(dest, entry):
        out.notes.append(f"grew_during_restore: {dest}")
    else:
        raise restore.RestoreError(f"{dest} does not match its point after it was written")
    out.written += 1
    out.bytes += entry.length
    return True


def _write(vault: Vault, point: Manifest, todo: List[FileEntry], destination: Callable[[FileEntry], Path], out: ConversationRestore,
           offload: Optional[Offload] = None) -> None:
    if not todo:
        out.status = _settled(out)
        return
    try:
        for entry in todo:
            held = offload.held_path(entry) if offload is not None else None
            if held is None or not restore.file_matches(held, entry):
                restore.verify_entry(vault.blobs, entry)
    except restore.RestoreError as exc:
        out.status, out.detail = STATUS_FAILED, f"{exc}; nothing was written"
        return
    try:
        for entry in _main_first(todo):
            if not _place_one(vault, point, entry, destination(entry), out, offload):
                out.status = STATUS_CONFLICT
                return
    except (restore.RestoreError, OSError) as exc:
        logger.warning("offload_restore_failed", conversation_id=point.unit, point_id=point.point_id, error_type=type(exc).__name__, error=str(exc)[:300])
        out.status = STATUS_FAILED
        out.detail = f"{str(exc)[:300]}; {out.written} of {len(todo)} files were written before it stopped"
        return
    out.status = STATUS_WRITTEN if out.written else _settled(out)
    logger.info("offload_restored", conversation_id=point.unit, point_id=point.point_id, written=out.written, bytes=out.bytes)


def _prune_empty(root: Path) -> None:
    if not root.is_dir():
        return
    for folder in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            folder.rmdir()
        except OSError:
            continue
    try:
        root.rmdir()
    except OSError:
        pass


_COMPARE_PIECE: int = 1 << 20


def begins_with_file(path: Path, prefix: Path) -> bool:
    try:
        if not path.is_file() or path.is_symlink() or os.path.getsize(path) < os.path.getsize(prefix):
            return False
        with open(path, "rb") as whole, open(prefix, "rb") as head:
            while True:
                want = head.read(_COMPARE_PIECE)
                if not want:
                    return True
                if whole.read(len(want)) != want:
                    return False
    except OSError:
        return False


def _keep(offload: Offload, out: ConversationRestore) -> None:
    state = C.STATE_CONFLICT if out.status in (STATUS_CONFLICT, STATUS_PRESENT_ELSEWHERE) else C.STATE_FAILED
    path = out.path or (out.conflicts[0] if out.conflicts else "")
    try:
        offload.ledger.update(offload.entry.conversation_id, state=state, error=(out.detail or out.status)[:300], error_code=out.status, error_path=path)
    except (LedgerUnreadable, OSError) as exc:
        logger.error("offload_restore_reason_not_recorded", conversation_id=offload.entry.conversation_id, status=out.status, error_type=type(exc).__name__, error=str(exc)[:200])
        out.notes.append(f"ledger_not_updated: {str(exc)[:200]}")


def _settle(offload: Offload, point: Manifest, destination: Callable[[FileEntry], Path], out: ConversationRestore) -> None:
    conv = offload.entry.conversation_id
    left = []
    for file in point.files:
        held = offload.held_path(file)
        if held is None:
            continue
        dest = destination(file)
        if begins_with_file(dest, held):
            held.unlink()
        else:
            left.append(str(held))
    if left:
        offload.ledger.update(conv, state=C.STATE_FAILED, error=f"{len(left)} held file(s) differ from what is on disk and were left in holding: {left[0]}",
                              error_code=STATUS_FAILED, error_path=left[0])
        return
    if offload.entry.holding_dir:
        _prune_empty(Path(offload.entry.holding_dir))
    offload.ledger.remove(conv)


@push.coalescing
def restore_conversations(vault: Vault, conversation_ids: Iterable[str], homes: Dict[str, Path], *, dry_run: bool = False,
                          ledger: Optional[Ledger] = None, folders: Optional[Dict[str, str]] = None) -> List[ConversationRestore]:
    return [restore_conversation(vault, c, homes, dry_run=dry_run, ledger=ledger, folder=(folders or {}).get(c)) for c in dict.fromkeys(conversation_ids)]
