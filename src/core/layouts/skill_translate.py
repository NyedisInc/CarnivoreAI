from __future__ import annotations

import re
from typing import Any, Dict, FrozenSet, Optional

FAMILY_SIGIL: Dict[str, str] = {"claude": "/", "codex": "$"}

_LEADING = re.compile(r"^([/$])([A-Za-z0-9][A-Za-z0-9_.:-]*)(?=\s|$)")


def family_of(info: Any) -> Optional[str]:
    family = getattr(info, "agent_family", None)
    return family if family in FAMILY_SIGIL else None


def translate(text: str, family: Optional[str], skill_names: FrozenSet[str]) -> str:
    sigil = FAMILY_SIGIL.get(family or "")
    match = _LEADING.match(text)
    if sigil is None or match is None or match.group(1) == sigil:
        return text
    if match.group(2) not in skill_names:
        return text
    return sigil + text[1:]
