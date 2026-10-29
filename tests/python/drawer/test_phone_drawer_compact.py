import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CSS = (ROOT / "client/css/session-sidebar.css").read_text()
HTML = (ROOT / "client/index.html").read_text()
SEARCH = (ROOT / "web/src/lib/drawer-tabs/DrawerSearch.svelte").read_text()
LEDGER = (ROOT / "web/src/lib/ledger-drawer/DrawerLedger.svelte").read_text()


def _phone_block(css: str) -> str:
    for m in re.finditer(r"@media \(max-width: 1023px\) \{", css):
        depth, i = 1, m.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        body = css[m.end():i - 1]
        if "session-sidebar-scroll" in body:
            return body
    return ""


def test_search_row_lives_inside_the_phone_scroller() -> None:
    wrap = re.search(r'<div class="session-sidebar-scroll">(.*?)\n        </div>', HTML, re.S)
    assert wrap, "scroll wrapper missing from index.html"
    assert 'id="session-sidebar-search"' in wrap.group(1)
    assert 'id="session-sidebar-list"' in wrap.group(1)
    phone = _phone_block(CSS)
    assert re.search(r"\.session-sidebar-scroll \{[^}]*overflow-y: auto", phone)
    assert re.search(r"\.session-sidebar-list \{[^}]*overflow-y: visible", phone)
    assert "position: sticky" not in phone
    assert re.search(r"\.session-sidebar-scroll \{\s*display: contents", CSS)


def test_mode_select_matches_the_field_height() -> None:
    mode = re.search(r"\.ds-mode \{([^}]*)\}", SEARCH).group(1)
    assert "height: 100%" in mode
    assert "--oc-search-h: var(--drawer-field-h" in re.search(r"\.ds-row :global\(\.oc-search\) \{([^}]*)\}", SEARCH).group(1)


def test_search_row_bar_token_is_field_plus_padding() -> None:
    assert "--drawer-bar-h: calc(var(--drawer-field-h) + 2 * var(--oc-space-1) + var(--oc-border))" in CSS
    row = re.search(r"\.ds-row \{([^}]*)\}", SEARCH).group(1)
    assert "padding: var(--oc-space-1)" in row and "border-bottom: var(--oc-border)" in row


def test_phone_tap_target_is_taller_than_the_look() -> None:
    mode = re.search(r"\.ds-mode::after \{([^}]*)\}", SEARCH).group(1)
    assert "height: var(--oc-tap" in mode and "content: ''" in mode
    assert re.search(r"left: 0;", mode), "must not reach left over the search field"
    assert re.search(r"@media \(max-width: 1023px\) \{\s*\.ds-mode \{\s*position: relative", SEARCH)
