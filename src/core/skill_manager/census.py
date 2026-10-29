
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

WINDOWS = (7, 30, 90)


def cutoffs_for(now: datetime, days: Sequence[int]) -> List[str]:
    return [(now - timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%S") for d in days]


def project_marker(project_path: str) -> str:
    return "/projects/" + re.sub(r"[^A-Za-z0-9]", "-", project_path) + "/"


def build_census(inventory: Dict[str, Any], by_skill: Optional[Dict[str, List[int]]]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for group in inventory["skills"]:
        locs = group["locations"]
        counts = None if by_skill is None else by_skill.get(group["name"], [0] * len(WINDOWS))
        rows.append({
            "name": group["name"],
            "harnesses": sorted({loc["harness"] for loc in locs}),
            "scopes": sorted({loc["scope"] for loc in locs}),
            "locations": len(locs),
            "states": {loc["harness"]: loc["state"] for loc in reversed(locs) if loc["shadowed_by"] is None},
            "tokens_est": max((loc["description_tokens_est"] for loc in locs), default=0),
            "fires": None if counts is None else {f"d{d}": counts[i] for i, d in enumerate(WINDOWS)},
        })
    return {
        "state": "not_measured" if by_skill is None else "measured",
        "tokens_label": inventory.get("tokens_label", "est."),
        "windows": list(WINDOWS),
        "context": inventory["context"],
        "skills": rows,
    }
