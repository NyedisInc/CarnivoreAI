
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import structlog

from src.cplugs.save.engine import layout
from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault.summary import PointSummary, SummaryCache
from src.cplugs.sdk.blob_codec import ChunkRef, chain_sha, refs_from_json, refs_to_json

logger = structlog.get_logger()

_UNIT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{2,199}$")

HOME_CLAUDE, HOME_CODEX, HOME_STATE, HOME_FOLDER = "claude", "codex", "state", "folder"
HOMES = (HOME_CLAUDE, HOME_CODEX, HOME_STATE, HOME_FOLDER)


class ManifestError(RuntimeError):
    pass


class SoleCopyError(RuntimeError):
    pass


@dataclass
class FileEntry:

    role: str
    home: str
    rel: str
    source_path: str
    length: int
    sha256: str
    chunks: List[ChunkRef]
    size_seen: int = 0
    mtime_ns: int = 0
    torn_bytes: int = 0
    lines: int = 0
    stored_bytes: int = 0
    mode: int = 0
    sha_kind: str = K.SHA_CONTENT
    digests: List[Dict[str, Any]] = field(default_factory=list)

    def as_json(self) -> Dict[str, Any]:
        return {"role": self.role, "home": self.home, "rel": self.rel, "source_path": self.source_path, "length": self.length,
                "sha256": self.sha256, "chunks": refs_to_json(self.chunks), "size_seen": self.size_seen,
                "mtime_ns": self.mtime_ns, "torn_bytes": self.torn_bytes, "lines": self.lines,
                "stored_bytes": self.stored_bytes, "mode": self.mode, "sha_kind": self.sha_kind,
                **({"digests": self.digests} if self.digests else {})}

    def chain_sha(self) -> str:
        return chain_sha(self.chunks)

    def extends(self, old: "FileEntry") -> bool:
        if self.length < old.length:
            return False
        keep = max(0, len(old.chunks) - 1)
        return [c.sha256 for c in old.chunks[:keep]] == [c.sha256 for c in self.chunks[:keep]]

    def tail_due(self, mtime_ns: int, now: float) -> bool:
        return self.torn_bytes > 0 and now - mtime_ns / 1e9 >= K.QUIET_TAIL_SECONDS

    @staticmethod
    def from_json(data: Dict[str, Any]) -> "FileEntry":
        try:
            entry = FileEntry(role=str(data["role"]), home=str(data["home"]), rel=str(data["rel"]),
                              source_path=str(data.get("source_path", "")), length=int(data["length"]),
                              sha256=str(data["sha256"]), chunks=refs_from_json(data["chunks"]),
                              size_seen=int(data.get("size_seen", 0)), mtime_ns=int(data.get("mtime_ns", 0)),
                              torn_bytes=int(data.get("torn_bytes", 0)), lines=int(data.get("lines", 0)),
                              stored_bytes=int(data.get("stored_bytes", 0)), mode=int(data.get("mode", 0)) & 0o777,
                              sha_kind=str(data.get("sha_kind", K.SHA_CONTENT)), digests=list(data.get("digests") or []))
        except (KeyError, TypeError, ValueError) as exc:
            raise ManifestError(f"malformed file entry: {exc}") from exc
        if entry.home not in HOMES:
            raise ManifestError(f"unknown home {entry.home!r}")
        if entry.sha_kind not in (K.SHA_CONTENT, K.SHA_CHAIN):
            raise ManifestError(f"unknown sha kind {entry.sha_kind!r}")
        check_rel(entry.rel)
        if sum(c.length for c in entry.chunks) != entry.length:
            raise ManifestError(f"chunk lengths of {entry.rel} do not add up to its length")
        return entry


def check_rel(rel: str) -> str:
    parts = rel.split("/")
    if not rel or rel.startswith("/") or any(p in ("", ".", "..") for p in parts):
        raise ManifestError(f"unsafe relative path {rel!r}")
    return rel


