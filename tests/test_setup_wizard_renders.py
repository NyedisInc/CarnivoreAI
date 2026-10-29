
from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_render_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_render_logs_"))
os.environ.setdefault("TOTP_SECRET", "JBSWY3DPEHPK3PXP")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-a-real-one-32b")

playwright_module = pytest.importorskip(
    "playwright.sync_api",
    reason=(
        "playwright is not installed, so nothing about what this page renders "
        "was measured. This is a could-not-evaluate, not a pass."
    ),
)

from fastapi import FastAPI  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

import src.api.setup_routes as setup_routes_module  # noqa: E402
from src.api.setup_routes import (  # noqa: E402
    page_router as setup_page_router,
    router as setup_router,
)
from src.config import settings  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

VIEWPORT = {"width": 1000, "height": 900}


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="function")
def live_wizard(tmp_path, monkeypatch):
    import uvicorn

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"agents": {}, "jwt_expiry_minutes": 99, "config_version": 7})
    )
    monkeypatch.setattr(settings, "auth_config_file", str(config_path))
    monkeypatch.setattr(settings, "host", "0.0.0.0")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(setup_routes_module, "_state_dir", lambda: state_dir)
    settings._auth_config_cache = None

    app = FastAPI()
    app.include_router(setup_router, prefix="/api/v1")
    app.include_router(setup_page_router)
    app.mount(
        "/static",
        StaticFiles(directory=str(REPO_ROOT / "client")),
        name="static",
    )

    port = _free_port()
    monkeypatch.setattr(settings, "port", port)
    monkeypatch.setenv("CLOUDE_BOUND_HOST", "127.0.0.1")
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        pytest.fail("the test server did not start, so nothing was measured")

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=10)
    settings._auth_config_cache = None


@pytest.fixture(scope="function")
def page(live_wizard):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(args=["--use-mock-keychain"])
        except Exception as exc:  # noqa: BLE001
            pytest.skip(
                f"chromium could not launch ({exc}), so nothing about what "
                "this page renders was measured."
            )
        context = browser.new_context(viewport=VIEWPORT)
        pg = context.new_page()
        pg.goto(f"{live_wizard}/setup", wait_until="networkidle")

        assert pg.evaluate("document.hidden") is False, (
            "the page reports document.hidden; a backgrounded tab freezes "
            "rendering and every measurement here would be meaningless"
        )
        assert pg.evaluate("window.innerWidth") == VIEWPORT["width"], (
            "innerWidth does not match the requested viewport, so the layout "
            "under test is not the one that was measured"
        )

        pg.wait_for_selector("#setup-checks .check", timeout=10000)
        yield pg
        context.close()
        browser.close()


def _settled_style(page, selector: str, prop: str) -> str:
    return page.evaluate(
        """([sel, prop]) => new Promise((resolve, reject) => {
            const el = document.querySelector(sel);
            if (!el) { reject(new Error('no element for ' + sel)); return; }
            let previous = null;
            let frames = 0;
            const tick = () => {
                const value = getComputedStyle(el).getPropertyValue(prop);
                if (value === previous) { resolve(value); return; }
                previous = value;
                if (++frames > 120) { resolve(value); return; }
                requestAnimationFrame(tick);
            };
            requestAnimationFrame(tick);
        })""",
        [selector, prop],
    )


