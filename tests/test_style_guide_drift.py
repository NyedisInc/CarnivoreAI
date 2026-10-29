from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.helpers import style_guide_inventory as inv

REPO_ROOT = inv.REPO_ROOT
SPECIMEN_MAIN = REPO_ROOT / "web" / "src" / "style-guide" / "main.ts"

GUIDE_PREFIX = "sg-"

HYPOTHETICAL = "music"

_CODE = re.compile(r"<code>(.*?)</code>", re.S)
_CLASS_ATTR = re.compile(r'class="([^"]*)"')
_TOKEN = re.compile(r"--oc-[a-z0-9]+(?:-[a-z0-9]+)*")
_PATH = re.compile(r"\b((?:client|web/src|src|docs|scripts|tests|hosted|macOS)/[\w./-]+\.[a-z]{2,5})\b")
_COMPONENT_FILE = re.compile(r"\b([A-Z][A-Za-z0-9]+)\.svelte\b")
_COMPONENT_TAG = re.compile(r"&lt;([A-Z][A-Za-z0-9]+)[\s/&]")
_DOTTED_CLASS = re.compile(r"^\.([a-zA-Z_][\w-]*)$")
_STATIC_ASSET = re.compile(r"/static/([\w./@-]+\.(?:png|webp|jpg|jpeg|gif|avif|svg))\b")


@pytest.fixture(scope="module")
def registry() -> dict:
    return inv.load_registry()


@pytest.fixture(scope="module")
def fragments() -> dict[str, str]:
    found = inv.fragment_text()
    assert found, f"no section fragments under {inv.SECTIONS_DIR}"
    return found


@pytest.fixture(scope="module")
def guide_text(fragments: dict[str, str]) -> str:
    return inv.GUIDE_HTML.read_text(encoding="utf-8") + "\n".join(fragments.values())




def test_every_shipped_file_class_and_component_is_in_the_guide(registry: dict) -> None:
    missing, _stale, missing_files, _gone = inv.drift(registry)
    lines = [f"  file with no guide entry: {rel}" for rel in missing_files]
    lines += [f"  {rel}: {' '.join(sorted(c))}" for rel, c in sorted(missing.items())]
    assert not lines, (
        "the style guide does not cover these; add each to "
        "client/style-guide/registry.json under the section that documents it, "
        "and describe it in that section's fragment:\n" + "\n".join(lines)
    )


def test_every_guide_entry_still_exists_in_the_code(registry: dict) -> None:
    _missing, stale, _new, gone_files = inv.drift(registry)
    lines = [f"  gone file: {rel}" for rel in gone_files]
    lines += [f"  {rel}: {' '.join(sorted(c))}" for rel, c in sorted(stale.items())]
    assert not lines, "the style guide lists things the code no longer has:\n" + "\n".join(lines)


def test_every_registry_section_is_a_real_section(registry: dict) -> None:
    ids = set(inv.section_ids(registry))
    bad = sorted(
        f"{rel} -> {sec}"
        for rel, groups in inv.registered(registry).items()
        for sec in groups
        if sec not in ids
    )
    assert not bad, f"registry files under unknown sections: {bad}"


def test_every_section_has_its_fragment(registry: dict) -> None:
    listed = {s["file"] for s in registry["sections"]}
    on_disk = {p.name for p in inv.SECTIONS_DIR.glob("*.html")}
    assert listed == on_disk, (
        f"sections without a fragment: {sorted(listed - on_disk)}; "
        f"fragments no section lists: {sorted(on_disk - listed)}"
    )


def test_every_exclusion_says_why(registry: dict) -> None:
    assert registry["excluded"], "the exclusion list is empty; the admin site would be flagged"
    for prefix, why in registry["excluded"].items():
        assert isinstance(why, str) and len(why) > 20, f"exclusion {prefix} gives no reason"




def test_every_class_the_guide_names_exists(guide_text: str) -> None:
    defined = inv.all_defined_classes()
    named = set()
    for code in _CODE.findall(guide_text):
        match = _DOTTED_CLASS.match(code.strip())
        if match:
            named.add(match.group(1))
    assert named, "the guide names no class at all; the scanner is broken"
    unknown = sorted(c for c in named if c not in defined and not c.startswith(GUIDE_PREFIX))
    assert not unknown, f"the guide names classes no stylesheet defines: {unknown}"


