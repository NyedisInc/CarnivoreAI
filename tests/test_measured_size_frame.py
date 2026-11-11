
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api.resize_negotiation import measured_size_frame  # noqa: E402


class _Backend:
    def __init__(self, grid):
        self._grid = grid

    async def pane_geometry(self):
        return self._grid


def test_measured_frame_carries_the_pane_grid_and_no_client_count():
    frame = json.loads(asyncio.run(measured_size_frame(_Backend((120, 40)))))
    assert frame == {"type": "terminal_size", "cols": 120, "rows": 40, "measured": True}


def test_unreadable_pane_sends_nothing():
    assert asyncio.run(measured_size_frame(_Backend(None))) is None
    assert asyncio.run(measured_size_frame(None)) is None
