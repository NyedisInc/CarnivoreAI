
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import List

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api.resize_negotiation import (  # noqa: E402
    apply_negotiated_resize,
    release_client_resize,
)


class Recorder:

    def __init__(self) -> None:
        self.resizes: List[tuple] = []
        self.frames: List[dict] = []

    def resize_terminal(self, cols: int, rows: int, session_id: str) -> None:
        self.resizes.append((cols, rows))

    async def broadcast_to_session(self, session_id: str, message: str) -> None:
        self.frames.append(json.loads(message))


def _manager() -> SimpleNamespace:
    rec = Recorder()
    return SimpleNamespace(resize_terminal=rec.resize_terminal, rec=rec)


@pytest.mark.asyncio
async def test_a_lone_client_is_never_sent_its_own_size():
    sm = _manager()
    await apply_negotiated_resize(sm, "s", "a", 160, 47, sm.rec)
    await apply_negotiated_resize(sm, "s", "a", 150, 40, sm.rec)
    assert sm.rec.frames == []
    assert sm.rec.resizes == [(160, 47), (150, 40)]


@pytest.mark.asyncio
async def test_a_larger_window_arriving_is_told_it_is_letterboxed():
    sm = _manager()
    await apply_negotiated_resize(sm, "s", "small", 82, 30, sm.rec)
    await apply_negotiated_resize(sm, "s", "big", 160, 47, sm.rec)
    assert sm.rec.resizes == [(82, 30)], "the big window must not resize the pane"
    assert sm.rec.frames[-1]["cols"] == 82
    assert sm.rec.frames[-1]["rows"] == 30
    assert sm.rec.frames[-1]["clients"] == 2


@pytest.mark.asyncio
async def test_the_constraining_window_going_hidden_tells_the_survivor():
    sm = _manager()
    await apply_negotiated_resize(sm, "s", "big", 160, 47, sm.rec)
    await apply_negotiated_resize(sm, "s", "small", 82, 30, sm.rec)
    await apply_negotiated_resize(sm, "s", "small", 82, 30, sm.rec, hidden=True)
    assert sm.rec.resizes[-1] == (160, 47)
    assert (sm.rec.frames[-1]["cols"], sm.rec.frames[-1]["rows"]) == (160, 47)


@pytest.mark.asyncio
async def test_a_hidden_tab_arriving_moves_nothing_and_is_told_the_grid():
    sm = _manager()
    await apply_negotiated_resize(sm, "s", "big", 160, 47, sm.rec)
    outcome = await apply_negotiated_resize(
        sm, "s", "hidden", 82, 30, sm.rec, hidden=True)
    assert sm.rec.resizes == [(160, 47)]
    assert [(f["cols"], f["rows"]) for f in sm.rec.frames] == [(160, 47)]
    assert outcome.target == (160, 47)


@pytest.mark.asyncio
async def test_the_constraining_window_leaving_tells_the_survivor():
    sm = _manager()
    await apply_negotiated_resize(sm, "s", "big", 160, 47, sm.rec)
    await apply_negotiated_resize(sm, "s", "small", 82, 30, sm.rec)
    await release_client_resize(sm, "s", "small", sm.rec)
    assert sm.rec.resizes[-1] == (160, 47)
    last = sm.rec.frames[-1]
    assert (last["cols"], last["rows"], last["clients"]) == (160, 47, 1)
    assert last["constrained"] is False


@pytest.mark.asyncio
async def test_a_window_resized_to_exactly_the_held_grid_is_told_it_is_free():
    sm = _manager()
    await apply_negotiated_resize(sm, "s", "small", 82, 30, sm.rec)
    await apply_negotiated_resize(sm, "s", "big", 160, 47, sm.rec)
    before = len(sm.rec.frames)
    await apply_negotiated_resize(sm, "s", "big", 82, 30, sm.rec)
    assert sm.rec.resizes == [(82, 30)]
    assert len(sm.rec.frames) == before + 1
    assert (sm.rec.frames[-1]["cols"], sm.rec.frames[-1]["rows"]) == (82, 30)
