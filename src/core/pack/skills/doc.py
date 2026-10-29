
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Collection, Mapping, Optional, Sequence

from src.core.pack.skills import rules
from src.core.pack.skills.scan import RootScan

DOC_VERSION = 1
RETENTION_SECONDS = 30 * 24 * 3600
MODES = ("off", "some", "all")

Pair = tuple[str, str]


@dataclass(frozen=True)
class Choices:

    mode: str = "off"
    include: frozenset[Pair] = frozenset()
    exclude: frozenset[Pair] = frozenset()

    def selects(self, family: str, name: str) -> bool:
        pair = (family, name)
        if self.mode == "all":
            return pair not in self.exclude
        return self.mode == "some" and pair in self.include


@dataclass(frozen=True)
class BuildResult:

    document: Optional[dict[str, Any]]
    problem: Optional[str] = None


def _budget(scans: Mapping[str, RootScan], choices: Choices, skip: Collection[Pair] = ()) -> dict[Pair, str]:
    over: dict[Pair, str] = {}
    size = count = 0
    for family in sorted(scans):
        for name, skill in sorted(scans[family].skills.items()):
            if skill.problem or (family, name) in skip or not choices.selects(family, name):
                continue
            add_bytes = sum(f.size for f in skill.files)
            if size + add_bytes > rules.MAX_SET_BYTES or count + len(skill.files) > rules.MAX_SET_FILES:
                over[(family, name)] = rules.REASON_TOO_LARGE
            else:
                size += add_bytes
                count += len(skill.files)
    return over


def _live(entries: Sequence[Sequence[Any]], now: int, skipping: set[Pair]) -> list[list[Any]]:
    kept = {(e[0], e[1]): [e[0], e[1], e[2]] for e in entries if now - int(e[2]) < RETENTION_SECONDS and (e[0], e[1]) not in skipping}
    return sorted(kept.values())


def build_document(
    *,
    alpha: str,
    gen: int,
    made_at: int,
    choices: Choices,
    scans: Mapping[str, RootScan],
    previous: Optional[Mapping[str, Any]] = None,
    removals: Sequence[Sequence[Any]] = (),
    unsynced: Sequence[Sequence[Any]] = (),
    warez: Sequence[Sequence[str]] = (),
    catalog_held: Sequence[Sequence[str]] = (),
    catalog_pairs: Collection[Pair] = (),
) -> BuildResult:
    for scan in scans.values():
        if not scan.healthy:
            return BuildResult(None, scan.why)
    over = _budget(scans, choices, catalog_pairs)
    skills: list[list[Any]] = []
    held: list[list[Any]] = []
    for family in sorted(scans):
        found = scans[family].skills
        for name, skill in sorted(found.items()):
            if not choices.selects(family, name) or (family, name) in catalog_pairs:
                continue
            reason = skill.problem or over.get((family, name))
            if reason:
                held.append([family, name, reason])
            else:
                skills.append([family, name, skill.digest])
    refs = sorted([list(e) for e in warez if choices.selects(e[0], e[1])])
    held += [list(h) for h in catalog_held if choices.selects(h[0], h[1])]
    if len(skills) + len(refs) > rules.MAX_SKILLS:
        return BuildResult(None, f"too many synced skills ({rules.MAX_SKILLS} max)")
    wanted: set[Pair] = set(choices.include) if choices.mode == "some" else set()
    for family, name, *_ in [*(previous or {}).get("skills", []), *(previous or {}).get("warez", [])]:
        wanted.add((family, name))
    for family, name in sorted(wanted):
        if family in scans and choices.selects(family, name) and name not in scans[family].skills and (family, name) not in catalog_pairs:
            held.append([family, name, rules.REASON_MISSING_ON_ALPHA])
    synced = {(f, n) for f, n, _ in skills} | {(e[0], e[1]) for e in refs}
    document = {
        "v": DOC_VERSION,
        "alpha": alpha,
        "gen": gen,
        "made_at": made_at,
        "choices": {
            "mode": choices.mode,
            "include": sorted([list(p) for p in choices.include]),
            "exclude": sorted([list(p) for p in choices.exclude]),
        },
        "skills": skills,
        "warez": refs,
        "removals": _live(removals, made_at, synced),
        "unsynced": _live(unsynced, made_at, set()),
        "held": sorted(held),
    }
    if len(json.dumps(document, separators=(",", ":")).encode("utf-8")) > rules.MAX_DOC_BYTES:
        return BuildResult(None, f"too many synced skills ({rules.MAX_SKILLS} max)")
    return BuildResult(document)
