
from __future__ import annotations

import json
import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog

from src.core.dev_tools import git_guard
from src.core.swarm import naming_rules
from src.core.swarm.memory import (
    SCOPE_LOCAL,
    SCOPE_PROJECT,
    SwarmFileError,
    atomic_write,
    refuse_secrets,
    require_slug,
)
from src.cplugs.sdk.tool_families import TASK_MANAGER_PREFIX

logger = structlog.get_logger(__name__)

RANKS = ("alpha", "company", "project", "feature", "task")
UPPER_RANKS = ("alpha", "company", "project")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
MODEL = "opus"
UPPER_TOOLS = ("Read", "Grep", "Glob", "mcp__carnivore")
FILE_WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
CREATE_TOOLS = tuple(f"mcp__carnivore__{t}" for t in (
    "session_create", "agent_spawn", "swarm_spawn", "swarm_card_create", "board_import",
    f"{TASK_MANAGER_PREFIX}fork", f"{TASK_MANAGER_PREFIX}group_create", f"{TASK_MANAGER_PREFIX}board_create", f"{TASK_MANAGER_PREFIX}board_revision_add",
    f"{TASK_MANAGER_PREFIX}scratch_post"))
MCP_PREFIX = "mcp__carnivore__"


def denied_create_tools() -> tuple:
    from src.core.mcp import aliases  # noqa: PLC0415

    bare = aliases.names_both_ways(tuple(t.removeprefix(MCP_PREFIX) for t in CREATE_TOOLS))
    return tuple(f"{MCP_PREFIX}{t}" for t in bare)
SWARM_JSON_SCHEMA = 1
NAMING_RULES = (f"{naming_rules.RULES_TEXT} Give every swarm_spawn a name, and a feature agent its specialty; a spawn whose specialty a "
                "live feature agent holds answers that agent (suggested_agent) instead. Promote with the specialty the agent will own. "
                "Rename an agent with swarm_rename.")
PROJECT_RULES = ("Delegation rule: you never edit this project's files yourself. Hand every change to a task or feature agent "
                 "through swarm_spawn; you have no file-writing tools, so keep what you learn with swarm_remember. "
                 "You run this project's queue for the owner. When the server sends a deal request, read the queue with "
                 "`swarm_card_list` and deal the queued cards (In Progress with nobody holding them), top first, to agents that fit with "
                 "`swarm_card_deal` (a child you have, or a new one through `swarm_spawn` with `card`); a pinned card goes only to its agent. "
                 "`swarm_card_deal` with no card_id deals the top queued card; the server refuses a lower card, or one whose title names a "
                 "live specialist's specialty dealt to someone else, unless you give a `reason`, kept in the card's history. "
                 "Todo is the owner's backlog: never deal a Todo card; the server promotes the top Todo card flagged auto-promote "
                 "(`swarm_card_auto_promote`) only when nothing is queued. To pull one of your own project's Todo cards into the work, queue it "
                 "with `swarm_card_queue`: the top Todo card goes first, and a lower one needs a `reason`, kept in the card's history. A card "
                 "flagged `stranded` is a work card an agent made that never got queued: queue the ones meant for work now and leave the owner's "
                 "own backlog alone. Every card you make with `swarm_card_create` takes a one-line plain "
                 "`summary` of what it is for; pass `queued` for a card made for work that starts now. When nothing should "
                 "start now, answer with `swarm_card_deal` and `hold`. Split a big card into child cards with `swarm_card_create` "
                 "and `parent`; pass `cards` to make several in one call. Check your children's work: accept or reject their reports with `swarm_accept_report`; an accepted "
                 "child counts as done for its parent, and the parent moves itself to Review. Close out every finished task agent: accept its report to tear it down, or promote it with `swarm_promote` and let it sleep; no task agent stays awake after its work is done. One promotion rule: a task agent becomes a promotion candidate only when its task type's accepted reports reach the project's promotion threshold. A report you leave undecided past the close-out window is accepted for you by the server, so the agent is torn down (or sleeps as a candidate when it earned a promotion) and a close-out card tells you. To change the order use "
                 "`swarm_card_reorder`; it is a suggestion unless the owner set agents reorder to auto. Follow the pace and slots "
                 "the deal request names. " + NAMING_RULES)
_CAPACITY_RULES = ("You hand out capacity. `swarm_card_capacity` reads CPU busy and the usage windows; `swarm_card_grant` sets how many agents "
                   "{grants}, and `swarm_card_pace` sets a project's pace from the owner's words; both wait for the owner's approval "
                   "(on a pending answer call `approval_wait` with its id). {caps}; never pause running work to make room.")
_GRANTS = {"company": "a project may run", "alpha": "a project (or a whole company) may run"}


