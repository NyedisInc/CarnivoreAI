
from __future__ import annotations

import io
import re
import socket
import sqlite3
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

import structlog

from src.core.companies import accounts as company_accounts, store as company_store
from src.core.swarm import definition, memory
from src.core.swarm.brief import SECTION_REPORT, SECTION_RULES, SECTION_WHO

logger = structlog.get_logger()

MAX_FACTS = 400
MAX_BYTES = 2 * 1024 * 1024
MAX_FILE_BYTES = 64 * 1024
_KEPT_SECTIONS = (SECTION_WHO, SECTION_RULES, SECTION_REPORT)
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_FACT_ID = re.compile(r"f_[0-9a-f]{12}")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_ROOT_TAIL = r"(?:/[^/\s`'\"<>)\]]+(?: [^/\s`'\"<>)\]]+){0,4}(?=/))*(?:/[^\s`'\"<>)\]]*)?"
_ABS_PATH = re.compile(r"(?<![\w.~-])(?:/(?:Users|home|private|var|tmp|opt|Volumes|mnt|srv|root|etc)|~)(?=/)" + _ROOT_TAIL)
_REPO_URL = re.compile(r"(?:(?:https?://|ssh://git@|git@)[^\s/:`'\"<>)\]]+[/:][^\s/`'\"<>)\]]+/[^\s`'\"<>)\]]+"
                       r"|(?:https?://|git@)[^\s`'\"<>)\]]*github[^\s`'\"<>)\]]*)", re.IGNORECASE)


class ExportRefused(ValueError):
    pass


class ExportTooLarge(ExportRefused):
    pass


def _portable(text: str, repo_dir: str, home: Tuple[str, ...]) -> str:
    out = text
    for root in {repo_dir, str(Path(repo_dir).resolve())}:
        out = out.replace(root, "your-repo")
    out = _known_root_pattern(repo_dir).sub("a-path", out)
    out = _ABS_PATH.sub("a-path", out)
    out = _REPO_URL.sub("a-repo-url", out)
    out = _EMAIL.sub("an-email", out)
    for name in sorted({v for n in home for v in _spellings(n)}, key=len, reverse=True):
        out = re.sub(rf"(?<![\w-]){re.escape(name)}(?![\w-])", "your-project", out, flags=re.IGNORECASE)
    return out


def _known_root_pattern(repo_dir: str) -> "re.Pattern[str]":
    repo = Path(repo_dir)
    roots = {str(Path.home()), str(repo), str(repo.resolve()), str(repo.parent), str(repo.resolve().parent)}
    roots = {r.rstrip("/") for r in roots if r.rstrip("/") and r.startswith("/")}
    alt = "|".join(re.escape(r) for r in sorted(roots, key=len, reverse=True))
    return re.compile(rf"(?<![\w.~-])(?:{alt})(?=/|\b)" + _ROOT_TAIL)


def _spellings(name: str) -> Tuple[str, ...]:
    if "/" in name:
        return (name,)
    slug = _slugify(name)
    return tuple({v for v in (name, slug, slug.replace("-", "_"), slug.replace("-", "")) if len(v) >= 4})


