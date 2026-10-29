
from __future__ import annotations

from src.core.project_colors.legacy_keys import LEGACY_KEYS, cycle_key

FROZEN_KEYS = ("orange", "green", "cyan", "yellow", "coral", "violet", "green-bright", "yellow-bright")


def test_legacy_keys_are_the_frozen_tuple_in_order() -> None:
    assert tuple(LEGACY_KEYS) == FROZEN_KEYS


def test_cycle_key_is_round_robin_over_the_frozen_keys() -> None:
    assert [cycle_key(i) for i in range(len(FROZEN_KEYS) + 2)] == list(FROZEN_KEYS) + list(FROZEN_KEYS[:2])
