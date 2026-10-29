
from __future__ import annotations

import json
import os
import tempfile
from types import SimpleNamespace
from typing import List

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_rda_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_rda_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.api.resize_negotiation import (  # noqa: E402
    adopt_grid,
    apply_negotiated_resize,
    get_negotiator,
    release_client_resize,
)


class Recorder:

    def __init__(self) -> None:
        self.resizes: List[tuple] = []
        self.frames: List[dict] = []

    def resize_terminal(self, cols: int, rows: int, session_id: str) -> None:
        self.resizes.append((cols, rows))

    async def broadcast_to_session(self, session_id: str, message: str) -> int:
        self.frames.append(json.loads(message))
        return 1


def _manager() -> SimpleNamespace:
    rec = Recorder()
    return SimpleNamespace(resize_terminal=rec.resize_terminal, rec=rec)




@pytest.mark.asyncio
async def test_a_departure_that_moves_nothing_still_tells_the_survivor():
    sm = _manager()
    await apply_negotiated_resize(sm, "s", "V", 79, 40, sm.rec)
    await apply_negotiated_resize(sm, "s", "H", 191, 54, sm.rec)
    assert sm.rec.frames[-1]["clients"] == 2, "fixture: V was told of a second window (its cap)"
    sm.rec.frames.clear()
    await release_client_resize(sm, "s", "H", sm.rec)
    assert sm.rec.resizes == [(79, 40)], "the grid did not move on H leaving"
    assert sm.rec.frames == [{"type": "terminal_size", "cols": 79, "rows": 40,
                              "clients": 1, "constrained": False}], (
        "the survivor was not told the other window left, so its cap never clears")
    sm.rec.frames.clear()
    await apply_negotiated_resize(sm, "s", "V", 129, 42, sm.rec)
    assert sm.rec.resizes[-1] == (129, 42)
    assert sm.rec.frames == [], "a lone client is still never sent its own size"


@pytest.mark.asyncio
async def test_control_with_the_second_window_still_attached_the_grow_is_told():
    sm = _manager()
    await apply_negotiated_resize(sm, "s", "V", 79, 40, sm.rec)
    await apply_negotiated_resize(sm, "s", "H", 191, 54, sm.rec)
    await apply_negotiated_resize(sm, "s", "V", 129, 42, sm.rec)
    assert sm.rec.frames[-1]["cols"] == 129 and sm.rec.frames[-1]["clients"] == 2


@pytest.mark.asyncio
async def test_a_departure_that_moves_the_grid_is_told_once():
    sm = _manager()
    await apply_negotiated_resize(sm, "s", "big", 191, 54, sm.rec)
    await apply_negotiated_resize(sm, "s", "small", 79, 40, sm.rec)
    sm.rec.frames.clear()
    await release_client_resize(sm, "s", "small", sm.rec)
    assert sm.rec.resizes[-1] == (191, 54)
    assert [f["cols"] for f in sm.rec.frames] == [191], sm.rec.frames


@pytest.mark.asyncio
async def test_the_last_client_leaving_sends_nothing():
    sm = _manager()
    await apply_negotiated_resize(sm, "s", "V", 79, 40, sm.rec)
    await release_client_resize(sm, "s", "V", sm.rec)
    assert sm.rec.frames == []




def test_adopt_with_no_window_recorded_uses_the_request():
    sm = _manager()
    assert adopt_grid(sm, ["ses_1"], 191, 54) == (191, 54)
    assert adopt_grid(sm, [], None, None) == (None, None)


@pytest.mark.asyncio
async def test_adopt_with_a_visible_window_recorded_uses_the_negotiated_size():
    sm = _manager()
    await apply_negotiated_resize(sm, "ses_1", "V", 114, 42, sm.rec)
    assert adopt_grid(sm, ["ses_old", "ses_1"], 191, 54) == (114, 42)


@pytest.mark.asyncio
async def test_adopt_with_only_hidden_windows_keeps_the_pane():
    sm = _manager()
    await apply_negotiated_resize(sm, "ses_1", "H", 191, 54, sm.rec, hidden=True)
    assert adopt_grid(sm, ["ses_1"], 191, 54) == (None, None), (
        "a hidden window has no say, so nothing may resize the pane")


@pytest.mark.asyncio
async def test_adopt_under_a_size_master_uses_the_masters_size():
    sm = _manager()
    neg = get_negotiator(sm)
    neg.bind_client_id("ses_1", "M", "tab-master-00001")
    await apply_negotiated_resize(sm, "ses_1", "M", 200, 60, sm.rec)
    await apply_negotiated_resize(sm, "ses_1", "W", 100, 30, sm.rec)
    neg.set_master("ses_1", "tab-master-00001")
    assert adopt_grid(sm, ["ses_1"], 100, 30) == (200, 60)


def test_the_adopt_route_hands_the_negotiated_grid_to_the_manager():
    import asyncio

    import httpx

    from src.api.auth import require_auth
    from src.main import app

    seen: list = []

    class _Manager:
        resize_terminal = staticmethod(lambda cols, rows, session_id=None: None)

        async def adopt_external_session(self, **kwargs):
            seen.append((kwargs["initial_cols"], kwargs["initial_rows"]))
            raise RuntimeError("stop after recording the grid")

    manager = _Manager()
    registry = SimpleNamespace(registered_ids_for_tmux_name=lambda name: ["ses_1"])
    missing = object()
    previous = {key: getattr(app.state, key, missing) for key in ("session_manager", "services")}
    app.state.session_manager = manager
    app.state.services = SimpleNamespace(registry=registry)
    app.dependency_overrides[require_auth] = lambda: True

    async def _drive(body: dict):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1/api/v1") as client:
            return await client.post("/sessions/adopt", json=body)

    body = {"session_name": "carnivore_rva", "confirm_detach": True, "cols": 191, "rows": 54}
    try:
        asyncio.run(_drive(body))
        assert seen[-1] == (191, 54), "control: no window recorded, the request's grid"
        asyncio.run(apply_negotiated_resize(manager, "ses_1", "V", 114, 42, Recorder()))
        asyncio.run(_drive(body))
        assert seen[-1] == (114, 42), "the adopt moved the pane around the negotiator"
    finally:
        app.dependency_overrides.pop(require_auth, None)
        for key, value in previous.items():
            if value is missing:
                delattr(app.state, key)
            else:
                setattr(app.state, key, value)
