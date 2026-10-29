from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "client" / "index.html"
CSS_DIR = ROOT / "client" / "css"
MODULE_FAMILIES_JS = ROOT / "client" / "js" / "module-families.js"


def _config_editor_family_pos(name: str) -> int:
    src = MODULE_FAMILIES_JS.read_text(encoding="utf-8")
    match = re.search(r"var\s+CONFIG_EDITOR\s*=\s*\[(.*?)\];", src, re.DOTALL)
    assert match, "could not find the CONFIG_EDITOR array in module-families.js"
    urls = re.findall(r"'/static/js/([^']+)'", match.group(1))
    assert name in urls, f"{name} is not listed in the CONFIG_EDITOR family"
    return urls.index(name)

LABELLED_BUTTON_RULES = [
    (CSS_DIR / "config-editor-modal.css", ".config-editor-mode-toggle button"),
    (CSS_DIR / "config-editor-modal.css", ".config-editor-modal-back"),
    (CSS_DIR / "config-editor.css", ".config-editor-toggle,\n.config-editor-file"),
]


def _rule_body(css: str, selector: str) -> str:
    marker = selector + " {"
    assert marker in css, f"selector {selector!r} is no longer in the stylesheet"
    start = css.index(marker) + len(marker)
    return css[start:css.index("}", start)]



def test_header_button_is_labelled_file_editor():
    html = INDEX_HTML.read_text(encoding="utf-8")
    line = next(ln for ln in html.splitlines() if 'id="configEditorBtn"' in ln)
    assert 'aria-label="File editor"' in line
    assert 'title="file editor"' in line
    assert 'data-tooltip=' not in line


def test_the_drawer_has_no_title_and_its_header_is_compiled():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="config-editor-title"' not in html
    assert '<div class="config-editor-header" id="config-editor-header"></div>' in html
    header = (ROOT / "web" / "src" / "lib" / "file-drawer" / "FileDrawerHeader.svelte").read_text(encoding="utf-8")
    assert 'id="config-editor-close"' in header
    assert 'id="config-editor-new"' in header


@pytest.mark.parametrize("attribute", ["aria-label", "title", "data-tooltip"])
def test_no_user_facing_attribute_still_says_claude_config(attribute):
    html = INDEX_HTML.read_text(encoding="utf-8")
    offenders = [
        value for value in re.findall(rf'{attribute}="([^"]*)"', html)
        if "claude config" in value.lower()
    ]
    assert offenders == [], f"stale {attribute} values: {offenders}"


def test_internal_identifiers_were_deliberately_left_alone():
    html = INDEX_HTML.read_text(encoding="utf-8")
    for identifier in (
        'id="configEditorBtn"',
        'id="config-editor-overlay"',
        'id="config-editor-header"',
        'id="config-editor-tree"',
        'class="config-editor-picker-content"',
    ):
        assert identifier in html, f"{identifier} was renamed - it must not be"



def test_bare_button_reset_still_exists_so_this_guard_is_not_vacuous():
    css = (CSS_DIR / "styles.css").read_text(encoding="utf-8")
    assert not re.search(r"\nbutton \{", css), \
        "a bare `button {` element rule reappeared - it should be scoped, e.g. to .btn-icon"
    assert re.search(r"\n\.btn-icon \{[^}]*width: var\(--control-size\)", css), \
        "the .btn-icon width reset is gone - re-evaluate the rules below"
    assert re.search(r"--control-size:\s*36px;", css), "base square changed"
    assert re.search(
        r"@media \(max-width: 768px\) \{\s*\n\s*:root \{[^}]*--control-size:\s*44px;",
        css,
    ), "the 768px bare-button bump is gone - re-evaluate the rules below"
    assert re.search(
        r"@media \(max-width: 480px\) \{\s*\n\s*:root \{[^}]*--control-size:\s*40px;",
        css,
    ), "the 480px bare-button bump is gone - re-evaluate the rules below"


@pytest.mark.parametrize("css_path,selector", LABELLED_BUTTON_RULES)
def test_labelled_button_rules_declare_width_and_height(css_path: Path, selector: str):
    body = _rule_body(css_path.read_text(encoding="utf-8"), selector)
    assert re.search(r"(^|\s)width:", body), \
        f"{selector} must declare width or it collapses to the bare button square"
    assert re.search(r"(^|\s)height:", body), \
        f"{selector} must declare height or it collapses to the bare button square"


def test_command_rows_break_long_tokens():
    css = (CSS_DIR / "styles.css").read_text(encoding="utf-8")
    body = _rule_body(css, ".command-name,\n.command-description")
    assert "overflow-wrap: anywhere" in body
    assert "min-width: 0" in body


def test_command_list_containers_cannot_exceed_their_parent():
    css = (CSS_DIR / "styles.css").read_text(encoding="utf-8")
    body = _rule_body(css, ".all-commands-list,\n.command-category,\n.command-item")
    assert "min-width: 0" in body
    assert "max-width: 100%" in body



def _script_pos(html: str, name: str) -> int:
    tag = f'<script src="/static/js/{name}"></script>'
    assert tag in html, f"{name} is not loaded"
    return html.index(tag)


def test_new_file_button_and_module_are_wired():
    header = (ROOT / "web" / "src" / "lib" / "file-drawer" / "FileDrawerHeader.svelte").read_text(encoding="utf-8")
    assert 'id="config-editor-new"' in header
    assert "onclick={() => onNewFile()}" in header
    panel = (ROOT / "client" / "js" / "config-editor-panel.js").read_text(encoding="utf-8")
    assert "onNewFile: () => this.createFile()" in panel
    assert (
        _config_editor_family_pos("config-editor-new-file.js")
        < _config_editor_family_pos("config-editor-panel.js")
    )


def test_command_description_module_loads_before_its_consumers():
    html = INDEX_HTML.read_text(encoding="utf-8")
    pos = _script_pos(html, "command-description.js")
    assert pos < _script_pos(html, "slash-command-filter.js")
    assert pos < _script_pos(html, "slash-commands.js")
