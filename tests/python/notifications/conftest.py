
from __future__ import annotations

import sys
from typing import Iterator, List

import pytest

from src.core.notifications import contracts


@pytest.fixture()
def captured() -> Iterator[List[contracts.NotifyEvent]]:
    events: List[contracts.NotifyEvent] = []
    copies = {id(m): m for m in (contracts, sys.modules.get(contracts.__name__)) if m is not None}.values()
    for module in copies:
        module.install_sink(events.append)
    try:
        yield events
    finally:
        for module in copies:
            module.uninstall_sink()