@dataclass
class Manifest:

    unit: str
    point_id: str
    reason: str
    created_epoch: float
    created_at: str
    kind: str = "conversation"
    family: str = "claude"
    conversation_id: Optional[str] = None
    session_uuid: Optional[str] = None
    project_uid: Optional[str] = None
    project_name: Optional[str] = None
    working_dir: Optional[str] = None
    encoded_folder: Optional[str] = None
    wrapper: Optional[str] = None
    title: Optional[str] = None
    legacy_key: Optional[str] = None
    files: List[FileEntry] = field(default_factory=list)

    def raw_bytes(self) -> int:
        return sum(f.length for f in self.files)

    def chunk_hashes(self) -> Iterator[str]:
        for entry in self.files:
            for chunk in entry.chunks:
                yield chunk.sha256

    def main(self) -> Optional[FileEntry]:
        return next((f for f in self.files if f.role in (K.ROLE_TRANSCRIPT, K.ROLE_CODEX_ROLLOUT)), None)

    def as_json(self) -> Dict[str, Any]:
        return {"format": K.FORMAT_VERSION, "unit": self.unit, "point_id": self.point_id, "reason": self.reason,
                "created_epoch": self.created_epoch, "created_at": self.created_at, "kind": self.kind, "family": self.family,
                "conversation_id": self.conversation_id, "session_uuid": self.session_uuid, "project_uid": self.project_uid,
                "project_name": self.project_name, "working_dir": self.working_dir, "encoded_folder": self.encoded_folder,
                "wrapper": self.wrapper, "title": self.title, "legacy_key": self.legacy_key,
                "files": [f.as_json() for f in self.files]}

    @staticmethod
    def from_json(data: Dict[str, Any]) -> "Manifest":
        if not isinstance(data, dict) or data.get("format") != K.FORMAT_VERSION:
            raise ManifestError(f"not a format {K.FORMAT_VERSION} manifest")
        try:
            return Manifest(
                unit=check_unit(str(data["unit"])), point_id=layout.check_point_id(str(data["point_id"])),
                reason=str(data["reason"]), created_epoch=float(data["created_epoch"]), created_at=str(data["created_at"]),
                kind=str(data.get("kind", "conversation")), family=str(data.get("family", "claude")),
                conversation_id=data.get("conversation_id"), session_uuid=data.get("session_uuid"),
                project_uid=data.get("project_uid"), project_name=data.get("project_name"),
                working_dir=data.get("working_dir"), encoded_folder=data.get("encoded_folder"),
                wrapper=data.get("wrapper"), title=data.get("title"), legacy_key=data.get("legacy_key"),
                files=[FileEntry.from_json(f) for f in data["files"]])
        except (KeyError, TypeError, ValueError, layout.InvalidIdError) as exc:
            raise ManifestError(f"malformed manifest: {exc}") from exc


def check_unit(value: str) -> str:
    if not isinstance(value, str) or not _UNIT_RE.match(value):
        raise ManifestError(f"not a valid unit id: {value!r}")
    return value


def memory_unit_id(encoded_folder: str) -> str:
    import hashlib

    name = K.MEMORY_UNIT_PREFIX + encoded_folder
    return name if _UNIT_RE.match(name) and len(name) <= 120 else K.MEMORY_UNIT_PREFIX + hashlib.sha1(encoded_folder.encode()).hexdigest()[:20]


