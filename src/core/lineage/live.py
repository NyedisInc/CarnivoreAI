
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import threading
from collections import Counter
from contextlib import closing
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import structlog

from src.core.safe_io.readonly_db import connect_readonly
from src.core.lineage import constants as K
from src.core.lineage import codex, graph, headless, milestones, reclassify, scan, split

logger = structlog.get_logger()

CURSOR_FILENAME: str = "lineage-live.json"
BATCH: int = 40
FIRST_DELAY_SECONDS: float = 45.0
INTERVAL_SECONDS: float = 120.0
MAX_LOAD: float = 10.0


class LineageLiveError(RuntimeError):
    pass


@dataclass
class SweepReport:

    examined: int = 0
    unchanged: int = 0
    dataless_skipped: int = 0
    unreadable: int = 0
    deferred: int = 0
    counts: Counter = field(default_factory=Counter)
    dry_run: bool = False

    def as_dict(self) -> Dict[str, object]:
        return {"dry_run": self.dry_run, "examined": self.examined, "unchanged": self.unchanged,
                "dataless_skipped": self.dataless_skipped, "unreadable": self.unreadable,
                "deferred_to_next_pass": self.deferred, **dict(sorted(self.counts.items()))}


@dataclass(frozen=True)
class FilePlan:

    conversation_id: str
    path: Path
    head: Optional[headless.Head]
    compacts: Tuple[scan.CompactHit, ...]
    subagents: Tuple[str, ...]
    codex: Optional[codex.CodexMeta] = None
    resume: Optional[scan.ScanResume] = None


def _stamp(path: Path) -> Optional[List[int]]:
    try:
        info = path.stat()
    except OSError:
        return None
    return [info.st_mtime_ns, info.st_size]


def cursor_key(path: Path) -> str:
    return str(path)


def is_legacy_key(key: str) -> bool:
    return os.sep not in key


def load_cursor(state_dir: Path) -> Dict[str, List[Any]]:
    try:
        data = json.loads((state_dir / CURSOR_FILENAME).read_text())
    except (OSError, ValueError):
        return {}
    files = data.get("files") if isinstance(data, dict) else None
    return {k: v for k, v in files.items() if isinstance(v, list)} if isinstance(files, dict) else {}


def save_cursor(state_dir: Path, files: Dict[str, List[Any]]) -> None:
    handle = tempfile.NamedTemporaryFile("w", dir=state_dir, prefix=CURSOR_FILENAME, delete=False)
    try:
        with handle:
            json.dump({"version": 2, "files": files}, handle, sort_keys=True)
        os.replace(handle.name, state_dir / CURSOR_FILENAME)
    except OSError:
        Path(handle.name).unlink(missing_ok=True)
        raise


def stamp_of(entry: Sequence[Any]) -> List[Any]:
    return list(entry[:2])


def resume_of(entry: Sequence[Any]) -> Optional[scan.ScanResume]:
    return scan.ScanResume.from_list(entry[2:])


def stored_compacts(conn: sqlite3.Connection, conversation_id: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {K.MILESTONES_TABLE} WHERE conversation_id = ? AND +kind = ?",
                        (conversation_id, K.MILESTONE_COMPACT)).fetchone()[0]


def resume_while_stored(conn: sqlite3.Connection, conversation_id: str,
                        resume: Optional[scan.ScanResume]) -> Optional[scan.ScanResume]:
    if resume is None:
        return None
    stored = stored_compacts(conn, conversation_id)
    if stored < resume.stored:
        logger.info("lineage_live_resume_dropped", conversation_id=conversation_id, stored=stored,
                    expected=resume.stored)
        return None
    return resume


def plan_file(path: Path, resume: Optional[scan.ScanResume] = None) -> FilePlan:
    folder = path.parent / path.stem / K.SUBAGENTS_DIRNAME
    subs = tuple(f"{path.stem}/{p.stem}" for p in sorted(folder.glob("*.jsonl"))) if folder.is_dir() else ()
    found = scan.scan_compacts(path, resume)
    return FilePlan(path.stem, path, headless.read_head(path), tuple(found.hits), subs, resume=found.resume)


