
from __future__ import annotations

from typing import Iterator

import pytest

from tests.helpers.scripted_model.rig import RigSlot


@pytest.fixture
def rig_slot() -> Iterator[RigSlot]:
    slot = RigSlot.lease()
    try:
        prefs = slot.slot.api("GET", "/api/v1/preferences")
        slot.slot.api("PATCH", "/api/v1/preferences", {
            "changes": {"account_welcome_seen": True},
            "expected_revision": prefs["revision"],
        })
        yield slot
    finally:
        slot.release()
