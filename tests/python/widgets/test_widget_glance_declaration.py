from __future__ import annotations

import pytest

from src.core.item_catalog import ItemCatalogError, load_widgets, parse_widgets


def _doc(row_extra: dict) -> dict:
    return {"schema": 1, "widgets": [{"id": "core.notes", "instancing": "singleton", **row_extra}]}


def test_the_shipped_file_loads_with_the_ledger_glance() -> None:
    assert any(decl.id == "core.ledger" for decl in load_widgets())


def test_a_whole_height_in_range_is_accepted() -> None:
    assert len(parse_widgets(_doc({"glance": {"height": 72}}))) == 1


@pytest.mark.parametrize("bad", [{"height": 0}, {"height": 500}, {"height": 7.5}, {"height": True}, {}, {"height": 72, "w": 1}, 72, None])
def test_a_malformed_glance_is_refused(bad: object) -> None:
    with pytest.raises(ItemCatalogError):
        parse_widgets(_doc({"glance": bad}))