def _home_names(conn: sqlite3.Connection, agent: Dict[str, Any], parent: str) -> Tuple[str, ...]:
    names = [Path(agent["repo_dir"]).name, parent, socket.gethostname(), socket.gethostname().split(".")[0], str(Path.home())]
    names += [agent.get("persona"), agent.get("naming_family")]
    names += [r[0] for r in conn.execute("SELECT display_name FROM swarm_agents WHERE id != ? AND torn_down_at IS NULL "
                                         "AND (parent_id = ? OR (parent_id IS NOT NULL AND parent_id = ?))",
                                         (agent["id"], agent["id"], agent.get("parent_id") or -1))]
    company_id = agent.get("company_id")
    if agent.get("project_id") is not None:
        proj = conn.execute("SELECT display_name, company_id FROM projects WHERE id = ?", (agent["project_id"],)).fetchone()
        if proj:
            names.append(proj[0])
            company_id = company_id if company_id is not None else proj[1]
    if company_id is not None:
        found = conn.execute("SELECT name FROM companies WHERE id = ?", (company_id,)).fetchone()
        names.append(found[0] if found else "")
        try:
            names += list(company_accounts.get_accounts(conn, company_id).values())
        except company_store.CompanyNotFound:
            pass
        names += [r[0] for r in conn.execute("SELECT display_name FROM projects WHERE company_id = ?", (company_id,))]
    return tuple(sorted({n.strip() for n in names if isinstance(n, str) and len(n.strip()) >= 4}, key=len, reverse=True))


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _ties_home(text: str, home: Tuple[str, ...]) -> bool:
    flat = f"-{_slugify(text)}-"
    return any(f"-{t}-" in flat for t in {_slugify(n) for n in home} - {""})


def export_name(agent: Dict[str, Any], home: Tuple[str, ...]) -> str:

    def clean(candidate: Any) -> bool:
        return isinstance(candidate, str) and memory.is_valid_slug(candidate) and not _ties_home(candidate, home)

    if clean(agent["slug"]):
        return agent["slug"]
    task = _slugify(agent.get("task_type") or "") if agent.get("rank") == "feature" else ""
    if task and clean(task):
        return task
    return f"{agent.get('rank') or 'project'}-agent"


def _read_small(path: Path, repo: Path) -> str:
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(repo.resolve()):
        raise ExportRefused("a file the export needs is missing or is not a regular file")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ExportRefused("a file the export needs is too large")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ExportRefused("a file the export needs is not valid text") from exc


def _sections(text: str) -> Dict[str, str]:
    parts = re.split(r"(?m)^(?=## )", text)
    return {p.split("\n", 1)[0][3:].strip(): p.rstrip("\n") for p in parts if p.startswith("## ")}


def _definition(agent: Dict[str, Any], parent: str, mem_rel: str, home: Tuple[str, ...], out_name: str) -> definition.AgentDefinition:
    repo, slug = agent["repo_dir"], agent["slug"]
    parsed = definition.parse_definition(_read_small(Path(repo) / ".claude" / "agents" / f"{slug}.md", Path(repo)))
    secs = _sections(parsed.brief)
    name = _portable(agent["display_name"], repo, home)
    if name != agent["display_name"] or _ties_home(name, home):
        name = out_name.replace("-", " ").capitalize()
    kept = [secs[h] for h in _KEPT_SECTIONS if h in secs]
    if not kept:
        kept = [f"You are {name}. Your job: {_portable(parsed.description, repo, home)}"]
    read_first = (f"## Read first\n\n`{mem_rel}/MEMORY.md` and the fact files it lists: what earlier runs learned.")
    body = "\n\n".join([f"# {name}", kept[0], read_first, *kept[1:]])
    body = re.sub(rf"(?<![\w-]){re.escape(slug)}(?![\w-])", out_name, body)
    if parent:
        body = re.sub(rf"(?<![\w-]){re.escape(parent)}(?![\w-])", "your parent", body.replace(f", spawned by {parent}", ""))
    return definition.AgentDefinition(
        slug=out_name, description=_portable(parsed.description, repo, home).replace("\n", " "),
        rank="feature" if parsed.tools is None else "project", effort=agent["effort"], memory=memory.SCOPE_PROJECT,
        brief=_portable(body, repo, home), display_name=name)