def test_every_class_a_specimen_wears_exists(fragments: dict[str, str]) -> None:
    defined = inv.all_defined_classes()
    source = inv.source_text()
    used: set[str] = set()
    for html in fragments.values():
        html = re.sub(r"<pre\b.*?</pre>", "", html, flags=re.S)
        for attr in _CLASS_ATTR.findall(html):
            used |= {c for c in attr.split() if not c.startswith(GUIDE_PREFIX)}
    assert used, "no specimen markup found; the scanner is broken"
    unknown = sorted(
        c for c in used
        if c not in defined and not re.search(rf"(?<![\w-]){re.escape(c)}(?![\w-])", source)
    )
    assert not unknown, f"specimens wear classes the app does not have: {unknown}"


def test_every_component_the_guide_names_exists(guide_text: str) -> None:
    components = {p.stem for p in inv.WEB_SRC.rglob("*.svelte")}
    named = set(_COMPONENT_FILE.findall(guide_text)) | set(_COMPONENT_TAG.findall(guide_text))
    assert named, "the guide names no component; the scanner is broken"
    unknown = sorted(n for n in named if n not in components and HYPOTHETICAL not in n.lower())
    assert not unknown, f"the guide names components that do not exist: {unknown}"


def test_every_path_the_guide_names_exists(guide_text: str) -> None:
    paths = set(_PATH.findall(guide_text))
    assert paths, "the guide names no path; the scanner is broken"
    missing = sorted(p for p in paths if not (REPO_ROOT / p).exists() and HYPOTHETICAL not in p.lower())
    assert not missing, f"the guide names paths that do not exist: {missing}"


def test_every_oc_token_is_documented_and_every_named_token_exists(guide_text: str) -> None:
    declared = inv.oc_tokens()
    assert len(declared) > 100, f"only {len(declared)} tokens read from tokens.css; the reader is broken"
    families = set(re.findall(r"(--oc-[a-z0-9-]*)\*", guide_text))
    dead_families = sorted(f for f in families if not any(t.startswith(f) for t in declared))
    assert not dead_families, f"the guide names token families nothing declares: {dead_families}"
    named = set(_TOKEN.findall(re.sub(r"--oc-[a-z0-9-]*\*", "", guide_text)))
    undocumented = sorted(declared - named)
    phantom = sorted(named - declared)
    assert not undocumented, f"tokens.css declares tokens the guide never documents: {undocumented}"
    assert not phantom, f"the guide names tokens tokens.css does not declare: {phantom}"




def test_the_guide_links_exactly_the_apps_stylesheets() -> None:
    app = inv.stylesheet_links(inv.INDEX_HTML.read_text(encoding="utf-8"))
    guide = inv.stylesheet_links(inv.GUIDE_HTML.read_text(encoding="utf-8"))
    assert app, "client/index.html links no stylesheet; the reader is broken"
    assert guide[: len(app)] == app, (
        "client/style-guide.html must link client/index.html's stylesheets in the "
        "same order, so every specimen wears what the app ships"
    )
    assert guide[len(app):] == ["/static/style-guide/guide.css"], guide[len(app):]


def test_the_guide_page_runs_no_inline_script() -> None:
    html = inv.GUIDE_HTML.read_text(encoding="utf-8")
    scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", html, re.S)
    assert scripts, "no script tags found; the reader is broken"
    for attrs, body in scripts:
        assert "src=" in attrs and not body.strip(), f"inline script in style-guide.html: {attrs}"
        src = re.search(r'src="([^"]+)"', attrs).group(1)
        assert src.startswith("/static/"), f"script not served same-origin: {src}"
    for html_frag in inv.fragment_text().values():
        assert "<script" not in html_frag, "a fragment carries a script tag"
        assert not re.search(r"\son[a-z]+=", html_frag), "a fragment carries an inline event handler"


