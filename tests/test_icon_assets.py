from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
CLIENT_DIR = ROOT / "client"
INDEX_HTML = CLIENT_DIR / "index.html"
MANIFEST = CLIENT_DIR / "manifest.webmanifest"
APP_JS = CLIENT_DIR / "js" / "app.js"


def _static_test_app() -> FastAPI:
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=str(CLIENT_DIR)), name="static")

    @app.get("/manifest.webmanifest")
    async def manifest():
        return FileResponse(MANIFEST, media_type="application/manifest+json")

    @app.get("/apple-touch-icon.png")
    async def apple_touch_icon():
        return FileResponse(CLIENT_DIR / "assets" / "icons" / "icon-180.png")

    return app


def _html_icon_hrefs() -> list[str]:
    html = INDEX_HTML.read_text(encoding="utf-8")
    hrefs = []
    for match in re.finditer(r"<link\s+[^>]*>", html):
        tag = match.group(0)
        rel_match = re.search(r'rel="([^"]+)"', tag)
        href_match = re.search(r'href="([^"]+)"', tag)
        if not rel_match or not href_match:
            continue
        if rel_match.group(1) in ("icon", "apple-touch-icon", "manifest"):
            hrefs.append(href_match.group(1))
    return hrefs


def _manifest_icon_srcs() -> list[str]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return [entry["src"] for entry in data.get("icons", [])]


def _header_brand_icon_url() -> str:
    js = APP_JS.read_text(encoding="utf-8")
    match = re.search(r"HEADER_BRAND_ICON_URL\s*=\s*'([^']+)'", js)
    assert match, "HEADER_BRAND_ICON_URL not found in client/js/app.js"
    return match.group(1)


def _url_to_disk_path(url: str) -> Path:
    if url == "/manifest.webmanifest":
        return MANIFEST
    if url == "/apple-touch-icon.png":
        return CLIENT_DIR / "assets" / "icons" / "icon-180.png"
    assert url.startswith("/static/"), f"unhandled icon URL shape: {url}"
    return CLIENT_DIR / url[len("/static/"):]


def all_declared_icon_urls() -> list[str]:
    urls = _html_icon_hrefs() + _manifest_icon_srcs() + [_header_brand_icon_url()]
    seen: list[str] = []
    for url in urls:
        if url not in seen:
            seen.append(url)
    return seen


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(_static_test_app())


@pytest.mark.parametrize("url", all_declared_icon_urls())
def test_icon_file_exists_on_disk(url: str) -> None:
    path = _url_to_disk_path(url)
    assert path.is_file(), f"{url} -> {path} does not exist"


@pytest.mark.parametrize("url", all_declared_icon_urls())
def test_icon_is_served_with_200(url: str, client: TestClient) -> None:
    response = client.get(url)
    assert response.status_code == 200, f"{url} returned {response.status_code}"
    assert len(response.content) > 0


def test_maskable_icon_declared_and_distinct_from_any_purpose() -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    icons = data.get("icons", [])
    maskable = [i["src"] for i in icons if i.get("purpose") == "maskable"]
    any_purpose = [i["src"] for i in icons if i.get("purpose") == "any"]
    assert maskable, "manifest declares no maskable icon"
    for src in maskable:
        assert src not in any_purpose, (
            f"maskable icon {src} reuses an 'any'-purpose file; "
            "it will not respect the adaptive-icon safe zone"
        )




def _header_icon_span_html() -> str:
    html = INDEX_HTML.read_text(encoding="utf-8")
    match = re.search(
        r'<(span|button)[^>]*\bid="header-icon"[^>]*>.*?</\1>', html, re.DOTALL
    )
    assert match, "expected a #header-icon span or button in client/index.html"
    return match.group(0)


def _set_header_identity_body() -> str:
    js = APP_JS.read_text(encoding="utf-8")
    start_match = re.search(r"function setHeaderIdentity\(opts\)\s*\{", js)
    assert start_match, "setHeaderIdentity(opts) not found in client/js/app.js"
    depth = 0
    i = start_match.end() - 1
    for i in range(start_match.end() - 1, len(js)):
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if depth == 0:
                break
    return js[start_match.end():i]


def test_header_icon_ships_the_real_mark_by_default() -> None:
    span_html = _header_icon_span_html()
    assert "<img" in span_html, (
        "#header-icon's static content must be an <img>, not a bare emoji - "
        "an emoji default is exactly how the launchpad/auth screens ended "
        "up showing the wrong mark"
    )
    assert "☁" not in span_html, (
        "the cloud emoji must not be the static content of #header-icon"
    )


