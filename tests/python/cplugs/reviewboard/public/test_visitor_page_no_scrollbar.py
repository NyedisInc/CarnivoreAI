
from __future__ import annotations

import asyncio
import socket
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator, List

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright is not installed, so NO scroll bar was measured.")
from playwright.sync_api import sync_playwright  # noqa: E402

from src.plugins.reviewboard.public import assets, minting  # noqa: E402
from src.plugins.reviewboard.public.edge import EdgeConfig, PublicEdge  # noqa: E402
from src.plugins.reviewboard.public.listener import ListenerSpec, PublicListener  # noqa: E402
from tests.python.cplugs.reviewboard.boards import SIDECAR  # noqa: E402

DIST = Path(__file__).resolve().parents[5] / "client" / "dist"
pytestmark = pytest.mark.skipif(not (DIST / "reviewboard-public.css").exists(), reason="no built visitor bundle, so NO scroll bar was measured.")

PROBE = """() => ({
  page: [document.documentElement.scrollWidth, document.documentElement.clientWidth],
  scrollers: [...document.querySelectorAll('*')].filter((e) => /(auto|scroll)/.test(getComputedStyle(e).overflowX) && e.scrollWidth > e.clientWidth)
    .map((e) => `${e.tagName}.${String(e.className).slice(0, 30)} ${e.scrollWidth}>${e.clientWidth}`),
})"""


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Served:

    def __init__(self, app: Any, port: int) -> None:
        self.app, self.port = app, port
        self.ready = threading.Event()
        self.thread = threading.Thread(target=lambda: asyncio.run(self.main()), daemon=True)

    async def main(self) -> None:
        self.loop, self.stop = asyncio.get_running_loop(), asyncio.Event()
        listener = PublicListener(self.app, ListenerSpec(host="127.0.0.1", port=self.port))
        await listener.start()
        self.ready.set()
        await self.stop.wait()
        await listener.stop()

    def __enter__(self) -> "Served":
        self.thread.start()
        assert self.ready.wait(10)
        return self

    def __exit__(self, *exc: object) -> None:
        self.loop.call_soon_threadsafe(self.stop.set)
        self.thread.join(10)


@pytest.fixture
def served(read_env: Any, store: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setattr(assets, "DIST_DIR", DIST)
    port = free_port()
    slug = SIDECAR["board"]["slug"]
    token = asyncio.run(minting.mint_link(SimpleNamespace(storage=store), slug, "1d", "pinned", access="answer"))["token"]
    edge = PublicEdge(EdgeConfig.of(["127.0.0.1"], [f"127.0.0.1:{port}"]))
    with Served(edge, port):
        yield f"http://127.0.0.1:{port}/#{token}"


@pytest.mark.parametrize("width", [1200, 768, 390])
def test_no_element_scrolls_sideways_and_the_page_does_not_either(served: str, width: int) -> None:
    with sync_playwright() as play:
        browser = play.chromium.launch()
        page = browser.new_context(viewport={"width": width, "height": 800}, extra_http_headers={"X-Forwarded-For": "198.51.100.1"}).new_page()
        page.goto(served)
        page.wait_for_selector(".pb-box iframe", timeout=10000)
        page.wait_for_timeout(1500)
        found = page.evaluate(PROBE)
        browser.close()
    assert found["page"][0] <= found["page"][1], found
    assert found["scrollers"] == [], found
