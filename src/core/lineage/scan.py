
from __future__ import annotations

import json
import os
import sqlite3
import stat
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Dict, Iterator, List, Optional, Sequence, Tuple

import structlog

from src.core.lineage import constants as K
from src.core.lineage.headless import Head, read_head

logger = structlog.get_logger()

_NEEDLE = K.COMPACT_SUBTYPE.encode()
_SF_DATALESS = getattr(stat, "SF_DATALESS", 0x40000000)


@dataclass(frozen=True)
class CompactHit:

    conversation_id: str
    line: int
    offset: int
    at_ts: Optional[str]
    detail: Dict[str, object]


@dataclass
class ScanReport:

    transcripts: int = 0
    dataless_skipped: int = 0
    unreadable: int = 0
    compacts: List[CompactHit] = field(default_factory=list)
    subagents: List[Tuple[str, str]] = field(default_factory=list)
    heads: List[Head] = field(default_factory=list)


def roots(corpus_root: Optional[Path] = None) -> Tuple[Path, ...]:
    if corpus_root is not None:
        return (Path(corpus_root),)
    from src.core.claude_config.transcript_roots import claude_transcript_roots

    return claude_transcript_roots()


def is_dataless(path: Path) -> bool:
    try:
        return bool(os.stat(path).st_flags & _SF_DATALESS)
    except (OSError, AttributeError):
        return False


@dataclass(frozen=True)
class ScanResume:

    offset: int
    lines: int
    stored: int
    anchor: int

    def as_list(self) -> List[int]:
        return [self.offset, self.lines, self.stored, self.anchor]

    @classmethod
    def from_list(cls, values: Sequence[Any]) -> Optional["ScanResume"]:
        if len(values) != 4 or not all(isinstance(v, int) and not isinstance(v, bool) for v in values):
            return None
        return cls(values[0], values[1], values[2], values[3])


@dataclass(frozen=True)
class CompactScan:

    hits: List[CompactHit]
    resume: ScanResume


def _anchor_of(handle: BinaryIO, offset: int, lines: int) -> int:
    size = min(offset, K.RESUME_ANCHOR_BYTES)
    handle.seek(0)
    head = handle.read(size)
    handle.seek(offset - size)
    tail = zlib.crc32(handle.read(size), zlib.crc32(head))
    return zlib.crc32(str(lines).encode(), tail)


def _start_of(handle: BinaryIO, resume: Optional[ScanResume]) -> Tuple[int, int]:
    if resume is not None and 0 < resume.offset <= os.fstat(handle.fileno()).st_size \
            and _anchor_of(handle, resume.offset, resume.lines) == resume.anchor:
        handle.seek(resume.offset)
        return resume.lines, resume.offset
    handle.seek(0)
    return 0, 0


def _hits_in(conversation_id: str, block: bytes, first_line: int, first_offset: int) -> Iterator[CompactHit]:
    if _NEEDLE not in block:
        return
    offset = first_offset
    for index, raw in enumerate(block.split(b"\n")):
        if _NEEDLE in raw:
            hit = _parse_hit(conversation_id, first_line + index + 1, offset, raw)
            if hit is not None:
                yield hit
        offset += len(raw) + 1


def _parse_hit(conversation_id: str, line: int, offset: int, raw: bytes) -> Optional[CompactHit]:
    try:
        record = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(record, dict) or record.get("subtype") != K.COMPACT_SUBTYPE or record.get("type") != "system":
        return None
    meta = record.get("compactMetadata") if isinstance(record.get("compactMetadata"), dict) else {}
    detail = {k: v for k, v in (("trigger", meta.get("trigger")), ("pre_tokens", meta.get("preTokens")),
                                ("record_uuid", record.get("uuid"))) if v is not None}
    return CompactHit(conversation_id, line, offset, record.get("timestamp"), detail)


def scan_compacts(path: Path, resume: Optional[ScanResume] = None) -> CompactScan:
    found: List[CompactHit] = []
    with path.open("rb") as handle:
        line_no, offset = _start_of(handle, resume)
        carry = b""
        while True:
            chunk = handle.read(K.SCAN_CHUNK_BYTES)
            if not chunk:
                break
            carry += chunk
            cut = carry.rfind(b"\n")
            if cut < 0:
                continue
            block, carry = carry[:cut], carry[cut + 1:]
            found.extend(_hits_in(path.stem, block, line_no, offset))
            line_no += block.count(b"\n") + 1
            offset += len(block) + 1
        found.extend(_hits_in(path.stem, carry, line_no, offset))
        return CompactScan(found, ScanResume(offset, line_no, 0, _anchor_of(handle, offset, line_no)))


def compacts_of(path: Path) -> List[CompactHit]:
    return scan_compacts(path).hits


def transcripts(scan_roots: Sequence[Path]) -> Iterator[Path]:
    seen: set = set()
    for root in scan_roots:
        for folder in _folders(root):
            for path in sorted(folder.glob("*.jsonl")):
                if path.stem not in seen:
                    seen.add(path.stem)
                    yield path


def find_transcript(conversation_id: str, scan_roots: Sequence[Path]) -> Optional[Path]:
    for root in scan_roots:
        for folder in _folders(root):
            candidate = folder / f"{conversation_id}.jsonl"
            if candidate.is_file():
                return candidate
    return None


def _folders(root: Path) -> List[Path]:
    try:
        return [p for p in root.iterdir() if p.is_dir()]
    except OSError as exc:
        logger.warning("lineage_scan_root_unreadable", root=str(root), error=str(exc))
        return []


def scan(scan_roots: Sequence[Path], skip: frozenset = frozenset()) -> ScanReport:
    report = ScanReport()
    seen: set = set()
    for root in scan_roots:
        for folder in _folders(root):
            for path in sorted(folder.glob("*.jsonl")):
                if path.stem in seen or path.stem in skip:
                    continue
                seen.add(path.stem)
                report.transcripts += 1
                if is_dataless(path):
                    report.dataless_skipped += 1
                    continue
                try:
                    report.heads.append(read_head(path))
                    report.compacts.extend(compacts_of(path))
                except OSError as exc:
                    report.unreadable += 1
                    logger.warning("lineage_scan_unreadable", path=str(path), error=str(exc))
            for sub in sorted(folder.glob(f"*/{K.SUBAGENTS_DIRNAME}/*.jsonl")):
                if sub.parent.parent.name in skip:
                    continue
                report.subagents.append((sub.parent.parent.name, f"{sub.parent.parent.name}/{sub.stem}"))
    return report


def session_of_conversation(conn: sqlite3.Connection) -> Dict[str, str]:
    out: Dict[str, str] = {}
    has_index = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'conversation_index'").fetchone()
    if has_index:
        for conv, uuid in conn.execute("SELECT conversation_id, session_uuid FROM conversation_index "
                                       "WHERE session_uuid IS NOT NULL"):
            out[conv] = uuid
    for conv, uuid in conn.execute("SELECT claude_session_uuid, session_uuid FROM sessions "
                                   "WHERE claude_session_uuid IS NOT NULL AND session_uuid IS NOT NULL"):
        out[conv] = uuid
    return out


def spawned_sessions(conn: sqlite3.Connection) -> List[Tuple[str, str, Optional[str]]]:
    rows = conn.execute("SELECT p.session_uuid, c.session_uuid, c.created_at FROM sessions c "
                        "JOIN sessions p ON p.id = c.parent_session_id WHERE c.session_uuid IS NOT NULL "
                        "AND p.session_uuid IS NOT NULL").fetchall()
    return [(r[0], r[1], r[2]) for r in rows]
