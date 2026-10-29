
from __future__ import annotations

import asyncio
from typing import Any

from src.cplugs.flow import routes
from src.cplugs.sdk import OWN_POLICY_HEADER
from src.cplugs.sdk.sandboxed_html import VIEW_CSP


def _call(monkeypatch, html: bool) -> Any:
    async def fake_run(*args: Any, **kwargs: Any) -> dict:
        return {"seed": "x", "stats": {}}

    monkeypatch.setattr(routes.service, "get_run", fake_run)
    monkeypatch.setattr(routes.service, "as_page", lambda run: {"html": "<!doctype html><script>1</script>"})
    return asyncio.run(routes.run(seed="huddle_item", id="1", start=None, end=None, refresh=False, html=html, ctx=None))


def test_the_html_page_is_served_under_the_sandbox_policy(monkeypatch) -> None:
    answer = _call(monkeypatch, True)
    assert answer.headers["content-security-policy"] == VIEW_CSP
    assert answer.headers[OWN_POLICY_HEADER.lower()] == "1"


def test_the_json_answer_is_untouched(monkeypatch) -> None:
    assert _call(monkeypatch, False) == {"seed": "x", "stats": {}}
