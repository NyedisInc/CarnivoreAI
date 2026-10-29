
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List

HEADINGS = ("sessions", "crosstalk", "task_manager", "swarm", "projects", "pack", "automations", "ui", "notifications", "ai",
            "conversations", "usage", "system")
MAX_ID_CHARS = 160
MAX_SEGMENTS = 8
MIN_SEGMENTS = 2
MAX_SUMMARY_CHARS = 240
_SEGMENT = re.compile(r"[a-z][a-z0-9_]{0,31}")


@dataclass(frozen=True)
class Capability:

    name: str
    id: str
    summary: str

    @property
    def heading(self) -> str:
        return self.id.split(".")[0]

    @property
    def sub_heading(self) -> str:
        parts = self.id.split(".")
        return parts[1] if len(parts) > MIN_SEGMENTS else parts[0]


def id_problems(capability_id: str) -> List[str]:
    out = []
    parts = capability_id.split(".")
    if not MIN_SEGMENTS <= len(parts) <= MAX_SEGMENTS:
        out.append(f"{capability_id}: {len(parts)} segments, needs {MIN_SEGMENTS} to {MAX_SEGMENTS}")
    if len(capability_id) > MAX_ID_CHARS:
        out.append(f"{capability_id}: longer than {MAX_ID_CHARS} characters")
    out += [f"{capability_id}: segment {p!r} is not [a-z][a-z0-9_]{{0,31}}" for p in parts if not _SEGMENT.fullmatch(p)]
    if parts[0] not in HEADINGS:
        out.append(f"{capability_id}: heading {parts[0]!r} is not one of the 13")
    return out


def problems(capabilities: Iterable[Capability]) -> List[str]:
    caps = list(capabilities)
    out: List[str] = []
    seen: dict = {}
    for cap in caps:
        out += [f"{cap.name}: {p}" for p in id_problems(cap.id)]
        if not 1 <= len(cap.summary) <= MAX_SUMMARY_CHARS:
            out.append(f"{cap.name}: summary is {len(cap.summary)} characters, needs 1 to {MAX_SUMMARY_CHARS}")
        if cap.id in seen:
            out.append(f"{cap.name}: id {cap.id} is also {seen[cap.id]}'s")
        seen.setdefault(cap.id, cap.name)
    namespaces = {".".join(c.id.split(".")[:i]) for c in caps for i in range(1, len(c.id.split(".")))}
    out += [f"{c.name}: id {c.id} is also a namespace of another id" for c in caps if c.id in namespaces]
    return out
