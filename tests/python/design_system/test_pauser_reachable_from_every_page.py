import re
from pathlib import Path

from tests.python.design_system._sources import strip_comments

REPO = Path(__file__).resolve().parents[3]
CLIENT = REPO / "client"
STATIC = "/static/"
REQUIRED_CSS = ["css/animation-pause.css", "css/animation-calm.css"]
REQUIRED_JS = [
    "js/motion-setting.js",
    "js/visibility-observer.js",
    "js/animation-pauser.js",
    "js/animation-calm.js",
    "js/ambient-ticker.js",
    "js/desktop-window-calm.js",
]
EXEMPT: dict[str, str] = {}
INFINITE = re.compile(r"\binfinite\b")
LINK = re.compile(r"""<link[^>]+rel=["']stylesheet["'][^>]*href=["']([^"']+)["']""")
SCRIPT = re.compile(r"""<script[^>]+src=["']([^"']+)["']""")
STYLE = re.compile(r"<style[^>]*>(.*?)</style>", re.S)


def _local(href: str, root: Path) -> Path | None:
    if not href.startswith(STATIC) or href.startswith(STATIC + "dist/"):
        return None
    return root / href[len(STATIC):]


def has_infinite_animation(html: str, root: Path) -> bool:
    text = strip_comments(html)
    if any(INFINITE.search(block) for block in STYLE.findall(text)):
        return True
    for href in LINK.findall(text):
        path = _local(href, root)
        if path and path.is_file() and INFINITE.search(strip_comments(path.read_text())):
            return True
    return False


def missing_machinery(html: str) -> list[str]:
    text = strip_comments(html)
    css = [h.removeprefix(STATIC) for h in LINK.findall(text)]
    js = [h.removeprefix(STATIC) for h in SCRIPT.findall(text)]
    gaps = [f for f in REQUIRED_CSS if f not in css] + [f for f in REQUIRED_JS if f not in js]
    if not gaps and js.index("js/visibility-observer.js") > js.index("js/animation-pauser.js"):
        gaps.append("order: visibility-observer.js must load before animation-pauser.js")
    return gaps


def test_every_animated_page_links_the_pause_machinery() -> None:
    problems = {}
    for page in sorted(CLIENT.glob("*.html")):
        if page.name in EXEMPT:
            continue
        html = page.read_text()
        if has_infinite_animation(html, CLIENT):
            gaps = missing_machinery(html)
            if gaps:
                problems[page.name] = gaps
    assert not problems, problems


def test_exempt_entries_are_real_pages() -> None:
    for name in EXEMPT:
        page = CLIENT / name
        assert page.is_file(), name
        assert has_infinite_animation(page.read_text(), CLIENT) or missing_machinery(page.read_text()), name


def test_planted_page_goes_red(tmp_path: Path) -> None:
    (tmp_path / "css").mkdir()
    (tmp_path / "css" / "spin.css").write_text("/* c */ .a { animation: spin 1s infinite; }")
    page = '<link rel="stylesheet" href="/static/css/spin.css">'
    assert has_infinite_animation(page, tmp_path)
    assert len(missing_machinery(page)) == len(REQUIRED_CSS) + len(REQUIRED_JS)
    full = "".join(f'<link rel="stylesheet" href="/static/{f}">' for f in REQUIRED_CSS)
    full += "".join(f'<script src="/static/{f}"></script>' for f in REQUIRED_JS)
    assert missing_machinery(full) == []
    swapped = full.replace("visibility-observer", "TMP").replace("animation-pauser", "visibility-observer").replace("TMP", "animation-pauser")
    assert missing_machinery(swapped) and "order" in missing_machinery(swapped)[0]


def test_page_without_animation_needs_nothing(tmp_path: Path) -> None:
    (tmp_path / "css").mkdir()
    (tmp_path / "css" / "calm.css").write_text(".a { animation: fade 1s 1; } /* infinite */")
    assert not has_infinite_animation('<link rel="stylesheet" href="/static/css/calm.css">', tmp_path)
