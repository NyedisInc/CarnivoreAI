from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from src.cplugs.huddle import sending, service
from src.cplugs.huddle.roles import unstick


def test_send_session_reads_project_names_off_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    async def go() -> None:
        loop_thread = threading.get_ident()

        def names(ctx: object) -> dict:
            seen["off_loop"] = threading.get_ident() != loop_thread
            return {"12": "alpha"}

        async def listing() -> list:
            return []

        async def one(ctx, run, key, name, infos, chosen, before_paste=None) -> dict:
            seen["name"] = name
            return {"list": key, "status": "sent"}

        async def run(call):
            return await asyncio.to_thread(call)

        monkeypatch.setattr(service, "project_names", names)
        monkeypatch.setattr(sending, "send_one_of_many", one)
        await unstick.send_session(SimpleNamespace(sessions=SimpleNamespace(list=listing)), run, "", "12")

    asyncio.run(go())
    assert seen == {"off_loop": True, "name": "alpha"}
