
from __future__ import annotations

import pytest


def test_the_helper_classifies_its_own_failure_when_the_door_cannot_take_it(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    import asyncio

    from src.core.computers import join_helper as jh

    async def find(_status):
        return []

    for door_answer in ({"error": "no_join_waiting"}, {"error": "door_unreachable"}):
        async def ask(request, _a=door_answer):
            return {"state": "waiting_relay", "job": "J1"} if request["op"] == "join" else _a

        monkeypatch.setattr(jh, "find_targets", find)
        monkeypatch.setattr(jh, "ask_once", ask)

        async def held():
            return {"state": "waiting_relay", "job": "J1"}, None

        monkeypatch.setattr(jh, "ask_held", held)
        asyncio.run(jh.serve(jh.Printer(machine=True, agent=False), first_request={"op": "join"}))
    out = capsys.readouterr().out
    assert out.count("state=failed") == 2 and out.count("error=no_pack") == 2