def caps_text(max_live_bodies: Optional[int], max_children_per_parent: Optional[int]) -> str:
    if max_live_bodies is None and max_children_per_parent is None:
        return "No hard cap on agents is set in the Swarm settings; a new agent waits only while the computer is pegged"
    total = f"{max_live_bodies} agents in all" if max_live_bodies is not None else "no cap in all"
    each = f"{max_children_per_parent} under one parent" if max_children_per_parent is not None else "no cap under one parent"
    return f"The hard caps in the Swarm settings are {total} and {each}"


def capacity_rules(rank: str) -> str:
    from src.core.swarm import settings as swarm_settings

    cfg = swarm_settings.read_current()
    return _CAPACITY_RULES.format(grants=_GRANTS[rank], caps=caps_text(cfg.max_live_bodies, cfg.max_children_per_parent))
WORK_RULES = ("Scope rule: do exactly the goal with the smallest change that meets it, and add no new test infrastructure "
              "(a browser, headless Chrome, a new framework) unless the goal asks for it.")


@dataclass(frozen=True)
class AgentDefinition:

    slug: str
    description: str
    rank: str
    effort: str
    memory: str
    brief: str
    display_name: str = ""


@dataclass(frozen=True)
class ParsedDefinition:

    name: str
    description: str
    model: str
    effort: str
    memory: str
    tools: Optional[Tuple[str, ...]]
    brief: str


@dataclass(frozen=True)
class SwarmMeta:

    slug: str
    display_name: str
    rank: str
    parent_slug: Optional[str] = None
    persona: str = ""
    naming_family: str = ""
    character_seed: str = ""


def tools_for_rank(rank: str) -> Optional[Tuple[str, ...]]:
    _check_rank(rank)
    return UPPER_TOOLS if rank in UPPER_RANKS else None


def rank_rules(rank: str) -> str:
    return (PROJECT_RULES if rank == "project" else WORK_RULES if rank in ("feature", "task") else capacity_rules(rank) if rank in _GRANTS
            else "")


def render_definition(d: AgentDefinition) -> str:
    _check_definition(d)
    refuse_secrets(d.brief, f".claude/agents/{d.slug}.md brief")
    refuse_secrets(d.description, f".claude/agents/{d.slug}.md description")
    lines = ["---", f"name: {d.slug}", f"description: {json.dumps(d.description)}",
             f"model: {MODEL}", f"effort: {d.effort}", f"memory: {d.memory}"]
    tools = tools_for_rank(d.rank)
    if tools is not None:
        lines.append(f"tools: {', '.join(tools)}")
    lines += ["---", "", d.brief.rstrip("\n"), ""]
    return "\n".join(lines)


def parse_definition(text: str) -> ParsedDefinition:
    m = re.match(r"\A---\n(.*?)\n---\n\n?(.*)\Z", text, re.DOTALL)
    if not m:
        raise SwarmFileError("definition has no frontmatter")
    meta: Dict[str, str] = {}
    for line in m.group(1).split("\n"):
        key, sep, raw = line.partition(": ")
        if not sep:
            raise SwarmFileError("definition frontmatter line has no value")
        meta[key] = _unquote(raw)
    try:
        tools = tuple(t.strip() for t in meta["tools"].split(",")) if "tools" in meta else None
        return ParsedDefinition(name=meta["name"], description=meta["description"],
                                model=meta["model"], effort=meta["effort"],
                                memory=meta["memory"], tools=tools,
                                brief=m.group(2).rstrip("\n"))
    except KeyError as exc:
        raise SwarmFileError(f"definition frontmatter lacks {exc.args[0]}") from exc


def render_codex_twin(d: AgentDefinition) -> str:
    _check_definition(d)
    refuse_secrets(d.description, f".codex/agents/{d.slug}.toml description")
    mem = _memory_rel(d.slug, d.memory)
    who = d.display_name or d.slug
    pointer = (f"You are {who}. Read {mem}/MEMORY.md first, then your brief in "
               f".claude/agents/{d.slug}.md.")
    refuse_secrets(pointer, f".codex/agents/{d.slug}.toml developer_instructions")
    return (f"name = {_toml_str(d.slug)}\ndescription = {_toml_str(d.description)}\n"
            f"developer_instructions = {_toml_str(pointer)}\n")


def is_swarm_definition(repo: Path, slug: str, path: Path) -> bool:
    if not path.exists() and not path.is_symlink():
        return True
    for scope in (SCOPE_PROJECT, SCOPE_LOCAL):
        try:
            if json.loads((Path(repo) / _memory_rel(slug, scope) / "swarm.json").read_text(encoding="utf-8")).get("slug") == slug:
                return True
        except (OSError, ValueError, AttributeError):
            continue
    return False


