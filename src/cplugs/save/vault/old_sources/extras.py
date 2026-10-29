
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog

from src.cplugs.save.engine import layout
from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault.manifest import HOME_FOLDER
from src.cplugs.save.vault.old_sources import model
from src.core.deepsearch.fallback_hook import FallbackPoint, IncomingFile

logger = structlog.get_logger()

UNIT = "save.old-archive-extras"
_TABLE_DIR, _FOREIGN, _AUDIT = "archive-metadata", "foreign", "audit.jsonl"


@dataclass(frozen=True)
class ExtraFile:

    path: Path
    rel: str
    length: int
    sha256: str
    mtime: float


def _opener(path: Path):
    def open_bytes():
        with open(path, "rb") as handle:
            while block := handle.read(model.READ_BLOCK):
                yield block
    return open_bytes


def find(root: Path, intake: model.Intake) -> List[ExtraFile]:
    root = Path(root)
    found: List[ExtraFile] = []
    if not root.is_dir():
        return found
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        for filename in sorted(filenames):
            path = Path(dirpath) / filename
            rel = path.relative_to(root).as_posix()
            parts = rel.split("/")
            if path.is_symlink() or filename.startswith("._"):
                continue
            if not ((_TABLE_DIR in parts[:-1] and filename.endswith(".jsonl")) or (parts[0] == _FOREIGN and filename == _AUDIT)):
                continue
            try:
                length, sha = model.measure(_opener(path))
                found.append(ExtraFile(path, rel, length, sha, path.stat().st_mtime))
            except OSError as exc:
                intake.refused.append(model.Refusal("extras", str(path), f"unreadable: {type(exc).__name__}"))
    return found


def fingerprint_part(files: List[ExtraFile]) -> List[Tuple[str, str]]:
    return [(f.rel, f.sha256) for f in files]


def point_of(root: Path, files: List[ExtraFile], run: str, taken: Optional[set] = None) -> Optional[FallbackPoint]:
    if not files:
        return None
    stamp = max(f.mtime for f in files)
    point_id = layout.new_point_id(K.REASON_IMPORT, datetime.fromtimestamp(stamp, timezone.utc), taken or set())
    incoming = tuple(IncomingFile(role=K.ROLE_FOLDER_FILE, home=HOME_FOLDER, rel=f.rel, source_path=str(f.path), length=f.length,
                                  sha256=f.sha256, mode=0o600, mtime_ns=int(f.mtime * 1e9), lines=0, read=_opener(f.path)) for f in files)
    tags: Dict[str, object] = {"imported": True, "kind": "extras", "run": run, "sources": ["recovered-transcripts"], "labels": [],
                               "files": len(files), "digest": hashlib.sha256("".join(f.sha256 for f in files).encode()).hexdigest()}
    return FallbackPoint(conversation_id=UNIT, point_id=point_id, reason=K.REASON_IMPORT, created_epoch=stamp,
                         created_at=datetime.fromtimestamp(stamp, timezone.utc).isoformat(), family=K.FAMILY_PLUGIN, files=incoming,
                         working_dir=str(root), kind=K.KIND_FOLDER, tags=tags)
