
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Tuple

import structlog

from src.core.message_model_secrets import scan_text
from src.core.swarm.slugs import is_valid_slug

logger = structlog.get_logger(__name__)

SCOPE_PROJECT = "project"
SCOPE_LOCAL = "local"
FACT_SCOPES = ("craft", "project")
FACT_ORIGINS = ("owner", "agent", "handwritten")
INDEX_START = "<!-- swarm:index:start -->"
INDEX_END = "<!-- swarm:index:end -->"
INDEX_LINE_CAP = 150
OVERFLOW_NAME = "INDEX-more.md"
_FACT_ID_RE = re.compile(r"^f_[0-9a-f]{12}$")


class SwarmFileError(ValueError):
    pass


class SecretRefused(SwarmFileError):

    def __init__(self, where: str, detectors: Tuple[str, ...]) -> None:
        self.where = where
        self.detectors = detectors
        super().__init__(f"secret-shaped content refused in {where} ({', '.join(detectors)})")


@dataclass(frozen=True)
class Fact:

    id: str
    title: str
    scope: str
    origin: str
    taught_at: str
    body: str
    owner_message_ref: Optional[str] = None


@dataclass(frozen=True)
class IndexEntry:

    id: str
    title: str
    scope: str
    origin: str
    taught_at: str


def require_slug(slug: str) -> str:
    if not isinstance(slug, str) or not is_valid_slug(slug):
        raise SwarmFileError("invalid agent slug")
    return slug


def refuse_secrets(text: str, where: str) -> None:
    findings = scan_text(text)
    if findings:
        detectors = tuple(sorted({f.detector for f in findings}))
        logger.warning("swarm_secret_refused", where=where, detectors=list(detectors))
        raise SecretRefused(where, detectors)


def memory_dir(repo: Path, slug: str, scope: str) -> Path:
    require_slug(slug)
    if scope == SCOPE_PROJECT:
        return Path(repo) / ".claude" / "agent-memory" / slug
    if scope == SCOPE_LOCAL:
        return Path(repo) / ".claude" / "agent-memory-local" / slug
    raise SwarmFileError("memory scope must be project or local")


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".swarm-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def adopt_legacy_json(mem: Path) -> None:
    old, new = mem / "pack.json", mem / "swarm.json"
    if old.is_file() and not new.exists():
        old.rename(new)


def ensure_layout(mem: Path) -> None:
    (mem / "facts").mkdir(parents=True, exist_ok=True)
    adopt_legacy_json(mem)
    index = mem / "MEMORY.md"
    if not index.exists():
        atomic_write(index, f"{INDEX_START}\n{INDEX_END}\n")


def render_fact(fact: Fact) -> str:
    _check_fact(fact)
    lines = ["---", f"id: {fact.id}", f"title: {json.dumps(fact.title)}",
             f"scope: {fact.scope}", f"origin: {fact.origin}",
             f"taught_at: {json.dumps(fact.taught_at)}"]
    if fact.owner_message_ref is not None:
        lines.append(f"owner_message_ref: {json.dumps(fact.owner_message_ref)}")
    lines += ["---", "", fact.body.rstrip("\n"), ""]
    return "\n".join(lines)


def parse_fact(text: str) -> Fact:
    m = re.match(r"\A---\n(.*?)\n---\n\n?(.*)\Z", text, re.DOTALL)
    if not m:
        raise SwarmFileError("fact file has no frontmatter")
    meta = {}
    for line in m.group(1).split("\n"):
        key, sep, raw = line.partition(": ")
        if not sep:
            raise SwarmFileError("fact frontmatter line has no value")
        meta[key] = _unquote(raw)
    try:
        fact = Fact(id=meta["id"], title=meta["title"], scope=meta["scope"],
                    origin=meta["origin"], taught_at=meta["taught_at"],
                    body=m.group(2).rstrip("\n"),
                    owner_message_ref=meta.get("owner_message_ref"))
    except KeyError as exc:
        raise SwarmFileError(f"fact frontmatter lacks {exc.args[0]}") from exc
    _check_fact(fact)
    return fact


def write_fact(mem: Path, fact: Fact) -> Path:
    where = f"facts/{fact.id}.md"
    refuse_secrets(fact.title, f"{where} title")
    refuse_secrets(fact.body, f"{where} body")
    path = mem / "facts" / f"{fact.id}.md"
    atomic_write(path, render_fact(fact))
    return path


def render_index_block(entries: Iterable[IndexEntry]) -> Tuple[str, Optional[str]]:
    ordered = sorted(entries, key=lambda e: e.taught_at, reverse=True)
    ordered.sort(key=lambda e: e.origin != "owner")
    lines = [_index_line(e) for e in ordered]
    head, rest = lines[:INDEX_LINE_CAP], lines[INDEX_LINE_CAP:]
    if rest:
        head.append(f"- [more facts](facts/{OVERFLOW_NAME}) {len(rest)} more")
    block = "\n".join([INDEX_START, *head, INDEX_END])
    overflow = "\n".join(["# More facts", "", *rest, ""]) if rest else None
    return block, overflow


def merge_index(memory_md: str, block: str) -> str:
    start, end = memory_md.find(INDEX_START), memory_md.find(INDEX_END)
    if start != -1 and end > start:
        rest = memory_md[:start] + memory_md[end + len(INDEX_END):]
    else:
        rest = memory_md
    rest = rest.lstrip("\n")
    return block + "\n" + (("\n" + rest) if rest else "")


def write_index(mem: Path, entries: Iterable[IndexEntry]) -> None:
    entries = list(entries)
    for e in entries:
        refuse_secrets(e.title, f"MEMORY.md index title {e.id}")
    block, overflow = render_index_block(entries)
    index = mem / "MEMORY.md"
    current = index.read_text(encoding="utf-8") if index.exists() else ""
    atomic_write(index, merge_index(current, block))
    more = mem / "facts" / OVERFLOW_NAME
    if overflow is not None:
        atomic_write(more, overflow)
    elif more.exists():
        more.unlink()


def _index_line(e: IndexEntry) -> str:
    title = re.sub(r"[\[\]\n\r]", " ", e.title).strip()
    return f"- [{title}](facts/{e.id}.md) {e.scope}"


def _check_fact(fact: Fact) -> None:
    if not _FACT_ID_RE.match(fact.id):
        raise SwarmFileError("fact id must be f_ plus 12 hex")
    if fact.scope not in FACT_SCOPES or fact.origin not in FACT_ORIGINS:
        raise SwarmFileError("fact scope or origin is not allowed")
    if (fact.origin == "owner") != (fact.owner_message_ref is not None):
        raise SwarmFileError("owner_message_ref is set exactly for owner facts")


def _unquote(raw: str) -> str:
    if raw.startswith('"'):
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SwarmFileError("bad quoted frontmatter value") from exc
    return raw
