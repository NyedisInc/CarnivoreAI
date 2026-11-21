
from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Callable, Dict, Protocol

from src.core.automations.store_schema import Tx


class StoreCore(Protocol):

    _clock: Callable[[], float]

    def _write(self, *hit: str, nudge: bool = True) -> AbstractContextManager[Tx]:
        ...

    def run(self, run_id: str) -> Dict[str, Any]:
        ...
