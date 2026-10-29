
from __future__ import annotations

import asyncio
from typing import List, Tuple

import pytest

from src.core.tmux_paste_buffer import PasteBufferError, paste_loaded_buffer


def _runner(calls: List[Tuple[str, ...]], delete_rc: int = 0, delete_raises: bool = False):
    async def run(*args, check=True):
        calls.append(args)
        if args[0] == "delete-buffer":
            if delete_raises:
                raise RuntimeError("tmux gone")
            return delete_rc, b"", b"no buffer" if delete_rc else b""
        return 1, b"", b"can't find pane"

    return run


def test_a_failed_paste_deletes_the_loaded_buffer_and_still_raises() -> None:
    calls: List[Tuple[str, ...]] = []
    with pytest.raises(PasteBufferError, match="can't find pane"):
        asyncio.run(paste_loaded_buffer(_runner(calls), "cloude_x_1", "=s:0.0", bracketed=True))
    assert ("delete-buffer", "-b", "cloude_x_1") in calls


@pytest.mark.parametrize("kwargs", [{"delete_rc": 1}, {"delete_raises": True}])
def test_a_failing_cleanup_never_masks_the_paste_error(kwargs) -> None:
    calls: List[Tuple[str, ...]] = []
    with pytest.raises(PasteBufferError):
        asyncio.run(paste_loaded_buffer(_runner(calls, **kwargs), "cloude_x_2", "=s:0.0", bracketed=True))
