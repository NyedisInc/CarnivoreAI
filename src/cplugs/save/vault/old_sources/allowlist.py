
from __future__ import annotations

from dataclasses import replace
from typing import Iterable, List, Set, Tuple

from src.cplugs.save.vault.old_sources import plan as plan_mod

NOT_SELECTED = plan_mod.SKIP_PREFIX + "not_selected"
MAX_POINTS = 5000
PointKey = Tuple[str, str]


class AllowListError(ValueError):

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def normalize(raw: object) -> List[PointKey]:
    if not isinstance(raw, (list, tuple)) or len(raw) > MAX_POINTS:
        raise AllowListError("bad_allow_list", f"only_points is a list of at most {MAX_POINTS} {{id, point_id}} entries")
    pairs: Set[PointKey] = set()
    for entry in raw:
        unit, point = (entry.get("id"), entry.get("point_id")) if isinstance(entry, dict) else (None, None)
        if not (isinstance(unit, str) and isinstance(point, str) and unit and point):
            raise AllowListError("bad_allow_list", "every only_points entry needs a non-empty string id and point_id")
        pairs.add((unit, point))
    return sorted(pairs)


def restrict(plan: plan_mod.Plan, only: Iterable[PointKey]) -> None:
    wanted = set(only)
    known = {(p.unit, p.point_id) for p in plan.points}
    unknown = sorted(wanted - known)
    if unknown:
        shown = ", ".join(f"{u}/{p}" for u, p in unknown[:5])
        raise AllowListError("unknown_point", f"{len(unknown)} listed point(s) are not in the plan, e.g. {shown}; preview the sources again")
    plan.points = [p for p in plan.points if (p.unit, p.point_id) in wanted]
    plan.decisions = [replace(d, decision=NOT_SELECTED, unit="", point_id="") if d.point_id and (d.unit, d.point_id) not in wanted else d
                      for d in plan.decisions]
    plan.only_points = sorted(wanted)