def _craft_facts(conn: sqlite3.Connection, agent: Dict[str, Any], mem: Path, home: Tuple[str, ...]) -> List[memory.Fact]:
    rows = conn.execute("SELECT id, title, taught_at FROM swarm_facts WHERE agent_id = ? AND scope = 'craft' AND state = 'live' "
                        "AND origin IN ('agent', 'owner') "
                        "ORDER BY taught_at DESC, id", (agent["id"],)).fetchall()
    if len(rows) > MAX_FACTS:
        raise ExportTooLarge(f"this agent has more than {MAX_FACTS} craft facts, too many to export")
    out: List[memory.Fact] = []
    for row in rows:
        if not _FACT_ID.fullmatch(row["id"]):
            continue
        try:
            fact = memory.parse_fact(_read_small(mem / "facts" / f"{row['id']}.md", Path(agent["repo_dir"])))
        except (memory.SwarmFileError, ExportRefused, OSError):
            logger.warning("swarm_export_fact_skipped", fact_id=row["id"], agent_id=agent["id"])
            continue
        if fact.id != row["id"]:
            continue
        out.append(memory.Fact(id=fact.id, title=_portable(row["title"], agent["repo_dir"], home), scope="craft", origin="agent",
                               taught_at=row["taught_at"], body=_portable(fact.body, agent["repo_dir"], home)))
    return out


def _readme(slug: str, name: str, n_facts: int) -> str:
    return (f"# {name}: a Swarm agent's craft\n\nThis bundle holds what the agent knows about its craft, with nothing of the "
            f"project it learned on. Unzip it at the root of a repository.\n\n"
            f"- `.claude/agents/{slug}.md`: the Claude Code agent definition.\n"
            f"- `.codex/agents/{slug}.toml`: the Codex twin of it.\n"
            f"- `.claude/agent-memory/{slug}/`: its memory, `MEMORY.md` plus {n_facts} craft fact file(s) under `facts/`.\n\n"
            f"Start it with `claude --agent {slug}`.\n")


def build_blocking(conn: sqlite3.Connection, agent: Dict[str, Any]) -> bytes:
    return build_named_blocking(conn, agent)[1]


def build_named_blocking(conn: sqlite3.Connection, agent: Dict[str, Any]) -> Tuple[str, bytes]:
    if agent.get("torn_down_at"):
        raise ExportRefused("that agent has been torn down, so there is nothing to export")
    repo, slug = Path(agent["repo_dir"]), memory.require_slug(agent["slug"])
    mem = memory.memory_dir(repo, slug, agent["memory_scope"])
    if not mem.resolve().is_relative_to(repo.resolve()):
        raise ExportRefused("the agent's memory folder is outside its repo")
    parent = ""
    if agent.get("parent_id") is not None:
        found = conn.execute("SELECT display_name FROM swarm_agents WHERE id = ?", (agent["parent_id"],)).fetchone()
        parent = found[0] if found else ""
    home = _home_names(conn, agent, parent)
    out = export_name(agent, home)
    mem_rel = f".claude/agent-memory/{out}"
    defn = _definition(agent, parent, mem_rel, home, out)
    facts = _craft_facts(conn, agent, mem, home)
    block, overflow = memory.render_index_block(
        memory.IndexEntry(f.id, f.title, f.scope, f.origin, f.taught_at) for f in facts)
    files: List[Tuple[str, str]] = [
        ("README.md", _readme(out, defn.display_name, len(facts))),
        (f".claude/agents/{out}.md", definition.render_definition(defn)),
        (f".codex/agents/{out}.toml", definition.render_codex_twin(defn)),
        (f"{mem_rel}/MEMORY.md", block + "\n"),
    ]
    if overflow is not None:
        files.append((f"{mem_rel}/facts/{memory.OVERFLOW_NAME}", overflow))
    files += [(f"{mem_rel}/facts/{f.id}.md", memory.render_fact(f)) for f in facts]
    for name, text in files:
        memory.refuse_secrets(text, f"export file {name}")
    if sum(len(t.encode("utf-8")) for _, t in files) > MAX_BYTES:
        raise ExportTooLarge("the export would be larger than 2 MB")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in files:
            info = zipfile.ZipInfo(name, _ZIP_TIME)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, text.encode("utf-8"))
    logger.info("swarm_export_built", agent_id=agent["id"], facts=len(facts))
    return out, buf.getvalue()
