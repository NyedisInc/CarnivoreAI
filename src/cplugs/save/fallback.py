
from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence

import structlog

from src.cplugs.save.service import RUNTIME
from src.cplugs.save.vault import adopt as adopt_mod
from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault.location import VaultUnavailable
from src.cplugs.save.vault.old_sources import labels as labels_mod
from src.cplugs.save.vault.manifest import FileEntry, Manifest, ManifestError
from src.cplugs.save.vault.ranges import ChunkCache, EntryReader
from src.cplugs.save.vault.store import Vault
from src.core.deepsearch import fallback_hook as fb
from src.core.deepsearch.fallback_hook import AdoptedPoint, FallbackPoint, FallbackPointFile

logger = structlog.get_logger()

_MANIFEST_CACHE_MAX: int = 64


def _hidden(vault: Vault, unit: str, point_id: str) -> bool:
    try:
        tags = vault.manifests.read_tags(unit, point_id)
    except ManifestError as exc:
        logger.warning("vault_tags_unreadable", unit=unit, point=point_id, error=str(exc)[:200])
        return True
    return bool(tags) and labels_mod.is_hidden(tags.get("labels") or [])


def _file_kind(entry: FileEntry) -> str:
    return "conversation" if entry.role in K.MAIN_ROLES else "subagent"


