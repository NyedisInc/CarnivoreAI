from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.contrast.color_utils import (  # noqa: E402
    contrast_ratio,
    list_theme_ids,
    load_theme_vars,
    mix_oklab,
    resolve_color,
)

STYLES_CSS = ROOT / "web" / "src" / "lib" / "base" / "elements.css"
DANGER_SELECTOR = ":where([data-btn='danger'], .oc-btn--danger, .modal-btn-danger)"
THEME_IDS = list_theme_ids()

_LITERAL_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(")
_MIX_RE = re.compile(
    r"color-mix\(\s*in\s+oklab\s*,\s*var\(--oc-coral\)\s*(\d+(?:\.\d+)?)%\s*,"
    r"\s*var\(--oc-ground-raised\)\s*\)"
)


def _rule_body(selector: str) -> str:
    css = STYLES_CSS.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(selector) + r"\s*\{([^}]*)\}")
    match = pattern.search(css)
    assert match, f"{selector!r} not found in {STYLES_CSS} - the check looked at nothing"
    return match.group(1)


def _prop(prop: str) -> str:
    body = _rule_body(DANGER_SELECTOR)
    match = re.search(rf"{re.escape(prop)}\s*:\s*([^;]+);", body)
    assert match, f"{prop} not declared in the danger rule: {body!r}"
    return match.group(1).strip()


def _mix_percent(prop: str) -> float:
    value = _prop(prop)
    match = _MIX_RE.search(value)
    assert match, (
        f"{prop}: no color-mix(in oklab, var(--oc-coral) N%, "
        f"var(--oc-ground-raised)) found in {value!r}"
    )
    return float(match.group(1))


def _danger_fill(theme_id: str, percent: float) -> tuple[int, int, int]:
    v = load_theme_vars(theme_id)
    danger = resolve_color("color-danger", v)
    ground = resolve_color("color-bg-elevated", v)
    return mix_oklab(danger, ground, percent)




def test_no_literal_colors_in_danger_rule() -> None:
    body = _rule_body(DANGER_SELECTOR)
    literals = _LITERAL_COLOR_RE.findall(body)
    assert not literals, f"the danger rule carries a literal colour: {literals} in {body!r}"


def test_danger_rule_names_the_expected_tokens() -> None:
    assert _prop("--_btn-ink") == "var(--oc-text-bright)"
    assert _prop("--_btn-ink-hover") == "var(--oc-text-bright)"
    assert _prop("--_btn-edge") == "var(--oc-coral)"
    assert _prop("--_btn-edge-hover") == "var(--oc-coral)"
    assert _MIX_RE.search(_prop("--_btn-fill")), "fill is not a color-mix(in oklab, --oc-coral, --oc-ground-raised)"
    assert _MIX_RE.search(_prop("--_btn-fill-hover")), "hover fill is not the same color-mix family"


def test_negative_control_the_literal_check_can_fail() -> None:
    assert _LITERAL_COLOR_RE.search("background: #4a1414;")
    assert _LITERAL_COLOR_RE.search("color: rgba(255, 255, 255, 1);")
    assert not _LITERAL_COLOR_RE.search(
        "background: color-mix(in oklab, var(--oc-coral) 25%, var(--oc-ground-raised));"
    )




def _assert_theme_passes(theme_id: str, percent: float) -> None:
    v = load_theme_vars(theme_id)
    fg = resolve_color("color-fg", v)
    fill = _danger_fill(theme_id, percent)
    ratio = contrast_ratio(fg, fill)
    assert ratio >= 4.5, f"{theme_id} at {percent:g}%: text-on-fill {ratio:.2f} below WCAG AA"


@pytest.mark.parametrize("theme_id", THEME_IDS)
def test_danger_fill_text_contrast_resting(theme_id: str) -> None:
    _assert_theme_passes(theme_id, _mix_percent("--_btn-fill"))


@pytest.mark.parametrize("theme_id", THEME_IDS)
def test_danger_fill_text_contrast_hover(theme_id: str) -> None:
    _assert_theme_passes(theme_id, _mix_percent("--_btn-fill-hover"))


def test_at_least_twelve_themes_discovered() -> None:
    assert len(THEME_IDS) >= 12, f"expected >=12 themes, found {len(THEME_IDS)}: {THEME_IDS}"


def test_negative_control_the_contrast_check_can_fail() -> None:
    with pytest.raises(AssertionError):
        assert contrast_ratio((255, 255, 255), (250, 250, 250)) >= 4.5




def test_fill_differs_between_carnivore_and_carnivore_light() -> None:
    percent = _mix_percent("--_btn-fill")
    fill_carnivore = _danger_fill("carnivore", percent)
    fill_light = _danger_fill("carnivore-light", percent)
    assert fill_carnivore != fill_light, (
        "the danger fill is identical under carnivore and carnivore-light - "
        "reads as hardcoded, not token-driven"
    )


def test_negative_control_the_theme_diff_check_can_fail() -> None:
    fill = _danger_fill("carnivore", 25.0)
    with pytest.raises(AssertionError):
        assert fill != fill
