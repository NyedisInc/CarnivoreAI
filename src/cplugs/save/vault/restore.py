"""Restore: a manifest back to byte-identical files.

EVERY FILE IS RE-HASHED as it is written (each chunk is checked against its name, then the whole against the manifest's
length and sha256: the hash of the bytes for an old entry, the hash over the chunk list for a newer one), so a damaged vault
produces an error, never a quiet wrong file. A restored file gets the permission bits and the modification time the source
had (an entry from before they were recorded is restored owner-only). NEVER OVERWRITE: a destination that
exists with the same bytes is reported ``already_present``; one that differs is a conflict, and a restore with any
conflict writes nothing at all unless the caller asks to skip them. A file appears only whole (temp file, fsync, a hard
link that fails if the name exists; on a volume that cannot hard link, a rename after a last check: the shared placer,
``src/core/blobcodec/place.py``).

:func:`restore_to_root` puts ``<target>/<home>/<rel>`` (what the export and import steps use); :func:`restore_to_homes`
puts each file back into the Claude, Codex or state folder it came from (the restore route uses it).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

import structlog

from src.cplugs.save.engine import layout
from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault.chunks import BlobStore
from src.cplugs.save.vault.manifest import FileEntry, Manifest
from src.cplugs.sdk import transcript_files as tf
from src.cplugs.sdk.blob_codec import BlobCorrupt, BlobMissing, ChunkReader, PlaceConflict, chain_sha, place_no_clobber, sha256_file

logger = structlog.get_logger()

STATUS_WRITTEN = "written"
STATUS_ALREADY_PRESENT = "already_present"


class RestoreError(RuntimeError):
    pass


class RestoreConflict(RestoreError):

    def __init__(self, paths: List[Path]) -> None:
        self.paths = list(paths)
        super().__init__(f"{len(paths)} file(s) already exist with different content, first {paths[0] if paths else '?'}")


@dataclass
class RestoreResult:

    written: List[Path] = field(default_factory=list)
    already_present: List[Path] = field(default_factory=list)
    skipped_conflicts: List[Path] = field(default_factory=list)
    bytes: int = 0


def file_matches(path: Path, entry: FileEntry) -> bool:
    try:
        if os.path.getsize(path) != entry.length:
            return False
        if entry.sha_kind == K.SHA_CONTENT:
            return sha256_file(path) == entry.sha256
        with open(path, "rb") as handle:
            reader = ChunkReader(handle, entry.length, entry.role in K.LINE_ROLES, keep_tail=True)
            seen = []
            for raw in reader:
                seen.append(hashlib.sha256(raw).hexdigest())
                if len(seen) > len(entry.chunks) or seen[-1] != entry.chunks[len(seen) - 1].sha256:
                    return False
            return len(seen) == len(entry.chunks) and not reader.short
    except OSError:
        return False


def read_entry(blobs: BlobStore, entry: FileEntry) -> Iterable[bytes]:
    for chunk in entry.chunks:
        try:
            yield blobs.get(chunk)
        except (BlobMissing, BlobCorrupt) as exc:
            raise RestoreError(f"{entry.rel}: {exc}") from exc


def verify_entry(blobs: BlobStore, entry: FileEntry) -> None:
    digest, total = hashlib.sha256(), 0
    for raw in read_entry(blobs, entry):
        digest.update(raw)
        total += len(raw)
    whole = digest.hexdigest() if entry.sha_kind == K.SHA_CONTENT else chain_sha(entry.chunks)
    if total != entry.length or whole != entry.sha256:
        raise RestoreError(f"{entry.rel}: the stored chunks do not add up to the recorded file")


def verify_manifest(blobs: BlobStore, manifest: Manifest) -> int:
    for entry in manifest.files:
        verify_entry(blobs, entry)
    return manifest.raw_bytes()


def _write_entry(blobs: BlobStore, entry: FileEntry, dest: Path) -> None:
    tf.assert_test_write_allowed(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_name(layout.temp_name(".vault-restore-"))
    digest, total = hashlib.sha256(), 0
    try:
        with open(temp, "xb") as out:
            for raw in read_entry(blobs, entry):
                digest.update(raw)
                total += len(raw)
                out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        whole = digest.hexdigest() if entry.sha_kind == K.SHA_CONTENT else chain_sha(entry.chunks)
        if total != entry.length or whole != entry.sha256:
            raise RestoreError(f"{entry.rel}: the restored bytes do not match the manifest")
        _apply_metadata(temp, entry)
        try:
            place_no_clobber(temp, dest)
        except PlaceConflict:
            raise RestoreConflict([dest]) from None
    finally:
        temp.unlink(missing_ok=True)


def _apply_metadata(temp: Path, entry: FileEntry) -> None:
    try:
        os.chmod(temp, (entry.mode & 0o777) or K.DEFAULT_RESTORE_MODE)
        if entry.mtime_ns > 0:
            os.utime(temp, ns=(entry.mtime_ns, entry.mtime_ns))
    except OSError as exc:
        logger.debug("vault_restore_metadata_unsupported", rel=entry.rel, error=str(exc))


def restore_manifest(blobs: BlobStore, manifest: Manifest, destination: Callable[[FileEntry], Path], *,
                     skip_conflicts: bool = False, only_roles: Optional[Iterable[str]] = None) -> RestoreResult:
    roles = set(only_roles) if only_roles is not None else None
    plan = [(e, destination(e)) for e in manifest.files if roles is None or e.role in roles]
    conflicts = [d for e, d in plan if d.exists() and not file_matches(d, e)]
    if conflicts and not skip_conflicts:
        raise RestoreConflict(conflicts)
    result = RestoreResult()
    for entry, dest in plan:
        if dest in conflicts:
            result.skipped_conflicts.append(dest)
        elif dest.exists():
            result.already_present.append(dest)
        else:
            _write_entry(blobs, entry, dest)
            result.written.append(dest)
            result.bytes += entry.length
    logger.info("vault_restored", unit=manifest.unit, point_id=manifest.point_id, written=len(result.written),
                already_present=len(result.already_present))
    return result


def restore_to_root(blobs: BlobStore, manifest: Manifest, target_root: Path, **kwargs) -> RestoreResult:
    return restore_manifest(blobs, manifest, lambda e: Path(target_root) / e.home / e.rel, **kwargs)


def restore_to_homes(blobs: BlobStore, manifest: Manifest, homes: Dict[str, Path], **kwargs) -> RestoreResult:
    """Restore each file into its own home folder. Inputs: homes {'claude': ~/.claude, 'codex': ~/.codex, 'state': state dir}, optionally with a key such as
    'claude/projects' that sends that top folder somewhere else (a Claude profile whose projects folder is shared).

    Raises: RestoreError - a home is missing from ``homes`` or a destination resolves outside it.
    """
    def destination(entry: FileEntry) -> Path:
        first, _, rest = entry.rel.partition("/")
        specific = homes.get(f"{entry.home}/{first}")
        home, inner = (specific, rest) if specific is not None and rest else (homes.get(entry.home), entry.rel)
        if home is None:
            raise RestoreError(f"no folder given for home {entry.home!r}")
        dest = Path(home) / inner
        real_home, real_parent = Path(os.path.realpath(home)), Path(os.path.realpath(dest.parent))
        if real_parent != real_home and real_home not in real_parent.parents:
            raise RestoreError(f"refusing to write outside {home}: {dest}")
        return dest

    return restore_manifest(blobs, manifest, destination, **kwargs)
