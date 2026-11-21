
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from src.api import crosstalk_peer_routes as routes
from src.core.crosstalk import peer_create

BYPASS = '--dangerously-bypass-approvals-and-sandbox'


def _run_spawn(monkeypatch: pytest.MonkeyPatch, *, sender: bool, receiver: bool) -> tuple[list[str], list[str]]:
    seen: dict[str, Any] = {}
    asked: list[str] = []

    async def folder(_body: Any, _parent: Any) -> str:
        return '/tmp/peer-spawn-test'

    async def create_pane(_request: Any, **kwargs: Any) -> dict:
        seen.update(kwargs)
        return {'row_id': 1, 'id': 'ses_x'}

    def approval_skip(action: str, **_kw: Any) -> bool:
        asked.append(action)
        return receiver

    monkeypatch.setattr(routes, '_folder', folder)
    monkeypatch.setattr(peer_create, 'create_pane', create_pane)
    monkeypatch.setattr('src.core.mcp.beast_mode.approval_skip', approval_skip)
    body = routes.PeerSpawn(provider='codex', task='t', beast=sender)
    asyncio.run(routes.peer_spawn(body, SimpleNamespace(), SimpleNamespace(is_peer=True, grant=object())))
    return seen['extra_args'], asked


@pytest.mark.parametrize('sender,receiver', [(True, True), (True, False), (False, True), (False, False)])
def test_bypass_only_when_both_machines_have_beast_on(monkeypatch: pytest.MonkeyPatch, sender: bool, receiver: bool) -> None:
    flags, asked = _run_spawn(monkeypatch, sender=sender, receiver=receiver)
    assert (BYPASS in flags) is (sender and receiver)
    assert asked == ['agent_spawn']