def _compact_known(conn: sqlite3.Connection, hit: scan.CompactHit) -> bool:
    return conn.execute(
        f"SELECT 1 FROM {K.MILESTONES_TABLE} WHERE conversation_id = ? AND kind = ? AND (jsonl_line = ? OR at_ts = ?)",
        (hit.conversation_id, K.MILESTONE_COMPACT, hit.line, hit.at_ts)).fetchone() is not None


def plan_codex(path: Path) -> Optional[FilePlan]:
    meta = codex.read_meta(path)
    return None if meta is None else FilePlan(meta.conversation_id, path, None, (), (), meta)


def apply_file(conn: sqlite3.Connection, plan: FilePlan, session_of: Dict[str, str]) -> Counter:
    if plan.codex is not None:
        return codex.apply_meta(conn, plan.codex, session_of)
    out: Counter = Counter()
    conv = plan.conversation_id
    out["nodes"] += graph.set_node(conn, K.NODE_CONVERSATION, conv, plan.head.level, plan.head.entrypoint)
    for hit in plan.compacts:
        if _compact_known(conn, hit):
            continue
        out["compacts"] += milestones.add_milestone(
            conn, conv, K.MILESTONE_COMPACT, K.SOURCE_JSONL_SCAN, session_uuid=session_of.get(conv),
            at_ts=hit.at_ts, jsonl_line=hit.line, jsonl_offset=hit.offset, detail=hit.detail)
    for sub in plan.subagents:
        out["subagents"] += graph.add_edge(conn, K.NODE_CONVERSATION, conv, K.NODE_SUBAGENT, sub,
                                           K.KIND_SUBAGENT) == "added"
    out["fork_pointers_seen"] += split.record_fork_pointer(conn, conv, plan.path, session_of)
    return out


def _spawned(conn: sqlite3.Connection) -> int:
    return sum(graph.add_edge(conn, K.NODE_SESSION, parent, K.NODE_SESSION, child, K.KIND_SPAWNED_BY,
                              created_at=created) == "added" for parent, child, created in scan.spawned_sessions(conn))


def sweep(db_path: Path, state_dir: Path, *, roots: Optional[Sequence[Path]] = None, limit: Optional[int] = None,
          apply: bool = True, codex_root: Optional[Path] = None, include_codex: bool = True) -> SweepReport:
    from src.core.db import DatastoreUnreadableError, connect, transaction

    report = SweepReport(dry_run=not apply)
    search = tuple(roots) if roots is not None else scan.roots()
    cursor = load_cursor(state_dir)
    cursor_before = {stem: list(stamp) for stem, stamp in cursor.items()}
    try:
        conn = connect(db_path, create=False) if apply else _readonly(db_path)
    except (DatastoreUnreadableError, sqlite3.Error) as exc:
        raise LineageLiveError(f"the datastore could not be opened: {exc}") from exc
    with closing(conn):
        if not graph.ready(conn):
            raise LineageLiveError("the datastore predates schema v49 (no lineage tables)")
        session_of = scan.session_of_conversation(conn)
        todo: List[Tuple[Path, str, List[int], Optional[scan.ScanResume]]] = []
        sources = [(p, False) for p in scan.transcripts(search)]
        if include_codex:
            sources += [(p, True) for p in codex.rollouts(codex_root or default_codex_root())]
        for path, is_codex in sources:
            stamp = _stamp(path)
            key = cursor_key(path)
            seen = cursor.get(key) or cursor.get(path.stem, [])
            if stamp is not None and stamp_of(seen) == stamp:
                cursor[key] = seen
            if stamp is None or stamp_of(seen) == stamp:
                report.unchanged += 1
            elif scan.is_dataless(path):
                report.dataless_skipped += 1
            else:
                todo.append((path, key, stamp, resume_of(seen)))
        kind_of = {p: c for p, c in sources}
        report.deferred = max(0, len(todo) - limit) if limit is not None else 0
        for path, key, stamp, resume in todo[:limit]:
            try:
                plan = (plan_codex(path) if kind_of[path]
                        else plan_file(path, resume_while_stored(conn, path.stem, resume)))
            except OSError as exc:
                report.unreadable += 1
                logger.warning("lineage_live_unreadable", path=str(path), error=str(exc))
                continue
            report.examined += 1
            if plan is None:
                cursor[key] = stamp
                continue
            written = _write(conn, plan, session_of, apply, transaction)
            report.counts.update(written)
            if apply and written.get("compacts"):
                _announce_compaction(session_of.get(plan.conversation_id))
            cursor[key] = stamp + _resume_entry(conn, plan, apply)
        if apply:
            with transaction(conn):
                report.counts["spawned_by"] += _spawned(conn)
                by_stem = {p.stem: p for p, is_codex in sources if not is_codex}
                report.counts["switches_reclassified"] += reclassify.reclassify_switches(
                    conn, roots=search, finder=lambda conversation, _roots: by_stem.get(conversation))
    if apply:
        if roots is None and not report.deferred:
            cursor = {k: v for k, v in cursor.items() if not is_legacy_key(k)}
        if cursor != cursor_before:
            save_cursor(state_dir, cursor)
    return report


