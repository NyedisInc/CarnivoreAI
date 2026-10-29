"""
THE RULES, all from the vault's own model (``manifest.py``, ``store.py``, ``retention.py``); no schema change:
- ADD ONLY. A call writes new chunks (``BlobStore.put``: the chunk is re-hashed, one already stored is not written again, which is the
  dedupe by chunk hash) and new manifests. It never edits, replaces or removes an existing manifest or blob.
- A POINT IS WRITTEN LAST. Every file is streamed through the vault's own chunker, the reassembled bytes are checked against the sha256 the
  sender recorded, ``sync_dirs`` makes the blob folders durable, and only then is the manifest published (temp file, fsync, rename), under
  the shared capture guard (a blob collection cannot run between the chunks and the manifest). A failure before that leaves unreferenced
  chunks (the vault's own collector removes them after its grace) and no point.
- THE SAME POINT TWICE IS ONE POINT. A point id already in the unit whose files have the same signature is ``present`` (nothing written). The same id
  with different files gets a new id; the sender's id is never reused for different bytes.
- A TAGGED POINT carries its tags (step 7, ``FallbackPoint.tags``) in a ``<point>.tags`` sidecar written before the manifest and removed with it by ``remove_adopted``.
- AN ADOPTED POINT IS NEVER PRUNED. Its ``.keep`` marker is made durable before the manifest is published, so retention never thins or
  replaces it and it does not count as history: it is never dropped sooner than the point it came from.
- THE UNDO LOG COMES FIRST. ``log`` receives the entry (unit, point id, the hash of the manifest bytes, the chunks this call newly wrote)
  before the manifest is published; ``remove_adopted`` removes exactly that.
The caller (the crate import) has already mapped ``rel``, ``working_dir`` and ``encoded_folder`` for a relocated conversation.
"""

from __future__ import annotations

import hashlib
import io
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import structlog

from src.cplugs.save.engine import layout
from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault import digest as digest_mod
from src.cplugs.save.vault import retention
from src.cplugs.save.vault.manifest import HOME_CLAUDE, HOME_CODEX, HOME_FOLDER, FileEntry, Manifest, ManifestError, check_rel, check_unit
from src.cplugs.save.vault.store import Vault, signature, unit_lock
from src.cplugs.sdk.blob_codec import ChunkReader, ChunkRef, IterStream, chain_sha
from src.core.deepsearch.fallback_hook import AdoptedPoint, FallbackPoint

logger = structlog.get_logger()

ADOPTED, PRESENT, REFUSED = "adopted", "present", "refused"
_FAMILIES = ("claude", "codex")
_ROLES = (K.ROLE_TRANSCRIPT, K.ROLE_SUBAGENT, K.ROLE_TOOL_RESULT, K.ROLE_CONVERSATION_OTHER, K.ROLE_FILE_HISTORY, K.ROLE_CODEX_ROLLOUT)
_HOMES = (HOME_CLAUDE, HOME_CODEX)
_FOLDER_FAMILY, _FOLDER_ROLE, _FOLDER_HOMES = K.FAMILY_PLUGIN, K.ROLE_FOLDER_FILE, (HOME_FOLDER,)


class AdoptRefused(ValueError):
    pass


def _check(point: FallbackPoint) -> None:
    try:
        check_unit(point.conversation_id)
        layout.check_point_id(point.point_id)
    except (ManifestError, layout.InvalidIdError) as exc:
        raise AdoptRefused(str(exc)) from exc
    folder = point.kind == K.KIND_FOLDER
    if point.kind not in (K.KIND_CONVERSATION, K.KIND_FOLDER):
        raise AdoptRefused(f"unknown point kind {point.kind!r}")
    if point.family != _FOLDER_FAMILY if folder else point.family not in _FAMILIES:
        raise AdoptRefused(f"unknown family {point.family!r}")
    if folder and not point.working_dir:
        raise AdoptRefused("a folder point names the folder it restores into")
    if not point.files:
        raise AdoptRefused("the point holds no files")
    homes, roles = (_FOLDER_HOMES, (_FOLDER_ROLE,)) if folder else (_HOMES, _ROLES)
    seen: Set[Tuple[str, str]] = set()
    for f in point.files:
        try:
            check_rel(f.rel)
        except ManifestError as exc:
            raise AdoptRefused(str(exc)) from exc
        if f.home not in homes or f.role not in roles or getattr(f, "read", None) is None:
            raise AdoptRefused(f"{f.rel}: not a file a point can hold (home {f.home!r}, role {f.role!r})")
        if (f.home, f.rel) in seen:
            raise AdoptRefused(f"{f.rel}: listed twice")
        seen.add((f.home, f.rel))


def _entry_of(vault: Vault, f: Any, fresh: Set[str]) -> FileEntry:
    line_mode = f.role in K.LINE_ROLES
    reader = ChunkReader(io.BufferedReader(IterStream(f.read())), f.length, line_mode, keep_tail=True)
    refs: List[ChunkRef] = []
    digests: List[Dict[str, Any]] = []
    whole, stored, lines = hashlib.sha256(), 0, 0
    for raw in reader:
        ref, size, new = vault.blobs.put(raw)
        refs.append(ref)
        stored += size
        whole.update(raw)
        lines += raw.count(b"\n") if line_mode else 0
        if new:
            fresh.add(ref.sha256)
        if f.role in K.MAIN_ROLES:
            digests.append(digest_mod.chunk_digest(raw))
    if reader.short or reader.length != f.length or whole.hexdigest() != f.sha256:
        raise AdoptRefused(f"{f.rel}: the bytes are not the {f.length} bytes the sender recorded")
    return FileEntry(role=f.role, home=f.home, rel=f.rel, source_path=f.source_path or "", length=reader.length,
                     sha256=chain_sha(refs), sha_kind=K.SHA_CHAIN, chunks=refs, size_seen=reader.length, mtime_ns=int(f.mtime_ns or 0),
                     torn_bytes=0, lines=lines, stored_bytes=stored, mode=int(f.mode or 0) & 0o777, digests=digests)