def test_header_icon_static_src_matches_the_single_source_of_truth() -> None:
    span_html = _header_icon_span_html()
    src_match = re.search(r'<img[^>]*\bsrc="([^"]+)"', span_html)
    assert src_match, "#header-icon's <img> must declare a src"
    assert src_match.group(1) == _header_brand_icon_url(), (
        "client/index.html's static #header-icon src has drifted from "
        "HEADER_BRAND_ICON_URL in client/js/app.js - update both together"
    )


def test_set_header_identity_does_not_branch_the_emoji_back_in() -> None:
    body = _set_header_identity_body()
    assert "HEADER_BRAND_EMOJI" not in body, (
        "setHeaderIdentity() must not write the emoji for any opts.icon "
        "value - the real mark renders on every screen; a per-screen "
        "emoji branch is the exact bug this test exists to catch"
    )
    assert "HEADER_BRAND_ICON_URL" in body, (
        "setHeaderIdentity() must still reference the real mark's URL "
        "somewhere in its body"
    )


@pytest.mark.parametrize(
    "screen_function",
    [
        "showAuth",
        "showLaunchpad",
        "showTerminal",
        "returnToExistingTerminal",
    ],
)
def test_every_screen_entry_calls_set_header_identity(screen_function: str) -> None:
    js = APP_JS.read_text(encoding="utf-8")
    func_match = re.search(
        rf"(?:async\s+)?{screen_function}\s*\([^)]*\)\s*\{{", js
    )
    assert func_match, f"{screen_function}() not found in client/js/app.js"
    depth = 0
    end = func_match.end() - 1
    for end in range(func_match.end() - 1, len(js)):
        if js[end] == "{":
            depth += 1
        elif js[end] == "}":
            depth -= 1
            if depth == 0:
                break
    body = js[func_match.end():end]
    if "AppScreenEntry.enterTerminal(" in body:
        shared = (APP_JS.parent / "app-screen-entry.js").read_text(encoding="utf-8")
        body += shared
    assert "setHeaderIdentity(" in body, (
        f"{screen_function}() never calls setHeaderIdentity() - this "
        "screen's header will silently show whatever the previous "
        "screen left in place"
    )




def test_header_icon_is_not_an_svg_vector_redraw() -> None:
    url = _header_brand_icon_url()
    assert not url.lower().endswith(".svg"), (
        f"HEADER_BRAND_ICON_URL is an .svg ({url}) - the only .svg this "
        "repo ever shipped as the header mark was the hand-drawn "
        "cloud_mark() redraw, not the real app icon"
    )
    disk_path = ROOT / "client" / url.lstrip("/").removeprefix("static/")
    assert disk_path.suffix.lower() != ".svg"


def test_deleted_vector_redraw_has_not_come_back() -> None:
    assert not (CLIENT_DIR / "assets" / "cloude-icon.svg").exists(), (
        "client/assets/cloude-icon.svg exists again - this was the "
        "hand-drawn vector redraw deleted by fix/real-app-icon-art; the "
        "header must derive from macOS/assets/AppIcon-1024.png instead"
    )


def _resized_source_pixels(size: int):
    from PIL import Image

    src = Image.open(ROOT / "macOS" / "assets" / "AppIcon-1024.png").convert("RGBA")
    return src.resize((size, size), Image.LANCZOS)


def _mean_abs_pixel_diff(img_a, img_b) -> float:
    from PIL import ImageChops, ImageStat

    diff = ImageChops.difference(img_a, img_b)
    channel_means = ImageStat.Stat(diff).mean
    return sum(channel_means) / len(channel_means)


@pytest.mark.parametrize(
    "filename,size",
    [("header-icon.png", 64), ("header-icon@2x.png", 128)],
)
def test_header_icon_pixels_are_derived_from_real_app_icon(
    filename: str, size: int
) -> None:
    from PIL import Image

    shipped_path = CLIENT_DIR / "assets" / "icons" / filename
    assert shipped_path.is_file(), f"{shipped_path} does not exist"
    shipped = Image.open(shipped_path).convert("RGBA")
    assert shipped.size == (size, size)

    expected = _resized_source_pixels(size)
    diff = _mean_abs_pixel_diff(shipped, expected)
    assert diff < 5.0, (
        f"{filename}'s pixels differ from a resize of AppIcon-1024.png by "
        f"a mean of {diff:.2f}/255 - this is not derived from the real "
        "app icon art (a different resampler of the SAME source differs "
        "by a fraction of this; a redraw differs by orders of magnitude)"
    )
