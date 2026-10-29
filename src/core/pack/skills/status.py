
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Collection, Iterable, Mapping, Optional, Sequence

from src.core.pack.skills.receiver import DIFFERS, MISSING, Cell
from src.core.pack.skills.scan import RootScan

_HEX16 = re.compile(r"^[0-9a-f]{16}$")
_MAX_COUNT = 1_000_000
VOLATILE_KEYS = ("gen", "made_at")

OffRow = tuple[str, str, str]


def off_pairs(cells: Iterable[Cell], held_back: Collection[tuple[str, str, str]] = ()) -> list[OffRow]:
    return sorted((c.family, c.name, c.root.group) for c in cells
                  if c.state in (MISSING, DIFFERS) and (c.family, c.name, str(c.root.leaf)) not in held_back)


def block(gen: Optional[int], applied_gen: int, off: Sequence[OffRow], conflicts: int = 0) -> dict[str, Any]:
    digest = hashlib.sha256("\n".join("\0".join(row) for row in sorted(off)).encode("utf-8")).hexdigest()[:16]
    out: dict[str, Any] = {"applied_gen": applied_gen, "off_count": len(off), "off_digest": digest}
    if conflicts:
        out["conflict_count"] = conflicts
    if gen is not None:
        out["gen"] = gen
    return out


def clean_block(raw: Any) -> Optional[dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    applied, off, gen = raw.get("applied_gen"), raw.get("off_count"), raw.get("gen")
    conflicts = raw.get("conflict_count", 0)
    if not (type(conflicts) is int and 0 <= conflicts <= _MAX_COUNT):
        return None
    if not (type(applied) is int and 0 <= applied < _MAX_COUNT * 1000 and type(off) is int and 0 <= off <= _MAX_COUNT):
        return None
    if not (isinstance(raw.get("off_digest"), str) and _HEX16.match(raw["off_digest"])):
        return None
    if gen is not None and not (type(gen) is int and 0 <= gen < _MAX_COUNT * 1000):
        return None
    return {"applied_gen": applied, "off_count": off, "off_digest": raw["off_digest"], "gen": gen, "conflict_count": conflicts}


def content_key(doc: Mapping[str, Any]) -> str:
    return json.dumps({k: v for k, v in doc.items() if k not in VOLATILE_KEYS}, sort_keys=True, separators=(",", ":"))


def next_gen(own_last: int, reported: Iterable[int], minimum: int = 0) -> int:
    return max(own_last + 1, max(reported, default=-1) + 1, minimum, 1)


def reported_gens(blocks: Iterable[Optional[Mapping[str, Any]]]) -> list[int]:
    out: list[int] = []
    for item in blocks:
        if item:
            out += [int(item[k]) for k in ("gen", "applied_gen") if item.get(k) is not None]
    return out


def takeover_differences(accepted: Mapping[str, Any], scans: Mapping[str, RootScan], choices: Optional[Any] = None,
                         warez_here: Optional[Any] = None) -> int:
    count = 0
    catalog = set(warez_here.pairs) if warez_here is not None else set()
    if warez_here is not None:
        mine = {(e[0], e[1]): (e[2], e[4]) for e in warez_here.entries}
        count += sum(1 for e in accepted.get("warez", []) if mine.get((e[0], e[1])) != (e[2], e[4]))
        if choices is not None:
            known_refs = {(e[0], e[1]) for e in accepted.get("warez", [])}
            count += sum(1 for pair in mine if pair not in known_refs and choices.selects(*pair))
    if choices is not None:
        known = {(f, n) for f, n, _ in accepted.get("skills", [])}
        count += sum(1 for family, scan in scans.items() for name, found in scan.skills.items()
                     if found.problem is None and (family, name) not in known and (family, name) not in catalog and choices.selects(family, name))
    for family, name, digest in accepted.get("skills", []):
        scan = scans.get(family)
        found = scan.skills.get(name) if scan is not None else None
        if found is None or found.problem is not None or found.digest != digest:
            count += 1
    return count
