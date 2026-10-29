
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import FrozenSet, Iterable, List, Optional, Sequence, Tuple

from src.config.mcp_launch import APP_INJECTED_CLAUDE_FLAGS
from src.core.agent_families import DEFAULT_FAMILY
from src.core.db_models import SESSION_FAMILY_SOURCE_INFERRED_PROCESS

INFER_UNAVAILABLE: str = "unavailable"

INFER_NOT_CLAUDE: str = "not_claude"

INFER_WRAPPER: str = "wrapper"

INFER_FAMILY: str = "family"

INFER_OUTCOMES: Tuple[str, ...] = (
    INFER_UNAVAILABLE,
    INFER_NOT_CLAUDE,
    INFER_WRAPPER,
    INFER_FAMILY,
)

PER_RUN_FLAGS: FrozenSet[str] = frozenset(
    {"--resume", "--fork-session", "--name", "--model", "--continue",
     "--agent", "--effort", "--settings", "--tools", "--setting-sources", "--strict-mcp-config", "--add-dir",
     "--no-chrome"}
) | APP_INJECTED_CLAUDE_FLAGS

_FLAG_RE = re.compile(r"--[A-Za-z][A-Za-z0-9-]*")

_CLAUDE_INVOCATION_RE = re.compile(r"(?:^|[;&|(`\s])(?:command\s+)?claude\b")

CLAUDE_FAMILY: str = DEFAULT_FAMILY


@dataclass(frozen=True)
class AgentInference:

    outcome: str
    agent_type: Optional[str] = None
    family_source: Optional[str] = None
    candidates: Tuple[str, ...] = ()
    detail: str = ""


UNAVAILABLE = AgentInference(
    INFER_UNAVAILABLE,
    detail="no process evidence could be read for this pane",
)


def flag_signature(command_line: Optional[str]) -> FrozenSet[str]:
    if not command_line:
        return frozenset()
    return strip_per_run_flags(match.group(0) for match in _FLAG_RE.finditer(command_line))


def strip_per_run_flags(flags: Iterable[str]) -> FrozenSet[str]:
    return frozenset({str(flag).lower() for flag in flags} - PER_RUN_FLAGS)


def wrapper_flag_signature(wrapper) -> FrozenSet[str]:
    if isinstance(wrapper, dict):
        script = wrapper.get("script")
    else:
        script = getattr(wrapper, "script", None)
    if not script:
        return frozenset()

    flags: set = set()
    for line in str(script).splitlines():
        match = _CLAUDE_INVOCATION_RE.search(line)
        if match is None:
            continue
        flags |= flag_signature(line[match.start():])
    return frozenset(flags)


def _wrapper_id(wrapper) -> Optional[str]:
    raw = wrapper.get("id") if isinstance(wrapper, dict) else getattr(wrapper, "id", None)
    text = str(raw).strip() if raw else ""
    return text or None


def _is_claude_family(wrapper) -> bool:
    if isinstance(wrapper, dict):
        family = wrapper.get("family")
    else:
        family = getattr(wrapper, "family", None)
    name = str(family).strip().lower() if family else ""
    return (name or CLAUDE_FAMILY) == CLAUDE_FAMILY


def matching_wrapper_ids(
    observed: FrozenSet[str], wrappers: Sequence
) -> Tuple[str, ...]:
    if not observed:
        return ()
    matched: List[str] = []
    for wrapper in wrappers or ():
        wid = _wrapper_id(wrapper)
        if not wid or not _is_claude_family(wrapper):
            continue
        if wrapper_flag_signature(wrapper) == observed:
            matched.append(wid)
    return tuple(matched)


def resolve_agent_inference(
    *,
    claude_argv: Optional[str],
    pane_current_command: Optional[str],
    process_table_read: bool,
    wrappers: Sequence,
) -> AgentInference:
    if not process_table_read:
        return UNAVAILABLE

    if not claude_argv:
        current = (pane_current_command or "").strip()
        if current.rsplit("/", 1)[-1].lower() == "claude":
            return AgentInference(
                INFER_FAMILY,
                agent_type=CLAUDE_FAMILY,
                family_source=SESSION_FAMILY_SOURCE_INFERRED_PROCESS,
                detail=(
                    "the pane's own foreground command is claude, but no "
                    "command line was readable, so no wrapper can be named"
                ),
            )
        return AgentInference(
            INFER_NOT_CLAUDE,
            detail=(
                "the process table was read and this pane's tree contains "
                "no claude process"
            ),
        )

    observed = flag_signature(claude_argv)
    matched = matching_wrapper_ids(observed, wrappers)

    if len(matched) == 1:
        return AgentInference(
            INFER_WRAPPER,
            agent_type=matched[0],
            family_source=SESSION_FAMILY_SOURCE_INFERRED_PROCESS,
            candidates=matched,
            detail=(
                f"the running claude passes exactly the flags wrapper "
                f"{matched[0]!r} passes"
            ),
        )

    if not observed:
        why = (
            "the running claude carries no distinguishing flag, so no "
            "wrapper can be told from any other"
        )
    elif not matched:
        why = (
            "the running claude's flags match no configured wrapper, so "
            "only the family can be claimed"
        )
    else:
        why = (
            f"{len(matched)} configured wrappers pass exactly these flags, "
            f"so naming one would be a coin flip"
        )
    return AgentInference(
        INFER_FAMILY,
        agent_type=CLAUDE_FAMILY,
        family_source=SESSION_FAMILY_SOURCE_INFERRED_PROCESS,
        candidates=matched,
        detail=why,
    )


def restart_agent_type(
    agent_type: Optional[str], agent_family_source: Optional[str]
) -> Optional[str]:
    source = (agent_family_source or "").strip()
    if source == SESSION_FAMILY_SOURCE_INFERRED_PROCESS:
        return None
    return agent_type
