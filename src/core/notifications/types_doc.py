
from __future__ import annotations

import sys
from pathlib import Path
from typing import List

from src.core.notifications import catalog_lines, types

DOC_PATH = Path(__file__).resolve().parents[3] / "docs" / "notifications.md"
START = "<!-- generated from src/core/notifications/types.py by src/core/notifications/types_doc.py: start -->"
END = "<!-- generated: end -->"


MIRROR_TESTED = frozenset({
    "session.finished", "agent.message", "plugin.notice", "session.terminal_notice", "alert.self_check", "session.auto_slept",
})


def _verified(type_id: str) -> str:
    return "emit test, Mac mirror test" if type_id in MIRROR_TESTED else "emit test"


def _yes(flag: bool) -> str:
    return "yes" if flag else ""


def render() -> str:
    labels = catalog_lines.read_prefixed(("notify.type.", "notify.family."))
    rows = types.ordered_types()
    out: List[str] = [START, "", f"{len(rows)} types in {len(types.FAMILIES)} groups.", ""]
    for family in types.FAMILIES:
        out.append(f"#### {labels.get(f'notify.family.{family}', family)}")
        out.append("")
        out.append("| Type | Label | Source | On screen | New destination | Passes quiet hours | Never leaves the computer | Verified |")
        out.append("|---|---|---|---|---|---|---|---|")
        for row in (r for r in rows if r.family == family):
            d = row.defaults
            screen = "approvals inbox" if d.screen_surface == "approvals_inbox" else _yes(d.screen)
            seed = _yes(d.seed) + (f" (not {', '.join(row.seed_excluded_kinds)})" if d.seed and row.seed_excluded_kinds else "")
            out.append(f"| `{row.id}` | {labels.get(row.label_key, '')} | {row.source} | {screen} | {seed} | "
                       f"{_yes(d.passes_quiet_hours)} | {_yes(d.outside_locked_off)} | {_verified(row.id)} |")
        out.append("")
    out.append("Retired ids, still accepted (a paired computer on an older build, saved settings, API callers):")
    out.append("")
    out.extend(f"- `{old}` routes as `{new}`" for old, new in sorted(types.ALIASES.items()))
    out.extend(["", END])
    return "\n".join(out)


def current(text: str) -> str:
    if START not in text or END not in text:
        return ""
    return text[text.index(START):text.index(END) + len(END)]


def write(path: Path = DOC_PATH) -> bool:
    text = path.read_text(encoding="utf-8")
    old = current(text)
    if not old:
        raise ValueError(f"no generated block in {path}")
    new = render()
    if old == new:
        return False
    path.write_text(text.replace(old, new), encoding="utf-8")
    return True


if __name__ == "__main__":
    if sys.argv[1:] != ["--write"]:
        print("usage: python3 -m src.core.notifications.types_doc --write")
        sys.exit(2)
    print("updated" if write() else "unchanged")
