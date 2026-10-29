
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

import structlog

from src.core.db import transaction
from src.core.swarm import memory
from src.core.trail_entry import utc_now

logger = structlog.get_logger()

MAX_TERMS = 40
MIN_TERM_CHARS = 2
STOPWORDS = frozenset(
    "a about above after again all also am an and any are as at be because been before being below between both but by "
    "can could did do does doing down during each few for from further had has have having he her here hers him his how "
    "i if in into is it its just me more most my no nor not now of off on once only or other our out over own same she "
    "should so some such than that the their them then there these they this those through to too under until up us "
    "very was we were what when where which while who whom why will with would you your".split())
_TERM_RE = re.compile(r"\w+", re.UNICODE)
_FACT_STEM_RE = re.compile(r"^f_[0-9a-f]{12}$")
_FRONT_RE = re.compile(r"\A---\n(.*?)\n---\n\n?(.*)\Z", re.DOTALL)
_SKIP_NOTES = frozenset({"MEMORY.md", memory.OVERFLOW_NAME})


class Fts5Missing(RuntimeError):
    pass


@dataclass(frozen=True)
class BestHit:

    doc_key: str
    coverage: float
    bm25: float
    hit: bool


def require_fts5(conn: sqlite3.Connection) -> None:
    options = {row[0] for row in conn.execute("PRAGMA compile_options")}
    if "ENABLE_FTS5" not in options:
        raise Fts5Missing("this sqlite has no FTS5; the Swarm memory index needs it")


def query_terms(text: str) -> List[str]:
    seen: Dict[str, None] = {}
    for tok in _TERM_RE.findall(text.lower()):
        if len(tok) >= MIN_TERM_CHARS and tok not in STOPWORDS and tok not in seen:
            seen[tok] = None
    return list(seen)[:MAX_TERMS]


