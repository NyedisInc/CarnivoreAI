
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Set

from src.core.agent_families import (
    AGENT_FAMILIES,
    AgentFamily,
    wrappers_for_family,
)

_FORWARDING_TOKENS = ('"$@"', "$@", "$1", "$*")

_TRANSPARENT_PREFIX = re.compile(r"^(?:command|exec)\s+")


def _id_of(wrapper) -> Optional[str]:
    return wrapper.get("id") if isinstance(wrapper, dict) else None


def unique_id(base: str, taken: Iterable[str]) -> str:
    used: Set[str] = set(taken)
    if base not in used:
        return base
    n = 2
    while f"{base}-{n}" in used:
        n += 1
    return f"{base}-{n}"


def script_from_command(family_name: str, command: str) -> str:
    """Turn a legacy one-line launch command into a forwarding wrapper script.
    """
    text = command.strip()
    if any(token in text for token in _FORWARDING_TOKENS):
        return text
    if family_name == "codex":
        head, _, rest = text.partition(" ")
        return f'{head} "$@"' + (f" {rest.strip()}" if rest.strip() else "")
    return f'{text} "$@"'


def same_launch(command: str, script: str) -> bool:
    def norm(text: str) -> Optional[str]:
        text = (text or "").strip()
        if not text or "\n" in text:
            return None
        text = _TRANSPARENT_PREFIX.sub("", text)
        text = text.replace('"$@"', " ").replace("$@", " ")
        return " ".join(text.split())

    a, b = norm(command), norm(script)
    return a is not None and a == b


def standard_wrapper(family: AgentFamily, taken: Iterable[str]) -> dict:
    return {
        "id": unique_id(family.default_wrapper_id, taken),
        "family": family.name,
        "label": family.default_label,
        "script": family.default_script,
        "entry": None,
        "description": (
            f"the standard {family.name} launch. edit it to change what new "
            f"{family.name} sessions run."
        ),
        "default": True,
        "accepts_model": family.default_accepts_model,
        "icon": None,
    }


def ensure_family_defaults(wrappers: List) -> List:
    result = [dict(w) if isinstance(w, dict) else w for w in wrappers]
    dicts = [w for w in result if isinstance(w, dict)]
    for family in AGENT_FAMILIES:
        own = wrappers_for_family(dicts, family.name)
        if not own:
            seeded = standard_wrapper(family, (_id_of(w) for w in result))
            result.append(seeded)
            dicts.append(seeded)
            continue
        flagged = [w for w in own if w.get("default")]
        keep = flagged[0] if flagged else own[0]
        for w in own:
            if bool(w.get("default")) != (w is keep):
                w["default"] = w is keep
    return result
