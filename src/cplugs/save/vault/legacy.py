
from __future__ import annotations

import json
import re
import tarfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Callable, Dict, Iterator, List, Optional, Set, Tuple

import structlog

from src.cplugs.save.engine import codec as codec_mod
from src.cplugs.save.engine import layout
from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault import units
from src.cplugs.save.vault.chunks import BlobStore
from src.cplugs.save.vault.identity import Identity, ProjectIndex
from src.cplugs.save.vault.manifest import HOME_CLAUDE, HOME_CODEX, FileEntry, Manifest, ManifestError, check_unit
from src.cplugs.save.vault.store import Vault, signature
from src.cplugs.sdk import transcript_files as tf, vault_sources
from src.cplugs.sdk.blob_codec import ChunkReader, Throttle, chain_sha

logger = structlog.get_logger()

TREE_DIR = "time-machine"
_META = "meta.json"


@dataclass(frozen=True)
class LegacyProgress:

    more: bool = False
    failed: int = 0


@dataclass(frozen=True)
class LegacyPoint:

    key: str
    directory: Path
    meta: Dict[str, Any]


def tree_dir(state_dir: Path) -> Path:
    return Path(state_dir) / TREE_DIR


def iter_points(state_dir: Path) -> Iterator[LegacyPoint]:
    root = tree_dir(state_dir)
    if not root.is_dir():
        return
    for slug in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        for conv in sorted(p for p in slug.iterdir() if p.is_dir() and not p.name.startswith(".")):
            for point in sorted(p for p in conv.iterdir() if p.is_dir() and not p.name.startswith(".")):
                try:
                    meta = json.loads((point / _META).read_text(encoding="utf-8"))
                    if not isinstance(meta, dict) or not isinstance(meta.get("transcript"), dict):
                        raise ValueError("no transcript record")
                except (OSError, ValueError) as exc:
                    logger.warning("vault_legacy_point_unreadable", point=str(point), error=str(exc))
                    continue
                yield LegacyPoint(f"{slug.name}/{conv.name}/{point.name}", point, meta)


def _done_path(vault: Vault) -> Path:
    return vault.root / K.LEGACY_DONE_FILE


def _read_done(vault: Vault) -> Set[str]:
    try:
        return set(json.loads(_done_path(vault).read_text(encoding="utf-8")).get("keys", []))
    except FileNotFoundError:
        return set()
    except (OSError, ValueError, AttributeError) as exc:
        logger.warning("vault_legacy_done_unreadable", error=str(exc))
        return set()


def _write_done(vault: Vault, keys: Set[str]) -> None:
    layout.atomic_write_json(_done_path(vault), {"keys": sorted(keys)})


def _encoded_folder(meta: Dict[str, Any], conv: str) -> str:
    source = Path(str(meta["transcript"].get("source_path") or ""))
    if source.name == f"{conv}.jsonl" and source.parent.name:
        return source.parent.name
    return tf.slugify_project_dir(meta.get("working_dir") or "")


def _chunk_stream(blobs: BlobStore, stream: BinaryIO, limit: int, line_mode: bool, role: str, home: str, rel: str,
                  source_path: str, pace: Optional[Throttle]) -> Tuple[FileEntry, str]:
    import hashlib

    digest, refs, stored = hashlib.sha256(), [], 0
    reader = ChunkReader(stream, limit, line_mode, keep_tail=True)
    mark = time.monotonic()
    for raw in reader:
        ref, size, _new = blobs.put(raw)
        digest.update(raw)
        refs.append(ref)
        stored += size
        if pace is not None:
            pace.rest(time.monotonic() - mark)
        mark = time.monotonic()
    entry = FileEntry(role=role, home=home, rel=rel, source_path=source_path, length=reader.length, sha256=chain_sha(refs),
                      sha_kind=K.SHA_CHAIN, chunks=refs, size_seen=-1, mtime_ns=0, torn_bytes=reader.torn_bytes,
                      lines=reader.lines, stored_bytes=stored)
    return entry, digest.hexdigest()


def codex_rel(source: str) -> str:
    for folder in ("archived_sessions", "sessions"):
        marker = f"/{folder}/"
        if marker in source:
            return f"{folder}/{source.rpartition(marker)[2]}"
    return f"sessions/{Path(source).name}"


