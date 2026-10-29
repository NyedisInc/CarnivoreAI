
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

from tests.helpers.guard_fold import assert_no_offenders

STATUS_TOKENS = (
    "--color-success",
    "--color-warning",
    "--color-info",
    "--color-danger",
)

THEMES_DIR = Path(__file__).resolve().parents[1] / "client" / "css" / "themes"


def _theme_ids() -> List[str]:
    return sorted(
        p.parent.name for p in THEMES_DIR.glob("*/theme.json") if p.is_file()
    )


def _css_vars(theme_id: str) -> Dict[str, str]:
    data = json.loads((THEMES_DIR / theme_id / "theme.json").read_text())
    return data.get("cssVars", {}) or {}


def _status_hues(theme_id: str) -> Tuple[Dict[str, str], List[str]]:
    css = _css_vars(theme_id)
    present, missing = {}, []
    for token in STATUS_TOKENS:
        value = (css.get(token) or "").strip()
        if value:
            present[token] = value.lower()
        else:
            missing.append(token)
    return present, missing


def test_themes_were_actually_discovered() -> None:
    ids = _theme_ids()
    assert len(ids) >= 12, f"expected the bundled themes, found {len(ids)}: {ids}"


def _check_status_hues_are_four_distinct_colours(theme_id: str) -> None:
    present, missing = _status_hues(theme_id)
    assert not missing, (
        f"{theme_id} declares no value for {missing}. The status lights "
        f"paint from these four tokens; an undeclared one falls through "
        f"to a shared default."
    )
    by_value: Dict[str, List[str]] = {}
    for token, value in present.items():
        by_value.setdefault(value, []).append(token)
    collisions = {v: t for v, t in by_value.items() if len(t) > 1}
    assert not collisions, (
        f"{theme_id} points more than one status token at the same colour: "
        + "; ".join(f"{v} is used by {', '.join(t)}" for v, t in collisions.items())
        + ". The status lights cannot then say which state they mean. See "
        "the LESSONS entry 'A theme's semantic colours are four NAMES, not "
        "four COLOURS'."
    )


def test_status_hues_are_four_distinct_colours() -> None:
    assert_no_offenders(
        "status hues are four distinct colours",
        _theme_ids(),
        _check_status_hues_are_four_distinct_colours,
    )