class TestTheWizardDrawsPixels:

    def test_every_item_card_occupies_real_area(self, page):
        cards = page.evaluate(
            """() => Array.from(document.querySelectorAll('.card.item')).map(el => {
                const r = el.getBoundingClientRect();
                const cs = getComputedStyle(el);
                return {
                    path: el.getAttribute('data-path'),
                    width: r.width, height: r.height,
                    top: r.top, left: r.left,
                    display: cs.display, visibility: cs.visibility,
                    opacity: parseFloat(cs.opacity)
                };
            })"""
        )
        assert cards, "no item cards rendered at all"
        for card in cards:
            assert card["width"] > 300, card
            assert card["height"] > 120, card
            assert card["left"] >= 0 and card["left"] < VIEWPORT["width"], card
            assert card["display"] != "none", card
            assert card["visibility"] == "visible", card
            assert card["opacity"] > 0.9, card

    def test_the_card_is_actually_painted_not_just_laid_out(self, page):
        from PIL import Image  # noqa: PLC0415
        import io  # noqa: PLC0415

        box = page.evaluate(
            """() => {
                const el = document.querySelector('.card.item');
                const r = el.getBoundingClientRect();
                return {x: r.x, y: r.y, width: r.width, height: r.height};
            }"""
        )
        shot = page.screenshot()
        image = Image.open(io.BytesIO(shot)).convert("RGB")

        inside = image.getpixel(
            (int(box["x"] + box["width"] / 2), int(box["y"] + 6))
        )
        outside = image.getpixel((4, int(box["y"] + 6)))

        difference = sum(abs(a - b) for a, b in zip(inside, outside))
        assert difference > 12, (
            f"the card interior {inside} is indistinguishable from the page "
            f"background {outside}; the panel is laid out but not painted"
        )

    def test_the_two_value_columns_sit_side_by_side(self, page):
        boxes = page.evaluate(
            """() => Array.from(
                document.querySelector('.card.item .values').children
            ).map(el => {
                const r = el.getBoundingClientRect();
                return {left: r.left, right: r.right, top: r.top, bottom: r.bottom,
                        label: el.querySelector('h4').textContent};
            })"""
        )
        assert len(boxes) == 2, boxes
        first, second = boxes
        assert first["right"] <= second["left"] + 1, (
            "the value columns are stacked, not side by side: " + str(boxes)
        )
        assert first["top"] < second["bottom"] and second["top"] < first["bottom"], (
            "the value columns do not overlap vertically: " + str(boxes)
        )
        assert {b["label"] for b in boxes} == {"Your value", "Shipped default"}

    def test_the_three_outcome_marks_are_visually_distinct(self, page):
        colours = page.evaluate(
            """() => {
                const host = document.createElement('div');
                host.style.position = 'absolute';
                host.style.left = '0px';
                host.style.top = '0px';
                document.body.appendChild(host);
                const out = {};
                for (const state of ['pass', 'fail', 'unknown']) {
                    const probe = document.createElement('span');
                    probe.className = 'mark ' + state;
                    host.appendChild(probe);
                    out[state] = getComputedStyle(probe).backgroundColor;
                }
                host.remove();
                return out;
            }"""
        )
        assert len(set(colours.values())) == 3, (
            "two of the three setup-check states render in the same colour, "
            "so the third outcome is collapsed visually: " + str(colours)
        )

        live = page.evaluate(
            """() => Array.from(document.querySelectorAll('#setup-checks .check'))
                .map(row => ({
                    passed: row.getAttribute('data-passed'),
                    cls: row.querySelector('.mark').className,
                    colour: getComputedStyle(row.querySelector('.mark')).backgroundColor
                }))"""
        )
        assert live, "no setup-check rows rendered"
        expected = {"true": "pass", "false": "fail", "unknown": "unknown"}
        for row in live:
            assert expected[row["passed"]] in row["cls"], row
            assert row["colour"] == colours[expected[row["passed"]]], row

    def test_the_lockdown_banner_is_visible_above_the_fold(self, page):
        banner = page.evaluate(
            """() => {
                const el = document.getElementById('exposure-banner');
                if (!el) return null;
                const r = el.getBoundingClientRect();
                return {top: r.top, height: r.height, text: el.textContent};
            }"""
        )
        assert banner is not None, "the exposure banner did not render"
        assert banner["height"] > 20, banner
        assert banner["top"] < VIEWPORT["height"], banner
        assert "127.0.0.1" in banner["text"], banner

    def test_the_banner_carries_its_warning_colour(self, page):
        border = _settled_style(page, "#exposure-banner", "border-left-color")
        assert border, "no border colour resolved"
        numbers = [int(n) for n in border.replace("rgb(", "").rstrip(")").split(",")[:3]]
        red, green, blue = numbers
        assert red > blue + 40 and green > blue, (
            f"the lockdown banner is not rendering its warning colour: {border}"
        )


class TestTheWizardExplainsItself:

    def test_each_item_states_both_consequences(self, page):
        consequences = page.evaluate(
            """() => Array.from(
                document.querySelectorAll('.card.item .choice .consequence')
            ).map(el => el.textContent.trim())"""
        )
        assert len(consequences) >= 2, consequences
        for text in consequences:
            assert len(text) > 25, f"consequence text is not an explanation: {text!r}"

    def test_the_choices_are_per_item_not_one_blanket_accept(self, page):
        groups = page.evaluate(
            """() => Array.from(document.querySelectorAll('.card.item')).map(card =>
                new Set(Array.from(card.querySelectorAll('input[type=radio]'))
                    .map(i => i.name)).size === 1
                    ? card.querySelector('input[type=radio]').name : null)"""
        )
        assert all(groups), groups
        assert len(set(groups)) == len(groups), (
            "item cards share a radio group, so one choice would move them all"
        )

    def test_keep_mine_is_preselected(self, page):
        selected = page.evaluate(
            """() => Array.from(
                document.querySelectorAll('.card.item input[type=radio]:checked')
            ).map(i => i.value)"""
        )
        assert selected and all(v == "keep" for v in selected), selected
