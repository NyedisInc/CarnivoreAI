
from __future__ import annotations

import json
import os
import sqlite3
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

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


def _hits_in(block: bytes, first_line: int, first_offset: int) -> Iterator[Tuple[int, int, bytes]]:
    offset = first_offset
    for index, line in enumerate(block.split(b"\n")):
        if _NEEDLE in line:
            yield first_line + index + 1, offset, line
        offset += len(line) + 1


def compact_lines(path: Path) -> Iterator[Tuple[int, int, bytes]]:
    line_no, offset, carry = 0, 0, b""
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(K.SCAN_CHUNK_BYTES)
            if not chunk:
                break
            carry += chunk
            cut = carry.rfind(b"\n")
            if cut < 0:
                continue
            block, carry = carry[:cut], carry[cut + 1:]
            if _NEEDLE in block:
                yield from _hits_in(block, line_no, offset)
            line_no += block.count(b"\n") + 1
            offset += len(block) + 1
    if carry and _NEEDLE in carry:
        yield from _hits_in(carry, line_no, offset)


def compacts_of(path: Path) -> List[CompactHit]:
    found: List[CompactHit] = []
    for line_no, offset, raw in compact_lines(path):
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("subtype") != K.COMPACT_SUBTYPE or record.get("type") != "system":
            continue
        meta = record.get("compactMetadata") if isinstance(record.get("compactMetadata"), dict) else {}
        detail = {k: v for k, v in (("trigger", meta.get("trigger")), ("pre_tokens", meta.get("preTokens")),
                                    ("record_uuid", record.get("uuid"))) if v is not None}
        found.append(CompactHit(path.stem, line_no, offset, record.get("timestamp"), detail))
    return found


def transcripts(scan_roots: Sequence[Path]) -> Iterator[Path]:
    """Every top-level conversation transcript under the roots, each conversation id once (first root wins).

    Inputs: scan_roots (from :func:`roots`). Output: iterator of Path, sorted within a folder.
    """
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
    """Walk every root once: each top-level transcript's head and compact boundaries, and every subagent transcript.

    Description: the FALLBACK for what the archive does not hold (``lineage.archive_extract`` is the primary
      source): a conversation id in ``skip`` (archived) is neither read nor are its subagent files listed.
    Inputs: scan_roots (from :func:`roots`); skip (conversation ids already read from the archive).
    Output: ScanReport.
    Example: len(scan(roots()).compacts)
    """
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
