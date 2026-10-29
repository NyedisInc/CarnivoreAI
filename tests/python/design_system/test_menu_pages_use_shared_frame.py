from __future__ import annotations

import re

from tests.python.design_system._sources import REPO, strip_comments

PAGES = (
    "blueprints", "catalog", "hosts-page", "info-pages", "item-settings", "ledger",
    "manager-frame", "plugins-page", "settings-page", "sessions-page", "skills-page", "themes-page",
    "widgets-page",
)
REMOVED = (
    "mgr-toggle", "asw-toggle", "catalog-btn", "acts__btn", "ph-page__select",
    "ph-page__field", "mgr__chip", "ledger-scroll", "ledger-main",
    "mgr-actions__error", "mgr-actions__notice", "mgr-actions__question",
    "tp-bar", "tp-btn", "tp-btn-on", "tp-seg", "tp-search", "tp-tools", "tp-icon",
    "tp-title", "tp-kicker", "tp-stats", "tp-back", "tp-body", "tp-side",
    "mgr__head", "mgr__bar", "mgr__body", "mgr__scroll", "mgr__main",
    "mgr__input", "mgr__state", "mgr__items", "mgr__error", "pl-btn",
)
_TOKEN = re.compile(r"[A-Za-z][\w-]*")


def leftovers(text: str) -> set[str]:
    tokens = set(_TOKEN.findall(strip_comments(text)))
    return {c for c in REMOVED if c in tokens}


def test_pages_carry_no_removed_duplicate_class() -> None:
    bad: dict[str, set[str]] = {}
    for page in PAGES:
        root = REPO / "web" / "src" / "lib" / page
        assert root.is_dir(), f"guarded page folder {root} does not exist; fix PAGES"
        for path in root.rglob("*"):
            if path.suffix in {".svelte", ".css", ".ts"} and ".test." not in path.name:
                if hit := leftovers(path.read_text()):
                    bad[str(path.relative_to(REPO))] = hit
    assert not bad, f"per-page duplicates came back: {bad}"


def test_the_frame_is_the_only_overlay_root() -> None:
    for page in ("ledger", "catalog", "manager-frame"):
        for path in (REPO / "web" / "src" / "lib" / page).glob("*.svelte"):
            source = path.read_text()
            assert not fixed_overlay_roots(source), (
                f"{path.name} draws its own fixed overlay root; use Page (opscenter/ui/Page.svelte)"
            )


def fixed_overlay_roots(source: str) -> list[str]:
    css = strip_comments("".join(re.findall(r"<style[^>]*>(.*?)</style>", source, re.S)))
    popovers = set()
    for tag in re.findall(r"<[a-z][^>]*\bpopover\s*=\s*['\"][^'\"]+['\"][^>]*>", source, re.S):
        classes = re.search(r'\bclass="([^"]+)"', tag)
        if classes:
            popovers.update(classes.group(1).split())
    for tag in re.findall(r"<AnchoredPopup\b.*?(?:/>|\n\s*>|\}>|\">)", source, re.S):
        plain = re.search(r'\bclass="([^"]+)"', tag)
        if plain:
            popovers.update(plain.group(1).split())
        expr = re.search(r"\bclass=\{([^}]*)\}", tag)
        if expr:
            for quoted in re.findall(r"'([^']*)'", expr.group(1)):
                popovers.update(quoted.split())
    fixed = []
    for rule in re.finditer(r"([^{}]+)\{[^{}]*\bposition:\s*fixed\b[^{}]*}", css):
        for selector in rule.group(1).split(","):
            selector = selector.strip()
            root = re.fullmatch(r"\.([A-Za-z][\w-]*)|:global\(\.([A-Za-z][\w-]*)\)", selector)
            if not root or (root.group(1) or root.group(2)) not in popovers:
                fixed.append(selector)
    return fixed


def test_negative_control_a_removed_class_is_flagged() -> None:
    assert leftovers('<button class="mgr-toggle">') == {"mgr-toggle"}
    assert leftovers("<!-- mgr-toggle --> /* asw-toggle */") == set()
    assert fixed_overlay_roots('<style>.own-root { position: fixed; }</style>') == [".own-root"]
    assert fixed_overlay_roots('<div class="popup" popover="manual"></div><style>.popup .own-root { position: fixed; }</style>') == [".popup .own-root"]
    assert fixed_overlay_roots('<div class="popup" popover="manual"></div><style>.own-root, .popup { position: fixed; }</style>') == [".own-root"]
    assert fixed_overlay_roots('<div class="anchored popup-focus" popover="manual"></div><style>.anchored { position: fixed; }</style>') == []
    framed = "<AnchoredPopup class={wide ? 'pick' : 'pick pick--modal'} topLayer\n  label={x}\n>"
    assert fixed_overlay_roots(framed + "<style>:global(.pick) { position: fixed; }</style>") == []
    assert fixed_overlay_roots('<AnchoredPopup class="pick" label={x}>' + "<style>:global(.own-root) { position: fixed; }</style>") == [":global(.own-root)"]
    assert fixed_overlay_roots("<style>:global(.pick) { position: fixed; }</style>") == [":global(.pick)"]