def _resume_entry(conn: sqlite3.Connection, plan: FilePlan, apply: bool) -> List[int]:
    if plan.resume is None:
        return []
    stored = stored_compacts(conn, plan.conversation_id) if apply else plan.resume.stored
    return replace(plan.resume, stored=stored).as_list()


def _announce_compaction(session_uuid: Optional[str]) -> None:
    from src.core.bookmarks import compactions

    try:
        compactions.announce(session_uuid)
    except (OSError, RuntimeError) as exc:
        logger.warning("lineage_compaction_announce_failed", session_uuid=session_uuid, error=str(exc))


def default_codex_root() -> Path:
    from src.core.codex_corpus_discover import default_codex_root as _root

    return _root()


def _write(conn: sqlite3.Connection, plan: FilePlan, session_of: Dict[str, str], apply: bool, transaction) -> Counter:
    if apply:
        with transaction(conn):
            return apply_file(conn, plan, session_of)
    out: Counter = Counter()
    if plan.codex is not None:
        out["nodes"] = int(conn.execute(
            f"SELECT 1 FROM {K.NODES_TABLE} WHERE node_type = ? AND node_id = ?",
            (K.NODE_CONVERSATION, plan.conversation_id)).fetchone() is None)
        out["codex_fork_edges"] = int(plan.codex.forked_from is not None)
        out["codex_spawn_edges"] = int(plan.codex.spawn_parent is not None)
        return out
    out["compacts"] = sum(not _compact_known(conn, h) for h in plan.compacts)
    out["nodes"] = int(conn.execute(
        f"SELECT 1 FROM {K.NODES_TABLE} WHERE node_type = ? AND node_id = ?",
        (K.NODE_CONVERSATION, plan.conversation_id)).fetchone() is None)
    out["subagents"] = sum(conn.execute(
        f"SELECT 1 FROM {K.EDGES_TABLE} WHERE parent_type = ? AND parent_id = ? AND child_type = ? AND child_id = ? "
        "AND edge_kind = ?", (K.NODE_CONVERSATION, plan.conversation_id, K.NODE_SUBAGENT, s, K.KIND_SUBAGENT)
    ).fetchone() is None for s in plan.subagents)
    out["fork_pointers_seen"] = int(split.read_split_point(plan.path) is not None)
    return out


def _readonly(db_path: Path) -> sqlite3.Connection:
    conn = connect_readonly(db_path)
    conn.execute("PRAGMA query_only = ON")
    return conn


_stop = threading.Event()
_thread: Optional[threading.Thread] = None


def _loop(db_path: Path, state_dir: Path) -> None:
    _stop.wait(FIRST_DELAY_SECONDS)
    while not _stop.is_set():
        try:
            busy = os.getloadavg()[0] > MAX_LOAD
        except OSError:
            busy = False
        if not busy:
            try:
                report = sweep(db_path, state_dir, limit=BATCH)
                if report.examined or report.counts:
                    logger.info("lineage_live_pass", **report.as_dict())
            except (LineageLiveError, OSError, sqlite3.Error) as exc:
                logger.warning("lineage_live_pass_failed", error=str(exc), error_type=type(exc).__name__)
        _stop.wait(INTERVAL_SECONDS)


def start(db_path: Path, state_dir: Path) -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(db_path, state_dir), name="lineage-live", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
