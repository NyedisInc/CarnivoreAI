import asyncio
from pathlib import Path
from types import SimpleNamespace

from src.config.browser import BrowserConfig
from src.core.browsers.manager import BrowserManager

BID = "aaaaaaaaaaaaaaaa"


class _SlowPage:

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.started = asyncio.Event()

    async def goto(self, url: str, **_kw) -> None:
        self.started.set()
        await self.release.wait()


class _Manager(BrowserManager):

    def __init__(self, tmp: Path, page: _SlowPage) -> None:
        super().__init__(tmp, lambda: BrowserConfig(max_live=3))
        self.page = page

    async def _launch(self, browser_id: str, url: str):
        live = SimpleNamespace(id=browser_id, page=self.page)
        self.live[browser_id] = live
        return live


def test_a_slow_goto_does_not_block_the_lock(tmp_path: Path) -> None:
    async def scenario() -> bool:
        page = _SlowPage()
        manager = _Manager(tmp_path, page)
        task = asyncio.create_task(manager.ensure_live(BID, "https://example.com/"))
        await asyncio.wait_for(page.started.wait(), 2)
        got = False
        try:
            await asyncio.wait_for(manager._lock.acquire(), 0.5)
            got = True
            manager._lock.release()
        except asyncio.TimeoutError:
            pass
        page.release.set()
        await task
        return got

    assert asyncio.run(scenario()) is True
