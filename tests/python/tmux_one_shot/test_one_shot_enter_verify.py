import asyncio

import pytest

from src.core import tmux_one_shot as t


class FakePane:

    tmux_session = "cloude_fake"

    def __init__(self, swallow: int):
        self.swallow, self.enters, self.screen, self.ingest = swallow, 0, b"> \n", 0

    async def _run_tmux(self, *args, **kw):
        if self.ingest:
            self.ingest -= 1
            self.screen = b"pasting %d\n" % self.ingest
        return 0, self.screen, b""

    async def _write_via_paste_buffer(self, data, bracketed=False):
        self.ingest = 5

    async def _write_via_hex_keys(self, data):
        self.enters += 1
        if self.enters > self.swallow:
            self.screen = b"working\n"


def _fast(monkeypatch):
    monkeypatch.setattr(t, "QUIET_SECONDS", 0.1)
    monkeypatch.setattr(t, "SUBMIT_VERIFY_SECONDS", 0.15)


def test_swallowed_enters_are_retried_until_the_pane_changes(monkeypatch):
    _fast(monkeypatch)
    pane = FakePane(swallow=2)
    asyncio.run(t.paste_and_submit(pane, "big prompt"))
    assert pane.enters == 3 and pane.screen == b"working\n"


def test_a_pane_that_never_submits_is_reported_not_delivered(monkeypatch):
    _fast(monkeypatch)
    pane = FakePane(swallow=99)
    with pytest.raises(t.PasteNotSubmittedError):
        asyncio.run(t.paste_and_submit(pane, "big prompt"))
    assert pane.enters == t.SUBMIT_ATTEMPTS
