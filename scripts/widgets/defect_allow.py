
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from scripts.widgets.harness import REPO

ALLOWLIST = REPO / "tests" / "python" / "widgets" / "layout-defect-allowlist.json"
ANY = "*"


class AllowListError(Exception):
    pass


@dataclass(frozen=True)
class Allowance:

    widget: str
    size: str
    rule: str
    reason: str
    theme: str = ANY
    shape: str = ANY
    selector: str = ""
    todo: bool = False

    def covers_draw(self, draw: dict) -> bool:
        return all(mine in (ANY, theirs) for mine, theirs in (
            (self.widget, draw["key"]), (self.size, draw["size"]), (self.theme, draw["theme"]), (self.shape, draw["shape"])))

    def allows(self, draw: dict, finding: dict) -> bool:
        return (self.covers_draw(draw) and self.rule == finding["rule"]
                and (not self.selector or self.selector in finding["selector"]))


def load(path: Path = ALLOWLIST) -> list[Allowance]:
    raw = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"entries": []}
    out = []
    for index, entry in enumerate(raw.get("entries", [])):
        missing = [k for k in ("widget", "size", "rule", "reason") if not str(entry.get(k, "")).strip()]
        if missing:
            raise AllowListError(f"allow-list entry {index} lacks {', '.join(missing)}: {entry}")
        out.append(Allowance(**{k: entry[k] for k in Allowance.__dataclass_fields__ if k in entry}))
    return out


@dataclass
class Verdict:

    failing: list[tuple[dict, dict]]
    allowed: list[tuple[dict, dict, Allowance]]
    stale: list[Allowance]


def apply(draws: list[dict], entries: list[Allowance], judge_stale: bool = True) -> Verdict:
    failing: list[tuple[dict, dict]] = []
    allowed: list[tuple[dict, dict, Allowance]] = []
    used: set[Allowance] = set()
    for draw in draws:
        for finding in draw.get("findings", []):
            if finding["severity"] != "fail":
                continue
            entry = next((e for e in entries if e.allows(draw, finding)), None)
            if entry is None:
                failing.append((draw, finding))
            else:
                used.add(entry)
                allowed.append((draw, finding, entry))
    stale = [e for e in entries if judge_stale and e not in used and any(e.covers_draw(d) for d in draws)]
    return Verdict(failing=failing, allowed=allowed, stale=stale)
