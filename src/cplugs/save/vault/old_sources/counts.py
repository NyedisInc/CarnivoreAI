
from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any, Dict, List

from src.cplugs.save.vault.old_sources import extras as extras_mod, labels, plan as plan_mod
from src.cplugs.save.vault.old_sources.attribution import NO_PROJECT_GROUP

_LABEL_KINDS = ("junk-", "trash-", "review-", "kept-by-tree-", "secrets-flagged")


def fingerprint(plan: plan_mod.Plan, extra_files: List[extras_mod.ExtraFile]) -> str:
    rows = sorted([p.unit, p.kind, sorted((f.rel, f.copy.sha256) for f in p.files)] for p in plan.points)
    parts: Dict[str, Any] = {"points": rows, "extras": sorted(extras_mod.fingerprint_part(extra_files))}
    if plan.only_points is not None:
        parts["only_points"] = [list(pair) for pair in plan.only_points]
    body = json.dumps(parts, sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def summarize(plan: plan_mod.Plan, extra_files: List[extras_mod.ExtraFile]) -> Dict[str, Any]:
    buckets = Counter(d.decision.split(":")[0] if not d.decision.startswith(plan_mod.SKIP_PREFIX) else d.decision for d in plan.decisions)
    label_counts: Counter = Counter()
    for point in plan.points:
        if point.kind != "current":
            continue
        kinds = {k for lab in point.labels for k in _LABEL_KINDS if lab.startswith(k)}
        label_counts.update(kinds or {"none"})
    units = {p.unit for p in plan.points}
    return {
        "copies": {"total": len(plan.decisions), **dict(sorted(buckets.items()))},
        "points": {"total": len(plan.points), "current": sum(p.kind == "current" for p in plan.points),
                   "kept": sum(p.kind == "kept" for p in plan.points)},
        "conversations": {"to_import": len(units), "shared_id_units": sum("@" in u for u in units)},
        "files": sum(len(p.files) for p in plan.points), "bytes": sum(p.bytes for p in plan.points),
        "families": dict(Counter(p.family for p in plan.points if p.kind == "current")),
        "labels": dict(sorted(label_counts.items())),
        "hidden_from_search": sum(labels.is_hidden(p.labels) for p in plan.points),
        "no_project": sum(p.tags.get("group") == NO_PROJECT_GROUP for p in plan.points if p.kind == "current"),
        "attribution": dict(Counter(str(p.tags.get("attribution")) for p in plan.points if p.kind == "current")),
        "refused": {"total": len(plan.refused), "first": [{"source": r.source, "locator": r.locator, "reason": r.reason}
                                                         for r in plan.refused[:20]]},
        "skipped": dict(Counter(r.reason for r in plan.skipped)),
        "extras": {"files": len(extra_files), "bytes": sum(f.length for f in extra_files), "unit": extras_mod.UNIT if extra_files else None},
    }
