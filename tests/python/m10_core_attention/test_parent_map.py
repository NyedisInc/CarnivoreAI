from __future__ import annotations

from src.core.attention.parent_map import descendants, descends_from


def test_descendants_are_breadth_first_and_exclude_the_root() -> None:
    assert descendants(1, {2: 1, 3: 2, 4: 9}) == [2, 3]


def test_descends_from_includes_itself_and_survives_a_cycle() -> None:
    assert descends_from(3, 1, {3: 2, 2: 1}) is True
    assert descends_from(1, 1, {}) is True
    assert descends_from(3, 1, {3: 2, 2: 3}) is False