def _quote(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def rank(conn: sqlite3.Connection, terms: Sequence[str], agent_ids: Sequence[int],
         doc_keys: Optional[Set[str]] = None) -> List[BestHit]:
    if not terms or not agent_ids:
        return []
    marks = ",".join("?" * len(agent_ids))
    found: Dict[str, int] = {}
    for term in terms:
        rows = conn.execute(
            f"SELECT doc_key FROM swarm_fact_fts WHERE swarm_fact_fts MATCH ? AND agent_id IN ({marks})",
            (_quote(term), *agent_ids))
        for (key,) in rows:
            if doc_keys is None or key in doc_keys:
                found[key] = found.get(key, 0) + 1
    if not found:
        return []
    scores = {key: float(score) for key, score in conn.execute(
        f"SELECT doc_key, bm25(swarm_fact_fts) FROM swarm_fact_fts WHERE swarm_fact_fts MATCH ? "
        f"AND agent_id IN ({marks})", (" OR ".join(_quote(t) for t in terms), *agent_ids))}
    hits = [BestHit(key, n / len(terms), scores.get(key, 0.0), False) for key, n in found.items()]
    hits.sort(key=lambda h: (-h.coverage, h.bm25, h.doc_key))
    return hits


def best(conn: sqlite3.Connection, tier_agent_id: int, question: str,
         min_coverage: Optional[float] = None) -> Optional[BestHit]:
    if min_coverage is None:
        from src.core.swarm import settings

        min_coverage = settings.read_current().wake_hit_min_coverage
    top = rank(conn, query_terms(question), [tier_agent_id])
    if not top:
        return None
    first = top[0]
    return BestHit(first.doc_key, first.coverage, first.bm25, first.coverage >= min_coverage and first.bm25 < 0)


def _unquote(raw: str) -> str:
    if raw.startswith('"'):
        try:
            return str(json.loads(raw))
        except ValueError:
            pass
    return raw.strip()


def _split_front(text: str, stem: str) -> Tuple[str, str, Dict[str, str]]:
    m = _FRONT_RE.match(text)
    meta: Dict[str, str] = {}
    body = text
    if m:
        body = m.group(2)
        for line in m.group(1).split("\n"):
            key, sep, raw = line.partition(": ")
            if sep:
                meta[key.strip()] = _unquote(raw)
    title = meta.get("title") or next((ln.lstrip("# ").strip() for ln in body.splitlines() if ln.strip()), "") or stem
    return title[:200], body.strip(), meta


def _read(path: Path) -> Optional[Tuple[str, str, Dict[str, str]]]:
    try:
        return _split_front(path.read_text(encoding="utf-8", errors="replace"), path.stem)
    except OSError as exc:
        logger.warning("swarm_fact_file_unreadable", file=path.name, error_type=type(exc).__name__)
        return None


def _register_handwritten(conn: sqlite3.Connection, agent_id: int, mem: Path) -> None:
    facts_dir = mem / "facts"
    if not facts_dir.is_dir():
        return
    known = {r[0] for r in conn.execute("SELECT id FROM swarm_facts WHERE agent_id = ?", (agent_id,))}
    for path in sorted(facts_dir.glob("f_*.md")):
        if not _FACT_STEM_RE.match(path.stem) or path.stem in known:
            continue
        if conn.execute("SELECT 1 FROM swarm_facts WHERE id = ?", (path.stem,)).fetchone():
            continue
        read = _read(path)
        if read is None:
            continue
        title, _body, meta = read
        scope = meta.get("scope") if meta.get("scope") in memory.FACT_SCOPES else "project"
        conn.execute(
            "INSERT INTO swarm_facts (id, agent_id, rel_path, title, scope, origin, taught_at, state) "
            "VALUES (?, ?, ?, ?, ?, 'handwritten', ?, 'live')",
            (path.stem, agent_id, f"facts/{path.name}", title, scope, meta.get("taught_at") or utc_now()))
        logger.info("swarm_fact_handwritten_registered", agent_id=agent_id, fact_id=path.stem)


def live_entries(conn: sqlite3.Connection, agent_id: int) -> List[memory.IndexEntry]:
    return [memory.IndexEntry(r["id"], r["title"], r["scope"], r["origin"], r["taught_at"]) for r in conn.execute(
        "SELECT id, title, scope, origin, taught_at FROM swarm_facts WHERE agent_id = ? AND state = 'live'", (agent_id,))]


def _documents(conn: sqlite3.Connection, agent_id: int, mem: Path) -> Iterable[Tuple[str, str, str]]:
    live = {r["id"]: r["rel_path"] for r in conn.execute(
        "SELECT id, rel_path FROM swarm_facts WHERE agent_id = ? AND state = 'live'", (agent_id,))}
    registered = {r[0] for r in conn.execute("SELECT id FROM swarm_facts WHERE agent_id = ?", (agent_id,))}
    for fact_id, rel in live.items():
        read = _read(mem / rel)
        if read is not None:
            yield f"fact:{fact_id}", read[0], read[1]
    if not mem.is_dir():
        return
    for path in sorted(mem.rglob("*.md")):
        rel = path.relative_to(mem).as_posix()
        if path.name in _SKIP_NOTES or path.stem in registered or path.is_symlink():
            continue
        read = _read(path)
        if read is not None:
            yield f"file:{agent_id}:{rel}", read[0], read[1]


def refresh_agent(conn: sqlite3.Connection, agent: Mapping[str, Any], *, write_block: bool = True) -> int:
    require_fts5(conn)
    agent_id = int(agent["id"])
    mem = memory.memory_dir(Path(agent["repo_dir"]), agent["slug"], agent["memory_scope"])
    with transaction(conn):
        _register_handwritten(conn, agent_id, mem)
        docs = list(_documents(conn, agent_id, mem))
        conn.execute("DELETE FROM swarm_fact_fts WHERE agent_id = ?", (agent_id,))
        conn.executemany("INSERT INTO swarm_fact_fts (doc_key, agent_id, title, body) VALUES (?, ?, ?, ?)",
                         [(key, agent_id, title, body) for key, title, body in docs])
    if write_block and mem.is_dir():
        try:
            memory.write_index(mem, live_entries(conn, agent_id))
        except memory.SwarmFileError as exc:
            logger.warning("swarm_index_block_skipped", agent_id=agent_id, error=str(exc)[:200])
    return len(docs)

