
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from src.core.browsers import manager


def test_driver_errors_cover_expected_and_exclude_bugs() -> None:
    errors = manager.driver_errors()
    assert asyncio.TimeoutError in errors and KeyError in errors
    assert not issubclass(AttributeError, errors) and not issubclass(RuntimeError, errors)


def test_nav_read_survives_a_driver_failure_but_not_a_bug() -> None:
    from playwright.async_api import Error as PlaywrightError

    class Cdp:
        def __init__(self, exc: Exception) -> None:
            self.exc = exc

        async def send(self, *_a: object) -> None:
            raise self.exc

    def run(exc: Exception):
        live = SimpleNamespace(cdp=Cdp(exc), page=SimpleNamespace(url="u"))
        return asyncio.run(manager.LiveBrowser.nav_message(live, False))  # type: ignore[arg-type]

    assert run(PlaywrightError("renderer swap"))["type"] == "nav"
    try:
        run(AttributeError("bug"))
    except AttributeError:
        return
    raise AssertionError("a programming error must not be swallowed")
