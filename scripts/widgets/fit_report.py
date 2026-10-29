
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from scripts.widgets.harness import Render


def _where(render: Render) -> str:
    return f"{render.zone}/{render.size}/{render.fixture}/{render.theme}"


def group(renders: list[Render]) -> dict[str, dict]:
    out: dict[str, dict] = defaultdict(lambda: {"findings": {}, "errors": {}, "misses": set(), "draws": 0, "worst": 0})
    for render in renders:
        entry = out[render.key]
        entry["draws"] += 1
        entry["misses"].update(render.misses)
        if render.error:
            entry["errors"].setdefault(render.error, []).append(_where(render))
        for finding in render.findings:
            ident = (finding["rule"], finding["selector"])
            slot = entry["findings"].setdefault(ident, {**finding, "where": [], "shot": None, "max_px": 0})
            slot["where"].append(_where(render))
            if finding["px"] >= slot["max_px"]:
                slot["max_px"], slot["detail"] = finding["px"], finding["detail"]
                slot["shot"] = str(render.shot) if render.shot else slot["shot"]
            entry["worst"] = max(entry["worst"], finding["px"])
    return out


def merge_previous(out: Path, renders: list[Render]) -> list[Render]:
    store = out / "renders.json"
    if not store.is_file():
        return renders
    drawn = {r.key for r in renders}
    kept = [Render(**{**raw, "shot": Path(raw["shot"]) if raw.get("shot") else None})
            for raw in json.loads(store.read_text(encoding="utf-8")) if raw["key"] not in drawn]
    return kept + renders


def write_reports(out: Path, renders: list[Render], missing: list[str], elapsed: float) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    grouped = group(renders)
    failing = {k: v for k, v in grouped.items() if v["findings"] or v["errors"]}
    order = sorted(failing, key=lambda k: (-failing[k]["worst"], -len(failing[k]["findings"]), k))
    lines = ["# Widget fit check", "",
             f"{len(renders)} draws of {len(grouped)} widgets in {elapsed:.0f}s; "
             f"{sum(1 for r in renders if r.findings or r.error)} draws failing across {len(failing)} widgets.", ""]
    if missing:
        lines += ["## Widgets with no fixture", "", *[f"- `{k}`" for k in missing], ""]
    lines += ["## Failures by widget (worst overflow first)", ""]
    for key in order:
        entry = failing[key]
        lines += [f"### `{key}` (worst {entry['worst']}px, {len(entry['findings'])} findings)", ""]
        for error, where in entry["errors"].items():
            lines.append(f"- **draw error** {error} ({len(where)} draws: {', '.join(where[:4])})")
        for finding in sorted(entry["findings"].values(), key=lambda f: -f["max_px"]):
            where = finding["where"]
            lines.append(f"- **{finding['rule']}** {finding['detail']}  ")
            lines.append(f"  `{finding['selector']}`  ")
            lines.append(f"  in {len(where)} draws: {', '.join(where[:6])}{' ...' if len(where) > 6 else ''}"
                         + (f"  \n  shot: `{finding['shot']}`" if finding["shot"] else ""))
        if entry["misses"]:
            lines.append(f"- fixture misses: {', '.join(sorted(entry['misses']))}")
        lines.append("")
    misses = {k: sorted(v["misses"]) for k, v in grouped.items() if v["misses"] and k not in failing}
    if misses:
        lines += ["## Passing widgets whose fixture missed a route", ""]
        lines += [f"- `{k}`: {', '.join(m)}" for k, m in sorted(misses.items())] + [""]
    (out / "renders.json").write_text(json.dumps([{**r.__dict__, "shot": str(r.shot) if r.shot else None}
                                                  for r in renders]) + "\n", encoding="utf-8")
    md = out / "report.md"
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    serial = {k: {"draws": v["draws"], "worst": v["worst"], "misses": sorted(v["misses"]), "errors": v["errors"],
                  "findings": [{**f, "where": f["where"]} for f in v["findings"].values()]} for k, v in grouped.items()}
    (out / "report.json").write_text(json.dumps(serial, indent=1) + "\n", encoding="utf-8")
    return md
