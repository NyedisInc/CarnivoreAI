
from __future__ import annotations

from typing import Any, Iterable, Mapping

from scripts.widgets.harness import Render

PASS, FAIL, UNSUPPORTED = "pass", "fail", "unsupported"
RED_RULES = frozenset({"overflow-x", "overflow-y", "scrollbar-x", "clipped-text", "clipped", "escape", "overlap"})
MAX_CELL_REASONS = 6
GLANCE_HOST, GLANCE_SIZE, POPOUT_HOST = "glance", "glance", "popout"


def host_of(render: Render) -> str:
    return GLANCE_HOST if render.zone == "drawer" and render.size == GLANCE_SIZE else render.zone


def render_failures(render: Render) -> list[str]:
    where = f"{render.key} {render.zone}/{render.size}/{render.fixture}/{render.theme}"
    reasons = [f"{where}: draw error: {render.error}"] if render.error else []
    reasons += [f"{where}: console error: {line}" for line in render.console]
    reasons += [f"{where}: {f['rule']}: {f['detail']}"[:300] for f in render.findings]
    return reasons


def run_verdict(render: Render) -> dict[str, Any]:
    reasons = render_failures(render)
    red = bool(render.error) or any(f["rule"] in RED_RULES for f in render.findings)
    return {"verdict": FAIL if reasons else PASS, "reasons": reasons, "red": red}


def unsupported_run(widget: str, host: str, size: str, why: str) -> dict[str, Any]:
    return {"verdict": UNSUPPORTED, "reasons": [f"{widget} {host}/{size}: {why}"], "red": False}


def cells_of(renders: Iterable[Render], declared_hosts: Iterable[str], missing: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    cells: dict[tuple[str, str], dict[str, Any]] = {}
    for render in renders:
        cell = cells.setdefault((host_of(render), render.size), {"host": host_of(render), "size": render.size, "verdict": PASS, "draws": 0,
                                                                 "themes": set(), "fixtures": set(), "red": False, "reasons": []})
        verdict = run_verdict(render)
        cell["draws"] += 1
        cell["themes"].add(render.theme)
        cell["fixtures"].add(render.fixture)
        cell["red"] = cell["red"] or verdict["red"]
        if verdict["verdict"] == FAIL:
            cell["verdict"] = FAIL
            cell["reasons"] += [r for r in verdict["reasons"] if r not in cell["reasons"]]
    for pair, why in (missing or {}).items():
        host, _, size = pair.partition("/")
        cells.setdefault((host, size), {"host": host, "size": size, "verdict": FAIL, "draws": 0, "themes": set(), "fixtures": set(),
                                        "red": False, "reasons": [why]})
    if POPOUT_HOST in declared_hosts:
        for (host, size), cell in list(cells.items()):
            if host == "home":
                cells[(POPOUT_HOST, size)] = {**cell, "host": POPOUT_HOST, "themes": set(cell["themes"]), "fixtures": set(cell["fixtures"]),
                                              "reasons": list(cell["reasons"])}
    out = []
    for key in sorted(cells):
        cell = cells[key]
        out.append({**cell, "themes": sorted(cell["themes"]), "fixtures": sorted(cell["fixtures"]), "reasons": cell["reasons"][:MAX_CELL_REASONS]})
    return out