def test_every_live_container_is_mounted_and_every_mount_has_a_container(
    fragments: dict[str, str],
) -> None:
    in_html = set()
    for html in fragments.values():
        in_html |= set(re.findall(r'id="(sg-live-[a-z0-9-]+)"', html))
    sources = [SPECIMEN_MAIN, *sorted((REPO_ROOT / "web" / "src" / "cplugs").glob("*/style-guide/specimens.ts"))]
    in_main = {i for src in sources for i in re.findall(r"id: '(sg-live-[a-z0-9-]+)'", src.read_text(encoding="utf-8"))}
    assert in_html and in_main, "no live specimens found; the reader is broken"
    assert in_html == in_main, (
        f"containers no specimen mounts: {sorted(in_html - in_main)}; "
        f"specimens with no container: {sorted(in_main - in_html)}"
    )


def _missing_static_assets(fragments: dict[str, str]) -> tuple[set[str], list[str]]:
    named = {m for html in fragments.values() for m in _STATIC_ASSET.findall(html)}
    missing = sorted(p for p in named if not (REPO_ROOT / "client" / p).is_file())
    return named, missing


def test_every_image_a_fragment_loads_exists(fragments: dict[str, str]) -> None:
    named, missing = _missing_static_assets(fragments)
    assert len(named) >= 10, f"only {len(named)} images found in the fragments; the reader is broken"
    assert not missing, f"the guide loads images that do not exist: {missing}"


def test_negative_control_a_missing_image_is_flagged(fragments: dict[str, str]) -> None:
    doctored = dict(fragments)
    doctored["zz-negative.html"] = '<img src="/static/img/carnivore/no-such-mark@2x.png" alt="">'
    _named, missing = _missing_static_assets(doctored)
    assert missing == ["img/carnivore/no-such-mark@2x.png"]


def test_guide_copy_carries_no_dash_or_emoji(fragments: dict[str, str]) -> None:
    bad = []
    for name, html in fragments.items():
        for ch in ("—", "–", "&mdash;", "&ndash;"):
            if ch in html:
                bad.append(f"{name}: {ch!r}")
        if re.search(r"[\U0001F300-\U0001FAFF☀-➿]", html):
            bad.append(f"{name}: emoji")
    assert not bad, bad




def test_negative_control_a_new_class_is_flagged(registry: dict, monkeypatch) -> None:
    real = inv.shipped

    def with_extra(reg: dict) -> dict[str, set[str]]:
        out = real(reg)
        out["client/css/toast.css"] = out["client/css/toast.css"] | {"sg-negative-control-new-class"}
        return out

    monkeypatch.setattr(inv, "shipped", with_extra)
    missing, _stale, _files, _gone = inv.drift(registry)
    assert missing == {"client/css/toast.css": {"sg-negative-control-new-class"}}


def test_negative_control_a_removed_class_is_flagged(registry: dict) -> None:
    doctored = json.loads(json.dumps(registry))
    doctored["files"]["client/css/toast.css"]["classes"].append("toast--gone-for-good")
    _missing, stale, _files, _gone = inv.drift(doctored)
    assert stale == {"client/css/toast.css": {"toast--gone-for-good"}}


def test_negative_control_new_and_gone_files_are_flagged(registry: dict) -> None:
    doctored = json.loads(json.dumps(registry))
    removed = doctored["files"].pop("web/src/lib/StatusLed.svelte")
    doctored["files"]["web/src/lib/Nowhere.svelte"] = removed
    _missing, _stale, new_files, gone_files = inv.drift(doctored)
    assert new_files == ["web/src/lib/StatusLed.svelte"]
    assert gone_files == ["web/src/lib/Nowhere.svelte"]


def test_negative_control_the_selector_reader_sees_classes() -> None:
    css = """
    /* .commented-out { } */
    @media (max-width: 10px) { .a, .b:hover > .c--x { color: red } }
    [href$=".css"] { color: blue }
    .d::before { content: ".not-a-class"; }
    .e { color: red; .f { color: blue } }
    """
    assert inv.css_classes(css) == {"a", "b", "c--x", "d", "e", "f"}
