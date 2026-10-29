
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

DEFAULT_FAMILY = "claude"

INTERACTIVE_SHELL = '"${SHELL:-/bin/sh}" -i'


@dataclass(frozen=True)
class AgentFamily:

    name: str
    label: str
    sources_zshrc: bool
    reserved: bool
    pickable: bool
    description: str
    default_wrapper_id: str
    default_label: str
    default_script: str
    needs_model: bool = False
    default_accepts_model: bool = False
    seeded: bool = True


AGENT_FAMILIES: Tuple[AgentFamily, ...] = (
    AgentFamily(
        name="claude",
        label="claude",
        sources_zshrc=True,
        reserved=False,
        pickable=True,
        description="claude code sessions.",
        default_wrapper_id="claude",
        default_label="claude",
        default_script='command claude --dangerously-skip-permissions "$@"',
    ),
    AgentFamily(
        name="codex",
        label="codex",
        sources_zshrc=True,
        reserved=True,
        pickable=True,
        description="codex cli sessions.",
        default_wrapper_id="codex-default",
        default_label="codex",
        default_script='codex "$@"',
    ),
    AgentFamily(
        name="hermes",
        label="hermes",
        sources_zshrc=True,
        reserved=True,
        pickable=True,
        description="hermes sessions.",
        default_wrapper_id="hermes-default",
        default_label="hermes",
        default_script='hermes "$@"',
    ),
    AgentFamily(
        name="openclaw",
        label="openclaw",
        sources_zshrc=True,
        reserved=True,
        pickable=True,
        description="openclaw sessions.",
        default_wrapper_id="openclaw-default",
        default_label="openclaw",
        default_script='openclaw tui "$@"',
    ),
    AgentFamily(
        name="local",
        label="local (lm studio)",
        sources_zshrc=True,
        reserved=True,
        pickable=True,
        needs_model=True,
        description="claude code against a local lm studio model.",
        default_wrapper_id="local-default",
        default_label="local (lm studio)",
        default_script='cldl "$@"',
        default_accepts_model=True,
    ),
    AgentFamily(
        name="custom",
        label="custom agent",
        sources_zshrc=True,
        reserved=False,
        pickable=False,
        seeded=False,
        description="any command-line agent the user names, with its own command and icon.",
        default_wrapper_id="custom-default",
        default_label="custom agent",
        default_script=f'exec {INTERACTIVE_SHELL} "$@"',
    ),
    AgentFamily(
        name="shell",
        label="shell",
        sources_zshrc=False,
        reserved=True,
        pickable=False,
        description="a plain console, no agent.",
        default_wrapper_id="shell-default",
        default_label="shell",
        default_script=f'exec {INTERACTIVE_SHELL} "$@"',
    ),
)

AGENT_FAMILY_BY_NAME: Dict[str, AgentFamily] = {f.name: f for f in AGENT_FAMILIES}

AGENT_FAMILY_NAMES: Tuple[str, ...] = tuple(f.name for f in AGENT_FAMILIES)

RESERVED_FAMILY_NAMES = frozenset(f.name for f in AGENT_FAMILIES if f.reserved)


def is_valid_family(name: str) -> bool:
    return name in AGENT_FAMILY_BY_NAME


def get_family(name: Optional[str]) -> AgentFamily:
    return AGENT_FAMILY_BY_NAME.get(name or "", AGENT_FAMILY_BY_NAME[DEFAULT_FAMILY])




def wrappers_for_family(wrappers: List, family_name: str) -> List:
    kept = []
    for w in wrappers:
        if isinstance(w, dict):
            name = w.get("family") or DEFAULT_FAMILY
        else:
            name = getattr(w, "family", None) or DEFAULT_FAMILY
        if name == family_name:
            kept.append(w)
    return kept


def resolve_agent_type(agent_type: Optional[str], wrappers: List) -> Tuple[AgentFamily, Optional[object]]:
    normalized = (agent_type or DEFAULT_FAMILY).lower()

    if normalized in RESERVED_FAMILY_NAMES:
        return AGENT_FAMILY_BY_NAME[normalized], None

    for w in wrappers:
        wid = w.get("id") if isinstance(w, dict) else getattr(w, "id", None)
        if wid == normalized:
            family_name = (
                w.get("family") if isinstance(w, dict) else getattr(w, "family", None)
            ) or DEFAULT_FAMILY
            return get_family(family_name), w

    return AGENT_FAMILY_BY_NAME[DEFAULT_FAMILY], None


def build_family_summaries(agents, resolve_command: Callable[[str], str]) -> List[dict]:
    wrappers = getattr(agents, "wrappers", []) or []
    summaries: List[dict] = []
    for family in AGENT_FAMILIES:
        own = wrappers_for_family(wrappers, family.name)
        summaries.append({
            "name": family.name,
            "label": family.label,
            "reserved": family.reserved,
            "pickable": family.pickable,
            "needs_model": family.needs_model,
            "description": family.description,
            "wrapper_count": len(own),
            "default_wrapper": _default_id(own),
            "effective_command": _effective_command(resolve_command, family),
        })
    return summaries


def _default_id(own: List) -> Optional[str]:
    def get(w, key):
        return w.get(key) if isinstance(w, dict) else getattr(w, key, None)

    for w in own:
        if get(w, "default"):
            return get(w, "id")
    return get(own[0], "id") if own else None


def _effective_command(resolve_command, family: AgentFamily) -> str:
    try:
        return resolve_command(family.name)
    except ValueError as exc:
        return f"(needs a model: {exc})"
    except Exception as exc:  # noqa: BLE001
        return f"(could not resolve: {exc})"
