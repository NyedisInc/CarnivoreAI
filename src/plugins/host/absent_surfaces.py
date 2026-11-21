
from __future__ import annotations

import time
from typing import Callable, Dict, List, Set, Tuple

from src.plugins.runtime.process import ProcessEnded

MARK_SECONDS = 30 * 60.0

_absent: Dict[Tuple[str, str], Dict[str, float]] = {}
_rendered: Dict[Tuple[str, str], Set[str]] = {}
_clock: Callable[[], float] = time.monotonic


def is_no_such_surface(exc: ProcessEnded) -> bool:
    return exc.no_such_surface


def _forget_other_versions(cplug_id: str, version: str) -> None:
    for table in (_absent, _rendered):
        for stale in [k for k in table if k[0] == cplug_id and k[1] != version]:
            del table[stale]


def note_rendered(cplug_id: str, version: str, surface: str) -> None:
    _forget_other_versions(cplug_id, version)
    _rendered.setdefault((cplug_id, version), set()).add(surface)
    _absent.get((cplug_id, version), {}).pop(surface, None)


def remember(cplug_id: str, version: str, surface: str) -> None:
    _forget_other_versions(cplug_id, version)
    if surface in _rendered.get((cplug_id, version), ()):
        return
    _absent.setdefault((cplug_id, version), {})[surface] = _clock() + MARK_SECONDS


def is_absent(cplug_id: str, version: str, surface: str) -> bool:
    marks = _absent.get((cplug_id, version), {})
    expires = marks.get(surface)
    if expires is None:
        return False
    if _clock() >= expires:
        del marks[surface]
        return False
    return True


def listed(cplug_id: str, version: str) -> List[str]:
    return sorted(s for s in list(_absent.get((cplug_id, version), {})) if is_absent(cplug_id, version, s))


def clear() -> None:
    global _clock
    _absent.clear()
    _rendered.clear()
    _clock = time.monotonic
