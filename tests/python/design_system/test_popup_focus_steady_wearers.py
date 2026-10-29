
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCAN = ("web/src", "client/js")
SUFFIXES = {".svelte", ".ts", ".js"}
TOKEN = re.compile(r"(?<![\w./\-])popup-focus(?![\w.\-])")

TRANSIENT = {
    "client/js/fab-menu.js": "menu built on open, removed on close",
    "client/js/header-menu.js": "menu panel built on open, removed on close",
    "client/js/session-theme-menu.js": "picker built on open, removed on close",
    "client/js/slash-commands.js": "modal built on open, removed on close",
    "web/src/cplugs/huddle/TaskManagerArtifactDialog.svelte": "{#if artifactDialog.open}",
    "web/src/cplugs/huddle/TaskManagerForkDialog.svelte": "{#if forkDialog.open}",
    "web/src/cplugs/huddle/TaskManagerScheduleEditor.svelte": "{#if scheduleEditor.open}",
    "web/src/cplugs/huddle/TaskManagerStatusFilter.svelte": "always mounted, but `.hdf-card:not([data-open='on'])` sets animation: none",
    "web/src/cplugs/huddle/TaskManagerTickConfirm.svelte": "{#if tickConfirm.open}",
    "web/src/lib/byoai/ModelPicker.svelte": "{#if open}",
    "web/src/lib/catalog/ItemNotePopup.svelte": "{#if open}",
    "web/src/lib/dialog-frame/AnchoredPopup.svelte": "mounted by its opener while shown",
    "web/src/lib/drawer-tabs/CascadeMenu.svelte": "every caller mounts it inside {#if open/anchor}",
    "web/src/lib/drawer-tabs/MenuPreview.svelte": "hover preview, mounted while hovered",
    "web/src/lib/drawer/group-color.ts": "picker built on open, removed on close",
    "web/src/lib/drawer/group-icon.ts": "picker built on open, removed on close",
    "web/src/lib/drawer/group-rule-popup.ts": "editor built on open, removed on close",
    "web/src/lib/dropdown/ChoiceDropdown.svelte": "{#if open}",
    "web/src/lib/notifications/mute/mute-control.ts": "popover built on open, removed on close",
    "web/src/lib/send-to/SendToModal.svelte": "modal mounted by its opener while shown",
    "web/src/lib/session-move/MoveFolderModal.svelte": "modal mounted by its opener while shown",
    "web/src/lib/widgets-page/PlaceMenu.svelte": "menu mounted by its opener while shown",
    "web/src/opscenter/cells/terminal-live/TerminalActions.svelte": "popover; display:none while closed",
    "web/src/opscenter/layouts/LayoutSkillMenu.svelte": "{#if complete.open}",
}


def strip_comments(text: str) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)(^|\s)//[^\n]*", "", text)


def wears(text: str) -> bool:
    return bool(TOKEN.search(strip_comments(text)))


def steady(text: str) -> bool:
    return "popup-focus-turn" in strip_comments(text)


def census(root: Path = ROOT) -> dict[str, bool]:
    found: dict[str, bool] = {}
    for top in SCAN:
        for p in sorted((root / top).rglob("*")):
            if p.suffix not in SUFFIXES or ".test." in p.name or "__goldens__" in p.parts:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
            if wears(text):
                found[p.relative_to(root).as_posix()] = steady(text)
    return found


def problems(found: dict[str, bool], transient: dict[str, str]) -> list[str]:
    out = [f"{p}: wears popup-focus, is not in TRANSIENT and has no popup-focus-turn"
           for p, turn in found.items() if not turn and p not in transient]
    out += [f"{p}: stale TRANSIENT entry (no wearer there)" for p in transient if p not in found]
    return out


def test_every_wearer_is_transient_or_on_the_compositor():
    assert problems(census(), TRANSIENT) == []


def test_negative_controls(tmp_path):
    (tmp_path / "web/src").mkdir(parents=True)
    (tmp_path / "client/js").mkdir(parents=True)
    (tmp_path / "web/src/Steady.svelte").write_text('<div class="x popup-focus"></div>')
    (tmp_path / "web/src/Turn.svelte").write_text('<div class="popup-focus popup-focus-turn"><span class="pf-sheen"></span></div>')
    (tmp_path / "web/src/Quiet.svelte").write_text('<!-- popup-focus -->\n<style>.popup-focus { color: red }</style>')
    found = census(tmp_path)
    assert found == {"web/src/Steady.svelte": False, "web/src/Turn.svelte": True}
    assert problems(found, {}) == ["web/src/Steady.svelte: wears popup-focus, is not in TRANSIENT and has no popup-focus-turn"]
    assert problems(found, {"web/src/Steady.svelte": "ok"}) == []
    assert problems(found, {"web/src/Steady.svelte": "ok", "web/src/Gone.svelte": "x"}) == [
        "web/src/Gone.svelte: stale TRANSIENT entry (no wearer there)"]


def test_status_filter_gate_is_in_place():
    src = (ROOT / "web/src/cplugs/huddle/TaskManagerStatusFilter.svelte").read_text(encoding="utf-8")
    assert re.search(r"\.hdf-card:not\(\[data-open='on'\]\)\s*\{\s*animation:\s*none", src)