class BackupTranscripts:

    def __init__(self, vault: Callable[[], Vault] = RUNTIME.vault) -> None:
        self._vault = vault
        self._cache = ChunkCache()
        self._manifests: Dict[str, Manifest] = {}
        self._lock = threading.Lock()

    def _open(self) -> Vault:
        try:
            return self._vault()
        except VaultUnavailable as exc:
            raise OSError(str(exc)) from exc

    def _newest(self, vault: Vault, unit: str) -> Optional[Manifest]:
        ids = vault.manifests.point_ids(unit)
        if not ids:
            return None
        with self._lock:
            held = self._manifests.get(unit)
        if held is not None and held.point_id == ids[-1]:
            return held
        try:
            newest = vault.manifests.newest(unit)
        except ManifestError as exc:
            raise fb.FallbackUnavailable(str(exc)) from exc
        if newest is not None:
            with self._lock:
                if len(self._manifests) >= _MANIFEST_CACHE_MAX:
                    self._manifests.clear()
                self._manifests[unit] = newest
        return newest

    def conversations(self) -> Iterator[fb.FallbackConversation]:
        vault = self._open()
        for unit in vault.manifests.units():
            newest = vault.manifests.newest(unit)
            main = newest.main() if newest is not None else None
            if newest is None or main is None or newest.kind != "conversation":
                continue
            yield fb.FallbackConversation(conversation_id=unit, family=newest.family, signature=main.sha256,
                                          working_dir=newest.working_dir, title=newest.title,
                                          session_uuid=newest.session_uuid, project_name=newest.project_name,
                                          sha256=main.sha256 if main.sha_kind == K.SHA_CONTENT else None,
                                          hidden=_hidden(vault, unit, newest.point_id))

    def files(self, conversation_id: str) -> List[fb.FallbackFile]:
        newest = self._newest(self._open(), conversation_id)
        if newest is None or newest.kind != "conversation":
            return []
        found = [fb.FallbackFile(conversation_id=conversation_id, family=newest.family, file_kind=_file_kind(e),
                                 source_path=e.source_path, rel=e.rel, length=e.length, signature=e.chain_sha(),
                                 working_dir=newest.working_dir)
                 for e in newest.files if e.role in K.LINE_ROLES and e.source_path]
        return sorted(found, key=lambda f: f.file_kind != "conversation")

    def reader(self, conversation_id: str, source_path: str, file_kind: str) -> EntryReader:
        newest = self._newest(self._open(), conversation_id)
        entries = [e for e in (newest.files if newest is not None else []) if e.role in K.LINE_ROLES and _file_kind(e) == file_kind]
        match = next((e for e in entries if e.source_path == source_path), None)
        if match is None:
            wanted = fb.path_tail(source_path, conversation_id)
            match = next((e for e in entries if fb.path_tail(e.source_path or e.rel, conversation_id) == wanted), None)
        if match is None:
            raise fb.FallbackUnavailable(f"the backup of {conversation_id} holds no {file_kind} file {source_path}")
        return EntryReader(self._open().blobs, match, self._cache)

    def entries(self, conversation_id: str) -> List[fb.FallbackEntry]:
        newest = self._newest(self._open(), conversation_id)
        if newest is None or newest.kind != "conversation":
            return []
        return [fb.FallbackEntry(conversation_id=conversation_id, family=newest.family, role=e.role, home=e.home, rel=e.rel,
                                 source_path=e.source_path, length=e.length, signature=e.chain_sha(), mode=e.mode,
                                 mtime_ns=e.mtime_ns)
                for e in newest.files]

    def entry_reader(self, conversation_id: str, rel: str) -> EntryReader:
        vault = self._open()
        newest = self._newest(vault, conversation_id)
        match = next((e for e in (newest.files if newest is not None else []) if e.rel == rel), None)
        if match is None:
            raise fb.FallbackUnavailable(f"the backup of {conversation_id} holds no file {rel}")
        return EntryReader(vault.blobs, match, self._cache)

    def list_points(self, conversation_id: str) -> List[FallbackPoint]:
        vault = self._open()
        try:
            points = vault.manifests.points(conversation_id)
            if len(points) != len(vault.manifests.point_ids(conversation_id)):
                raise fb.FallbackUnavailable(f"a point of {conversation_id} cannot be read")
        except ManifestError as exc:
            raise fb.FallbackUnavailable(str(exc)) from exc
        return [FallbackPoint(
            conversation_id=conversation_id, point_id=m.point_id, reason=m.reason, created_epoch=m.created_epoch,
            created_at=m.created_at, family=m.family, session_uuid=m.session_uuid, project_uid=m.project_uid,
            project_name=m.project_name, working_dir=m.working_dir, encoded_folder=m.encoded_folder, wrapper=m.wrapper,
            title=m.title,
            files=tuple(FallbackPointFile(role=e.role, home=e.home, rel=e.rel, source_path=e.source_path, length=e.length,
                                          sha256=e.sha256 if e.sha_kind == K.SHA_CONTENT else "", mode=e.mode, mtime_ns=e.mtime_ns, lines=e.lines)
                        for e in m.files))
            for m in points if m.kind == "conversation"]

    def list_folder_points(self, unit: str) -> List[FallbackPoint]:
        vault = self._open()
        try:
            points = vault.manifests.points(unit)
            if len(points) != len(vault.manifests.point_ids(unit)):
                raise fb.FallbackUnavailable(f"a point of {unit} cannot be read")
        except ManifestError as exc:
            raise fb.FallbackUnavailable(str(exc)) from exc
        return [FallbackPoint(
            conversation_id=unit, point_id=m.point_id, reason=m.reason, created_epoch=m.created_epoch, created_at=m.created_at,
            family=m.family, working_dir=m.working_dir, kind=K.KIND_FOLDER,
            files=tuple(FallbackPointFile(role=e.role, home=e.home, rel=e.rel, source_path="", length=e.length,
                                          sha256=e.sha256 if e.sha_kind == K.SHA_CONTENT else "", mode=e.mode, mtime_ns=e.mtime_ns, lines=e.lines)
                        for e in m.files))
            for m in points if m.kind == K.KIND_FOLDER]

    def point_entry_reader(self, conversation_id: str, point_id: str, rel: str) -> EntryReader:
        vault = self._open()
        try:
            manifest = vault.manifests.read(conversation_id, point_id)
        except ManifestError as exc:
            raise fb.FallbackUnavailable(str(exc)) from exc
        match = next((e for e in manifest.files if e.rel == rel), None)
        if match is None:
            raise fb.FallbackUnavailable(f"point {point_id} of {conversation_id} holds no file {rel}")
        return EntryReader(vault.blobs, match, self._cache)

    def adopt_points(self, points: Sequence[FallbackPoint], log: Callable[[Dict[str, Any]], None]) -> List[AdoptedPoint]:
        return adopt_mod.adopt_points(self._open(), points, log)

    def remove_adopted(self, entries: Sequence[Dict[str, Any]]) -> Dict[str, List[str]]:
        return adopt_mod.remove_adopted(self._open(), entries)
