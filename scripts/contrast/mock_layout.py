from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .color_utils import REPO_ROOT, contrast_ratio, resolve_color
from .roles import _ink, _mix

MOCK_CSS = REPO_ROOT / "web" / "src" / "lib" / "widgets-page" / "settings" / "mock.css"
EDGE_FLOOR = 3.0
FILL_FLOOR = 1.12
TEXT_FLOOR = 4.5
CARD_BODY_SHARE = 0.06
STRIP_SHARE = 0.12
TEXT_VAR = {"primary": "color-fg", "secondary": "color-fg-muted", "muted": "color-fg-subtle"}
Rgb = tuple[int, int, int]


class MockCssError(Exception):
    pass


@dataclass(frozen=True)
class MockStyle:

    line_share: float
    head_share: float
    lines_text: str
    head_text: str


def _mix_share(css: str, token: str) -> float:
    found = re.search(rf"--{token}:\s*color-mix\(in srgb,\s*var\(--oc-ground-content\),\s*var\(--oc-text-primary\)\s*(\d+(?:\.\d+)?)%\)", css)
    if not found:
        raise MockCssError(f"--{token} is not declared as a color-mix of the ground and the primary text in mock.css")
    return float(found.group(1)) / 100.0


def _text_token(css: str, selector: str) -> str:
    found = re.search(rf"{re.escape(selector)}\s*\{{[^}}]*?[; ]color:\s*var\(--oc-text-(\w+)\)", css)
    if not found or found.group(1) not in TEXT_VAR:
        raise MockCssError(f"{selector} has no color: var(--oc-text-*) in mock.css")
    return found.group(1)


def read_style(path: Path = MOCK_CSS) -> MockStyle:
    css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
    return MockStyle(_mix_share(css, "wp-line-section"), _mix_share(css, "wp-surface-head"), _text_token(css, ".wp-mock__lines"), _text_token(css, ".wp-mock__head"))


def measure(ground: Rgb, text: Rgb, style: MockStyle, lines_ink: Rgb | None = None, head_ink: Rgb | None = None) -> dict[str, tuple[float, float]]:
    line, head = _mix(ground, text, style.line_share), _mix(ground, text, style.head_share)
    card = _mix(ground, text, CARD_BODY_SHARE)
    rows = {
        "frame line on card body": (contrast_ratio(line, card), EDGE_FLOOR),
        "padding fill on card body": (contrast_ratio(head, card), FILL_FLOOR),
        "padding fill on stage": (contrast_ratio(head, ground), FILL_FLOOR),
        "cell body line on stage": (contrast_ratio(line, ground), EDGE_FLOOR),
        "cell body line on padding fill": (contrast_ratio(line, head), EDGE_FLOOR),
        "primary text on stage": (contrast_ratio(text, ground), TEXT_FLOOR),
    }
    if lines_ink is not None:
        rows["sample text on stage"] = (contrast_ratio(lines_ink, ground), TEXT_FLOOR)
    if head_ink is not None:
        rows["title strip text on title strip"] = (contrast_ratio(head_ink, _mix(ground, text, STRIP_SHARE)), TEXT_FLOOR)
    return {name: (round(ratio, 2), floor) for name, (ratio, floor) in rows.items()}


def measure_bundled(table: dict[str, str], style: MockStyle) -> dict[str, tuple[float, float]]:
    ground, text = resolve_color("color-bg-page", table), resolve_color("color-fg", table)
    return measure(
        ground, text, style,
        _ink(TEXT_VAR[style.lines_text], ground, table),
        _ink(TEXT_VAR[style.head_text], _mix(ground, text, STRIP_SHARE), table),
    )


def failing(rows: dict[str, tuple[float, float]]) -> dict[str, float]:
    return {name: ratio for name, (ratio, floor) in rows.items() if ratio < floor}