def _existing(vault: Vault, unit: str, point_id: str) -> Optional[Manifest]:
    return vault.manifests.read(unit, point_id) if point_id in vault.manifests.point_ids(unit) else None


def _stamp(point: FallbackPoint) -> datetime:
    return datetime.fromtimestamp(point.created_epoch, timezone.utc)


def _manifest_of(point: FallbackPoint, point_id: str, entries: List[FileEntry]) -> Manifest:
    return Manifest(
        unit=point.conversation_id, point_id=point_id, reason=point.reason, created_epoch=point.created_epoch,
        created_at=point.created_at, kind=point.kind, family=point.family,
        conversation_id=point.conversation_id if point.kind == K.KIND_CONVERSATION else None,
        session_uuid=point.session_uuid, project_uid=point.project_uid, project_name=point.project_name,
        working_dir=point.working_dir, encoded_folder=point.encoded_folder, wrapper=point.wrapper, title=point.title,
        files=sorted(entries, key=lambda e: (e.home, e.rel)))


def adopt_point(vault: Vault, point: FallbackPoint, log: Callable[[Dict[str, Any]], None]) -> AdoptedPoint:
    _check(point)
    unit = point.conversation_id
    fresh: Set[str] = set()
    with vault.guard.capturing():
        entries = [_entry_of(vault, f, fresh) for f in point.files]
        with unit_lock(unit):
            held = _existing(vault, unit, point.point_id)
            if held is not None and signature(held.files) == signature(entries):
                return AdoptedPoint(unit, point.point_id, PRESENT, held.point_id)
            taken = set(vault.manifests.point_ids(unit))
            point_id = point.point_id if held is None else layout.new_point_id(
                "".join(c for c in point.reason.lower() if c.isalpha()) or "point", _stamp(point), taken)
            manifest = _manifest_of(point, point_id, entries)
            if any(not vault.blobs.has(c.sha256) for e in entries for c in e.chunks):
                raise AdoptRefused("a chunk is missing after it was written")
            data = vault.manifests.render(manifest)
            log({"op": "vault_point", "unit": unit, "point_id": point_id, "manifest_sha256": hashlib.sha256(data).hexdigest(),
                 "new_chunks": sorted(fresh)})
            vault.manifests.unit_dir(unit).mkdir(parents=True, exist_ok=True)
            vault.manifests.set_kept(unit, point_id)
            try:
                if point.tags:
                    vault.manifests.write_tags(unit, point_id, dict(point.tags))
                vault.blobs.sync_dirs()
                vault.manifests.write(manifest)
            except OSError:
                vault.manifests.keep_path(unit, point_id).unlink(missing_ok=True)
                vault.manifests.tags_path(unit, point_id).unlink(missing_ok=True)
                raise
    vault.changed()
    return AdoptedPoint(unit, point.point_id, ADOPTED, point_id, manifest_sha256=hashlib.sha256(data).hexdigest(),
                        new_chunks=tuple(sorted(fresh)))


def adopt_points(vault: Vault, points: Sequence[FallbackPoint], log: Callable[[Dict[str, Any]], None]) -> List[AdoptedPoint]:
    out: List[AdoptedPoint] = []
    for point in sorted(points, key=lambda p: (p.conversation_id, p.created_epoch)):
        try:
            out.append(adopt_point(vault, point, log))
        except (AdoptRefused, ManifestError) as exc:
            logger.warning("vault_adopt_refused", unit=point.conversation_id, point=point.point_id, error=str(exc)[:200])
            out.append(AdoptedPoint(point.conversation_id, point.point_id, REFUSED, reason=str(exc)[:300]))
    return out


def remove_adopted(vault: Vault, entries: Sequence[Dict[str, Any]]) -> Dict[str, List[str]]:
    report: Dict[str, List[str]] = {"removed": [], "kept": [], "errors": []}
    chunks: Set[str] = set()
    for entry in entries:
        name = f"{entry.get('unit')}/{entry.get('point_id')}"
        try:
            verdict = vault.manifests.remove_adopted(str(entry["unit"]), str(entry["point_id"]), str(entry["manifest_sha256"]))
        except (OSError, ManifestError, KeyError, layout.InvalidIdError) as exc:
            report["errors"].append(f"{name}: {type(exc).__name__}")
            continue
        report["removed" if verdict in ("removed", "absent") else "kept"].append(name)
        if verdict in ("removed", "absent"):
            chunks.update(str(c) for c in entry.get("new_chunks") or [])
    if report["removed"]:
        vault.changed()
    if chunks:
        _drop_chunks(vault, chunks, report)
    return report


def _drop_chunks(vault: Vault, chunks: Set[str], report: Dict[str, List[str]]) -> None:
    with vault.guard.try_exclusive() as held:
        if not held:
            return
        try:
            referenced = retention.referenced_chunks(vault)
        except (ManifestError, OSError) as exc:
            report["errors"].append(f"chunks kept: {type(exc).__name__}")
            return
        for sha in sorted(chunks - referenced):
            found = vault.blobs.find(sha)
            if found is not None:
                found[0].unlink(missing_ok=True)
                try:
                    found[0].parent.rmdir()
                except OSError:
                    pass
