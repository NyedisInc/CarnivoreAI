
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.cplugs.host import capabilities, session_actions
from src.cplugs.huddle import service
from src.cplugs.huddle.roles import route, tags

ASLEEP_KEY = "7f3e-asleep"


@pytest.fixture
def mcp_ctx(monkeypatch):

    async def infos():
        return []

    async def asleep(_request):
        return [{"session_uuid": ASLEEP_KEY, "project_id": 12, "name": "slept"}]

    monkeypatch.setattr(service, "swarm_of", lambda _ctx: None)
    monkeypatch.setattr(session_actions, "asleep", asleep)
    sessions = capabilities.Sessions(infos, None, True, app_state=object())
    assert not hasattr(sessions, "asleep")
    return SimpleNamespace(sessions=sessions)


@pytest.mark.asyncio
async def test_peek_reads_the_asleep_list_without_a_request(mcp_ctx):
    assert (await route.peek(mcp_ctx, ASLEEP_KEY)).outcome == route.ASLEEP
    assert (await route.peek(mcp_ctx, "nobody")).outcome == route.GONE


@pytest.mark.asyncio
async def test_a_tag_naming_an_asleep_session_resolves_without_a_request(mcp_ctx, monkeypatch):
    monkeypatch.setattr(tags, "RoleStore", lambda _store: SimpleNamespace(dnd_keys=lambda: set()))
    assert await tags.target_key(mcp_ctx, SimpleNamespace(), ASLEEP_KEY, caller_key="u-me") == ASLEEP_KEY
