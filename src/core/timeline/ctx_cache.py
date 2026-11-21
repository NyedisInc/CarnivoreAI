
from __future__ import annotations

import copy
import threading
from collections import OrderedDict
from typing import Optional, Tuple

from src.core.timeline.context import ExtractContext

MAX_SLOTS: int = 64

_slots: "OrderedDict[Tuple[str, int], ExtractContext]" = OrderedDict()
_lock = threading.Lock()


def take(real: str, offset: int) -> Optional[ExtractContext]:
    with _lock:
        held = _slots.get((real, offset))
        if held is None:
            return None
        _slots.move_to_end((real, offset))
        return copy.deepcopy(held)


def put(real: str, offset: int, ctx: ExtractContext) -> None:
    snapshot = copy.deepcopy(ctx)
    with _lock:
        _slots[(real, offset)] = snapshot
        _slots.move_to_end((real, offset))
        while len(_slots) > MAX_SLOTS:
            _slots.popitem(last=False)


def clear() -> None:
    with _lock:
        _slots.clear()