class ManifestStore:

    def __init__(self, root: Path) -> None:
        self._dir = Path(root) / K.MANIFESTS_DIR
        self.summaries = SummaryCache(ManifestError, Path(root) / K.SUMMARIES_FILE)

    def save_summaries(self) -> bool:
        return self.summaries.save()

    def summary(self, unit: str, point_id: str) -> PointSummary:
        layout.check_point_id(point_id)
        return self.summaries.get(self.unit_dir(unit) / f"{point_id}.json", unit, point_id, lambda: self.read(unit, point_id))

    def unit_dir(self, unit: str) -> Path:
        return self._dir / check_unit(unit)

    def exists(self) -> bool:
        return self._dir.is_dir()

    def units(self) -> List[str]:
        try:
            return sorted(p.name for p in self._dir.iterdir() if p.is_dir() and not p.name.startswith("."))
        except FileNotFoundError:
            return []

    def point_ids(self, unit: str) -> List[str]:
        try:
            return sorted(p.stem for p in self.unit_dir(unit).iterdir()
                          if p.suffix == ".json" and not p.name.startswith("."))
        except FileNotFoundError:
            return []

    def read(self, unit: str, point_id: str) -> Manifest:
        layout.check_point_id(point_id)
        path = self.unit_dir(unit) / f"{point_id}.json"
        try:
            return Manifest.from_json(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            raise ManifestError(f"manifest {unit}/{point_id} unreadable: {exc}") from exc

    def points(self, unit: str) -> List[Manifest]:
        found: List[Manifest] = []
        for point_id in self.point_ids(unit):
            try:
                found.append(self.read(unit, point_id))
            except ManifestError as exc:
                logger.error("vault_manifest_unreadable", unit=unit, point_id=point_id, error=str(exc))
        return found

    def newest(self, unit: str) -> Optional[Manifest]:
        for point_id in reversed(self.point_ids(unit)):
            try:
                return self.read(unit, point_id)
            except ManifestError as exc:
                logger.error("vault_manifest_unreadable", unit=unit, point_id=point_id, error=str(exc))
        return None

    def next_stamp(self, unit: str, now: datetime) -> datetime:
        latest = None
        for point_id in self.point_ids(unit):
            try:
                latest = datetime.strptime(point_id[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        stamp = now.astimezone(timezone.utc).replace(microsecond=0)
        return latest + timedelta(seconds=1) if latest is not None and stamp <= latest else stamp

    def new_point_id(self, unit: str, reason: str, stamp: datetime) -> str:
        safe = re.sub(r"[^a-z]", "", reason.lower()) or "point"
        return layout.new_point_id(safe, stamp, set(self.point_ids(unit)))

    @staticmethod
    def render(manifest: Manifest) -> bytes:
        return json.dumps(manifest.as_json(), sort_keys=True).encode("utf-8")

    def write(self, manifest: Manifest) -> Path:
        folder = self.unit_dir(manifest.unit)
        folder.mkdir(parents=True, exist_ok=True)
        final = folder / f"{manifest.point_id}.json"
        temp = folder / layout.temp_name()
        with open(temp, "wb") as handle:
            handle.write(self.render(manifest))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, final)
        layout.fsync_path(folder)
        return final

    def delete(self, unit: str, point_id: str) -> None:
        ids = self.point_ids(unit)
        if point_id not in ids:
            return
        if not any(self._readable(unit, other) for other in reversed(ids) if other != point_id):
            raise SoleCopyError(f"{unit}/{point_id} is the unit's last readable point; the vault never removes it")
        (self.unit_dir(unit) / f"{point_id}.json").unlink()
        self.pin_path(unit, point_id).unlink(missing_ok=True)
        self.keep_path(unit, point_id).unlink(missing_ok=True)
        self.tags_path(unit, point_id).unlink(missing_ok=True)

    def remove_adopted(self, unit: str, point_id: str, manifest_sha256: str) -> str:
        import hashlib

        path = self.unit_dir(unit) / f"{layout.check_point_id(point_id)}.json"
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            return "absent"
        if hashlib.sha256(data).hexdigest() != manifest_sha256:
            return "changed"
        if self.is_pinned(unit, point_id):
            return "pinned"
        path.unlink()
        self.keep_path(unit, point_id).unlink(missing_ok=True)
        self.tags_path(unit, point_id).unlink(missing_ok=True)
        try:
            self.unit_dir(unit).rmdir()
        except OSError:
            pass
        return "removed"

    def _readable(self, unit: str, point_id: str) -> bool:
        try:
            self.summary(unit, point_id)
        except ManifestError:
            return False
        return True

    def pin_path(self, unit: str, point_id: str) -> Path:
        return self.unit_dir(unit) / f"{point_id}{K.PINNED_SUFFIX}"

    def is_pinned(self, unit: str, point_id: str) -> bool:
        return self.pin_path(unit, point_id).exists()

    def set_pinned(self, unit: str, point_id: str, pinned: bool) -> None:
        if point_id not in self.point_ids(unit):
            raise ManifestError(f"no point {point_id} in {unit}")
        if pinned:
            self.pin_path(unit, point_id).touch()
        else:
            self.pin_path(unit, point_id).unlink(missing_ok=True)

    def keep_path(self, unit: str, point_id: str) -> Path:
        return self.unit_dir(unit) / f"{point_id}{K.KEPT_SUFFIX}"

    def is_kept(self, unit: str, point_id: str) -> bool:
        return self.keep_path(unit, point_id).exists()

    def set_kept(self, unit: str, point_id: str) -> None:
        marker = self.keep_path(unit, point_id)
        marker.touch()
        layout.fsync_path(marker.parent)

    def tags_path(self, unit: str, point_id: str) -> Path:
        return self.unit_dir(unit) / f"{point_id}{K.TAGS_SUFFIX}"

    def write_tags(self, unit: str, point_id: str, tags: Dict[str, Any]) -> None:
        folder = self.unit_dir(unit)
        folder.mkdir(parents=True, exist_ok=True)
        temp = folder / layout.temp_name()
        with open(temp, "wb") as handle:
            handle.write(json.dumps(tags, sort_keys=True).encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, self.tags_path(unit, point_id))
        layout.fsync_path(folder)

    def read_tags(self, unit: str, point_id: str) -> Dict[str, Any]:
        path = self.tags_path(unit, point_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise ManifestError(f"tags {unit}/{point_id} unreadable: {exc}") from exc
        if not isinstance(data, dict):
            raise ManifestError(f"tags {unit}/{point_id} are not an object")
        return data

    def exported_path(self, unit: str) -> Path:
        return self.unit_dir(unit) / K.EXPORTED_MARKER

    def mark_exported(self, unit: str) -> None:
        folder = self.unit_dir(unit)
        folder.mkdir(parents=True, exist_ok=True)
        self.exported_path(unit).touch()

    def exported_at(self, unit: str) -> Optional[float]:
        try:
            return self.exported_path(unit).stat().st_mtime
        except OSError:
            return None

    def is_exported(self, unit: str) -> bool:
        return self.exported_path(unit).exists()
