
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.python.design_system._sources import css_of

CLIENT = Path(__file__).resolve().parents[3] / "client"
SHARED = CLIENT / "css" / "modal-titlerow.css"
SHARED_PROPS = ("display", "align-items", "min-height", "height", "padding", "background", "box-shadow")

WEARERS = {
    "restart-picker__head": ("session-restart-picker.css", "session-restart-picker.js"),
    "sidebar-help__lightbox-bar": ("media-lightbox.css", None),
    "restore-offer__head": ("session-restore-offer.css", "session-restore-offer.js"),
    "group-colour-picker__title": ("session-sidebar-colours.css", "../../web/src/lib/drawer/GroupColorPicker.svelte"),
    "text-prompt-modal__head": ("text-prompt-modal.css", None),
}


def own_declarations(css: str, cls: str) -> set[str]:
    found: set[str] = set()
    for match in re.finditer(r"(?:^|[{};\s])\." + re.escape(cls) + r"\s*\{([^}]*)\}", css):
        found |= set(re.findall(r"([\w-]+)\s*:", match.group(1)))
    return found


def test_scan_can_go_red() -> None:
    sample = ".x__head { gap: 4px; padding: 0 16px; min-height: 26px; }"
    assert own_declarations(sample, "x__head") & set(SHARED_PROPS) == {"padding", "min-height"}


def test_shared_rule_is_the_restart_picker_row() -> None:
    css = css_of(SHARED)
    body = re.search(r"\.modal-titlerow,\s*\.text-prompt-modal__head\s*\{([^}]*)\}", css)
    assert body, "modal-titlerow.css lost its shared rule"
    assert "min-height: var(--oc-titlerow-h, 37px)" in body.group(1)
    assert "padding: 0 14px" in body.group(1)
    assert "var(--oc-ground-titlerow)" in body.group(1)


@pytest.mark.parametrize("cls", sorted(WEARERS))
def test_no_dialog_redeclares_the_strip(cls: str) -> None:
    sheet, js = WEARERS[cls]
    redeclared = own_declarations(css_of(CLIENT / "css" / sheet), cls) & set(SHARED_PROPS)
    assert not redeclared, f".{cls} in {sheet} redeclares {sorted(redeclared)}: that is a sixth copy of the title row"
    if js:
        markup = (CLIENT / "js" / js).resolve().read_text(encoding="utf-8")
        assert re.search(r'class="[^"]*\bmodal-titlerow\b[^"]*\b' + re.escape(cls) + r"\b", markup), (
            f"{js} builds .{cls} without .modal-titlerow"
        )


def test_the_guide_registers_the_class() -> None:
    registry = (CLIENT / "style-guide" / "registry.json").read_text(encoding="utf-8")
    assert '"client/css/modal-titlerow.css"' in registry and '"modal-titlerow"' in registry


def test_confirm_dialog_strip_is_the_text_prompt_strip() -> None:
    svelte = (CLIENT.parent / "web" / "src" / "lib" / "confirm-ok" / "ConfirmOkModal.svelte").read_text(encoding="utf-8")
    assert 'look="titlerow"' in svelte
    app_js = (CLIENT / "js" / "app.js").read_text(encoding="utf-8")
    assert "confirm-modal__verb" not in app_js, "app.js must not draw a confirm dialog of its own"


def test_lightbox_bar_markup_wears_the_shared_class() -> None:
    svelte = (CLIENT.parent / "web" / "src" / "lib" / "help" / "MediaLightbox.svelte").read_text(encoding="utf-8")
    assert 'class="modal-titlerow sidebar-help__lightbox-bar"' in svelte


def test_help_header_is_left_alone() -> None:
    assert "padding" in own_declarations(css_of(CLIENT / "css" / "sidebar-help.css"), "sidebar-help__header")
