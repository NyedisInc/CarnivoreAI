"""The agent-family registry: one table, no if/elif chains.

feat/universal-wrappers - wrappers used to be a claude-only concept. A
wrapper now declares which COMMAND FAMILY it wraps (``AgentWrapper.family``),
and one settings screen administers every family. Adding a sixth family must
be a DATA addition to ``AGENT_FAMILIES`` below and nothing else: no new
branch anywhere, no new key in a dict literal that someone forgets to
update. Everything downstream (resolution, the settings summary, the UI
grouping, wrapper-id validation) iterates this tuple.

The old shape this replaces was a dict literal inside
``Settings.get_agent_command``::

    {"codex": agents.codex_command, "hermes": agents.hermes_command, ...}[normalized]

which had to be edited in lockstep with ``RESERVED_AGENT_TYPES``, with
``AgentsConfig``'s fields, and with the settings summary. Three places, no
compiler to catch a miss.

``sources_zshrc`` is still a column, and it now governs how a WRAPPER is
rendered (``render_wrapper_invocation(source_rc=...)``):

* every agent CLI family sources ``~/.zshrc`` before the wrapper runs,
  because tmux's pane shell reads no rc and a version-managed binary or
  an rc-defined function (``keyc``) is not on PATH without it;
* ``shell`` does NOT: its wrapper execs an INTERACTIVE ``$SHELL``, which
  reads the rc itself. Sourcing it first as well would run the rc twice.

RESERVED NAMES, and the agent_type disambiguation this module encodes
--------------------------------------------------------------------
``Session.agent_type`` stores EITHER a wrapper id (``"keyc"``) OR a bare
family name (``"shell"``). ``resolve_agent_type`` is the single place that
disambiguates the two, and the ORDER is load-bearing for backward
compatibility. See its docstring.

``RESERVED_FAMILY_NAMES`` is deliberately NOT every family name: it excludes
``claude``. A config seeded by the v0->v1 migration can contain a wrapper
whose id is literally ``"claude"`` (``build_seed_wrappers`` authors one), and
that wrapper must stay reachable by id. Reserving the name would have made
``agent_type="claude"`` resolve to the family default instead of to that
specific wrapper, silently changing which script runs on a machine whose
default wrapper is something else. See ``resolve_agent_type``.
"""

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