def _entries_of(vault: Vault, point: LegacyPoint, pace: Optional[Throttle]) -> List[FileEntry]:
    meta, conv = point.meta, str(point.meta.get("conversation_id") or point.directory.parent.name)
    packed = point.directory / meta["transcript"]["file"]
    expected, family = meta["transcript"].get("sha256"), meta.get("agent_family") or "claude"
    source = str(meta["transcript"].get("source_path") or "")
    if family == "codex":
        home, rel, enc = HOME_CODEX, codex_rel(source), None
        role = K.ROLE_CODEX_ROLLOUT
    else:
        enc = _encoded_folder(meta, conv)
        home, rel, role = HOME_CLAUDE, f"projects/{enc}/{conv}.jsonl", K.ROLE_TRANSCRIPT
    with codec_mod.open_reader(packed, meta["codec"]) as stream:
        main, content_sha = _chunk_stream(vault.blobs, stream, int(meta["transcript"]["raw_bytes"]), True, role, home, rel, source, pace)
    if expected and content_sha != expected:
        raise ValueError(f"the old point's transcript does not match its recorded sha256 ({point.key})")
    entries = [main]
    sub = meta.get("subagents")
    if sub and enc is not None:
        base = Path(source).parent / conv / "subagents" if source else Path(conv) / "subagents"
        with codec_mod.open_reader(point.directory / sub["file"], sub.get("codec", meta["codec"])) as stream, \
                tarfile.open(fileobj=stream, mode="r|") as tar:
            for member in tar:
                name = PurePosixPath(member.name)
                if not member.isreg() or name.is_absolute() or ".." in name.parts:
                    continue
                handle = tar.extractfile(member)
                is_jsonl = name.suffix == ".jsonl"
                entries.append(_chunk_stream(vault.blobs, handle, member.size, is_jsonl,
                                             K.ROLE_SUBAGENT if is_jsonl else K.ROLE_CONVERSATION_OTHER, HOME_CLAUDE,
                                             f"projects/{enc}/{conv}/subagents/{name}", str(base / name), pace)[0])
    return entries


def _identity(vault: Vault, files: List[FileEntry], meta: Dict[str, Any], index: ProjectIndex) -> Identity:
    working_dir = meta.get("working_dir")
    main = next((f for f in files if f.role in K.MAIN_ROLES), None)
    if not working_dir and main is not None and main.chunks:
        working_dir = units.working_dir_in(vault.blobs.get(main.chunks[0]))
    return index.complete(Identity(session_uuid=meta.get("session_uuid"), project_name=meta.get("project"),
                                   working_dir=working_dir, wrapper=meta.get("wrapper"), title=meta.get("title")))


def _is_pinned(point: LegacyPoint) -> bool:
    return (point.directory / K.LEGACY_PINNED_MARKER).exists()


def _migrate_one(vault: Vault, point: LegacyPoint, pace: Optional[Throttle], index: ProjectIndex) -> str:
    meta = point.meta
    conv = check_unit(str(meta.get("conversation_id") or point.directory.parent.name))
    with vault.guard.capturing():
        files = _entries_of(vault, point, pace)
        existing = vault.manifests.points(conv)
        twin = next((p for p in existing if signature(files) == signature(p.files)), None)
        if twin is not None:
            if _is_pinned(point):
                vault.manifests.set_pinned(conv, twin.point_id, True)
            return "duplicate"
        ident = _identity(vault, files, meta, index)
        reason = re.sub(r"[^a-z]", "", str(meta.get("reason") or "").lower()) or K.REASON_LEGACY
        stamp = datetime.fromtimestamp(float(meta.get("created_epoch") or point.directory.stat().st_mtime), timezone.utc)
        taken = set(vault.manifests.point_ids(conv))
        manifest = Manifest(
            unit=conv, point_id=layout.new_point_id(reason, stamp, taken), reason=reason, created_epoch=stamp.timestamp(),
            created_at=stamp.isoformat(), kind="conversation", family=meta.get("agent_family") or "claude",
            conversation_id=conv, session_uuid=ident.session_uuid, project_uid=ident.project_uid, project_name=ident.project_name,
            working_dir=ident.working_dir, encoded_folder=_encoded_folder(meta, conv) if (meta.get("agent_family") or "claude") != "codex" else None,
            wrapper=ident.wrapper, title=ident.title, legacy_key=point.key, files=sorted(files, key=lambda f: (f.home, f.rel)))
        vault.blobs.sync_dirs()
        vault.manifests.write(manifest)
        if _is_pinned(point):
            vault.manifests.set_pinned(conv, manifest.point_id, True)
    vault.changed()
    return "migrated"


def _project_index(projects: Optional[Callable[[], List[dict]]]) -> ProjectIndex:
    if projects is None:
        return ProjectIndex()
    try:
        return ProjectIndex(projects())
    except vault_sources.SourceUnavailable as exc:
        logger.warning("vault_legacy_projects_unavailable", error=str(exc))
        return ProjectIndex()


def migrate(vault: Vault, state_dir: Path, pace: Optional[Throttle] = None,
            projects: Optional[Callable[[], List[dict]]] = None) -> LegacyProgress:
    done = _read_done(vault)
    index = _project_index(projects)
    handled = failed = 0
    for point in iter_points(state_dir):
        if point.key in done:
            continue
        if handled and pace is not None and pace.expired():
            return LegacyProgress(more=True, failed=failed)
        handled += 1
        try:
            outcome = _migrate_one(vault, point, pace, index)
        except (ValueError, OSError, ManifestError, codec_mod.CodecError, tarfile.TarError) as exc:
            logger.error("vault_legacy_point_failed", point=point.key, error=str(exc))
            failed += 1
            continue
        done.add(point.key)
        _write_done(vault, done)
        logger.info("vault_legacy_point", point=point.key, outcome=outcome)
    return LegacyProgress(more=False, failed=failed)
