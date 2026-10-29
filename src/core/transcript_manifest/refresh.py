"""One manifest refresh end to end: walk the roots, scan against the stored rows, optionally write.

THE WALK IS THE EXISTING ONE. Claude files come from ``merged_claude_discovery`` over the account-aware
roots (``claude_config.transcript_roots``: the default ``~/.claude/projects`` first, then every managed
profile's own, de-duplicated by real path), codex rollouts from the codex discovery over
``~/.codex/sessions``. Both classify by location only and report the directories they could not list;
this module adds no second walker.

A RESULT IS THE ONE SOURCE the archive freshness check and the backfill planner read, so both see the
same files, with the same order (default root first, then the other claude roots, then codex).

``write=False`` is a dry run: the database may be opened read-only, the rows are read (none when the
table does not exist yet), the same decisions are made, and nothing is written.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import structlog

from src.core.db import connect
from src.core.transcript_corpus_discover import CorpusEntry, DiscoveryOutcome
from src.core.transcript_manifest import constants as K
from src.core.transcript_manifest import store
from src.core.transcript_manifest.scan import Observed, ScanResult, scan

logger = structlog.get_logger(__name__)

_UUID_CHARS = 36


@dataclass(frozen=True)
class Walk:

    observed: List[Observed]
    complete_roots: List[str]
    unreadable_roots: List[str]
    # could not
    unreadable_dirs: int = 0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _root_of(entry: CorpusEntry) -> str:
    text = str(entry.abs_path)
    return text[: len(text) - len(entry.source_path) - 1]


def claude_observed(entry: CorpusEntry) -> Observed:
    parts = entry.source_path.split("/")
    if entry.kind == "subagent":
        kind, conv = K.KIND_SUBAGENT, (parts[1] if len(parts) > 1 else None)
    elif entry.kind == "session":
        kind, conv = K.KIND_CONVERSATION, Path(parts[-1]).stem
    else:
        kind, conv = K.KIND_OTHER, None
    return Observed(str(entry.abs_path), K.FAMILY_CLAUDE, _root_of(entry), entry.source_path, conv, kind)


def codex_observed(entry: CorpusEntry) -> Observed:
    return Observed(str(entry.abs_path), K.FAMILY_CODEX, _root_of(entry), entry.source_path,
                    Path(entry.abs_path).stem[-_UUID_CHARS:], K.KIND_CONVERSATION)


def _resolved(root: Path) -> str:
    return str(Path(root).expanduser().resolve())


def walk(claude_roots: Optional[Sequence[Path]] = None, codex_home: Optional[str] = None) -> Walk:
    from src.core.attention.codex_gather import DEFAULT_CODEX_HOME
    from src.core.claude_config.transcript_roots import claude_transcript_roots
    from src.core.stats.discovery_shared import merged_claude_discovery, shared_discovery

    roots: Tuple[Path, ...] = tuple(claude_roots) if claude_roots is not None else claude_transcript_roots()
    observed: List[Observed] = []
    complete: List[str] = []
    unreadable: List[str] = []
    dirs = [0]

    def _account(outcome: DiscoveryOutcome, names: List[str]) -> None:
        (unreadable if outcome.unreadable_count else complete).extend(names)
        dirs[0] += outcome.unreadable_count

    claude = merged_claude_discovery(roots, fresh=True)
    observed.extend(claude_observed(e) for e in claude.entries)
    _account(claude, [_resolved(r) for r in roots if Path(r).is_dir()])
    home = DEFAULT_CODEX_HOME if codex_home is None else codex_home
    if home:
        sessions = Path(home) / "sessions"
        if sessions.is_dir():
            codex = shared_discovery("codex", sessions, fresh=True)
            observed.extend(codex_observed(e) for e in codex.entries)
            _account(codex, [_resolved(sessions)])
    return Walk(observed, complete, unreadable, dirs[0])


def refresh(db_path: Path, *, write: bool = True, claude_roots: Optional[Sequence[Path]] = None,
            codex_home: Optional[str] = None, conn: Optional[sqlite3.Connection] = None) -> ScanResult:
    """Walk, scan against the stored rows, and (unless ``write`` is False) store the result.

    Inputs: db_path (Path) - cloude.db; write (bool) - False is a dry run (the file is opened ``mode=ro``);
      claude_roots, codex_home - overrides; conn - an open connection to use instead of ``db_path``.
    Output: ScanResult. Raises: sqlite3.Error, OSError (a database that cannot be opened or written).
    Example: refresh(db_path_for(state_dir), write=False).counts['added']
    """
    found = walk(claude_roots, codex_home)
    now = utc_now()
    if conn is not None:
        return _scan_on(conn, found, now, write)
    if write:
        opened = connect(Path(db_path), create=False)
    else:
        opened = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True, timeout=30)
    with closing(opened):
        return _scan_on(opened, found, now, write)


def _scan_on(conn: sqlite3.Connection, found: Walk, now: str, write: bool) -> ScanResult:
    result = scan(store.load_rows(conn), found.observed, complete_roots=found.complete_roots,
                  unreadable_roots=found.unreadable_roots, now=now)
    result.discovery_unreadable = found.unreadable_dirs
    if write and store.table_present(conn):
        store.persist(conn, result, now)
    logger.info("transcript_manifest_scan", write=write, **{k: v for k, v in result.counts.items()},
                files=len(result.present), unreadable_roots=len(found.unreadable_roots))
    return result


def claude_entries(result: ScanResult) -> List[CorpusEntry]:
    kinds = {K.KIND_CONVERSATION: "session", K.KIND_SUBAGENT: "subagent"}
    return [CorpusEntry(abs_path=Path(r.path), source_path=r.source_path, kind=kinds[r.kind])
            for r in result.present if r.family == K.FAMILY_CLAUDE and r.kind in kinds]