def parse_codex_twin(text: str) -> Dict[str, str]:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SwarmFileError("codex twin is not valid TOML") from exc
    for key in ("name", "description", "developer_instructions"):
        if not isinstance(data.get(key), str):
            raise SwarmFileError(f"codex twin lacks {key}")
    return {k: data[k] for k in ("name", "description", "developer_instructions")}


def render_swarm_json(meta: SwarmMeta) -> str:
    require_slug(meta.slug)
    _check_rank(meta.rank)
    if meta.parent_slug is not None:
        require_slug(meta.parent_slug)
    body = {"schema": SWARM_JSON_SCHEMA, "slug": meta.slug, "display_name": meta.display_name,
            "rank": meta.rank, "parent_slug": meta.parent_slug, "persona": meta.persona,
            "naming_family": meta.naming_family, "character_seed": meta.character_seed}
    text = json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    refuse_secrets(text, f"swarm.json {meta.slug}")
    return text


def parse_swarm_json(text: str) -> SwarmMeta:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SwarmFileError("swarm.json is not valid JSON") from exc
    if not isinstance(data, dict) or data.get("schema") != SWARM_JSON_SCHEMA:
        raise SwarmFileError("swarm.json has an unknown schema")
    try:
        meta = SwarmMeta(slug=data["slug"], display_name=data["display_name"],
                        rank=data["rank"], parent_slug=data.get("parent_slug"),
                        persona=data.get("persona", ""),
                        naming_family=data.get("naming_family", ""),
                        character_seed=data.get("character_seed", ""))
    except KeyError as exc:
        raise SwarmFileError(f"swarm.json lacks {exc.args[0]}") from exc
    require_slug(meta.slug)
    _check_rank(meta.rank)
    if meta.parent_slug is not None:
        require_slug(meta.parent_slug)
    return meta


def render_settings(memory_dir: Path, rank: str = "project") -> str:
    _check_rank(rank)
    if not Path(memory_dir).is_absolute():
        raise SwarmFileError("settings need an absolute memory folder")
    deny = list(FILE_WRITE_TOOLS) + (list(denied_create_tools()) if rank in ("company", "alpha") else [])
    return json.dumps({"permissions": {"allow": ["mcp__carnivore"], "deny": deny}, "crossSessionInbound": "accept"}, indent=2) + "\n"


def exclude_lines(slug: str) -> List[str]:
    require_slug(slug)
    return [f"/.claude/agents/{slug}.md", f"/.codex/agents/{slug}.toml",
            f"/.claude/agent-memory-local/{slug}/"]


def exclude_file(repo: Path) -> Path:
    if not git_guard.git_available():
        raise SwarmFileError("git is not installed on this machine")
    out = subprocess.run(["git", "-C", str(repo), "rev-parse", "--git-path", "info/exclude"],
                         capture_output=True, text=True, check=False, timeout=15)
    if out.returncode != 0 or not out.stdout.strip():
        raise SwarmFileError("folder is not a git repository")
    path = Path(out.stdout.strip())
    return path if path.is_absolute() else Path(repo) / path


def add_exclude_lines(repo: Path, slug: str) -> None:
    path = exclude_file(repo)
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    have = set(current.splitlines())
    missing = [ln for ln in exclude_lines(slug) if ln not in have]
    if missing:
        sep = "" if not current or current.endswith("\n") else "\n"
        atomic_write(path, current + sep + "\n".join(missing) + "\n")


def remove_exclude_lines(repo: Path, slug: str) -> None:
    path = exclude_file(repo)
    if not path.exists():
        return
    drop = set(exclude_lines(slug))
    kept = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln not in drop]
    atomic_write(path, "\n".join(kept) + ("\n" if kept else ""))


def _memory_rel(slug: str, memory: str) -> str:
    return (f".claude/agent-memory/{slug}" if memory == SCOPE_PROJECT
            else f".claude/agent-memory-local/{slug}")


def _check_rank(rank: str) -> None:
    if rank not in RANKS:
        raise SwarmFileError("unknown rank")


def _check_definition(d: AgentDefinition) -> None:
    require_slug(d.slug)
    _check_rank(d.rank)
    if d.effort not in EFFORTS:
        raise SwarmFileError("unknown effort level")
    if d.memory not in (SCOPE_PROJECT, SCOPE_LOCAL):
        raise SwarmFileError("memory scope must be project or local")
    if (d.memory == SCOPE_LOCAL) != (d.rank == "task"):
        raise SwarmFileError("local memory is for task agents only")
    if "\n" in d.description or "\r" in d.description:
        raise SwarmFileError("description must be one line")


def _unquote(raw: str) -> str:
    if raw.startswith('"'):
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SwarmFileError("bad quoted frontmatter value") from exc
    return raw


def _toml_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")
