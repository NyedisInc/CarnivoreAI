
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from src.cplugs.save.vault import constants as K
from src.cplugs.save.vault import manifest

EXPORT_SUFFIX = re.compile(r"@\d{8}T\d{6}Z-m\d+(?=\.jsonl$)")
_UUID = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
_AGENT_FILE = re.compile(r"agent-[0-9a-f]+")
KIND_MAIN, KIND_SUB = "main", "sub"


@dataclass(frozen=True)
class Ident:

    conv: str
    family: str
    kind: str
    parent: str
    enc: str
    rel: str
    role: str


def strip_export_suffix(name: str) -> str:
    return EXPORT_SUFFIX.sub("", name)


def is_appledouble(path: str) -> bool:
    return path.rsplit("/", 1)[-1].startswith("._")


_PROJECTS = re.compile(r"(?:^|[/#])projects/")


def after_projects(path: str) -> str:
    found = list(_PROJECTS.finditer(path))
    return path[found[-1].end():] if found else path


def classify(path: str) -> Optional[Ident]:
    found = _shape(path)
    if found is None:
        return None
    try:
        manifest.check_unit(found.conv)
        if found.parent:
            manifest.check_unit(found.parent)
    except manifest.ManifestError:
        return None
    return found


def _shape(path: str) -> Optional[Ident]:
    parts = [p for p in path.split("/") if p]
    if not parts or not parts[-1].endswith(".jsonl"):
        return None
    base = parts[-1]
    if base.startswith("rollout-") or parts[0] in ("codex-sessions", "sessions", "archived_sessions"):
        found = _UUID.findall(base)
        if not found:
            return None
        folder = "archived_sessions" if "archived_sessions" in parts else "sessions"
        tail = parts[parts.index(folder) + 1:] if folder in parts else parts[1:] if parts[0] == "codex-sessions" else parts
        return Ident(found[-1], "codex", KIND_MAIN, "", "", f"{folder}/{'/'.join(tail)}", K.ROLE_CODEX_ROLLOUT)
    if "subagents" in parts and parts.index("subagents") >= 2:
        i = parts.index("subagents")
        return Ident(parts[i - 1], "claude", KIND_SUB, parts[i - 1], parts[i - 2], "projects/" + "/".join(parts), K.ROLE_SUBAGENT)
    if len(parts) == 2 and (_UUID.fullmatch(base[:-6]) or _AGENT_FILE.fullmatch(base[:-6])):
        return Ident(base[:-6], "claude", KIND_MAIN, "", parts[0], "projects/" + "/".join(parts), K.ROLE_TRANSCRIPT)
    return None


def file_id(path: str) -> Optional[str]:
    base = strip_export_suffix(path).rsplit("/", 1)[-1]
    if not base.endswith(".jsonl") or is_appledouble(path):
        return None
    stem = base[:-6]
    if _UUID.fullmatch(stem) or _AGENT_FILE.fullmatch(stem):
        return stem
    found = _UUID.findall(stem) if stem.startswith("rollout-") else []
    return found[-1] if found else None


def identify(path: str) -> Optional[Ident]:
    return classify(_without_container(after_projects(strip_export_suffix(path))))


_CODEX_ROOTS = ("codex-sessions", "sessions", "archived_sessions")


def _without_container(path: str) -> str:
    parts = path.split("/")
    if len(parts) == 3 and not parts[0].startswith("-") and parts[0] not in _CODEX_ROOTS and parts[1].startswith("-") and parts[2].endswith(".jsonl"):
        return "/".join(parts[1:])
    return path
