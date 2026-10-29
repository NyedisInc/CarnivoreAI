from __future__ import annotations

from src.core.session_import_mapping import _row_fields


def test_string_row_has_no_epoch() -> None:
    assert _row_fields("cloude_a")["tmux_created_epoch"] is None


def test_dict_row_without_a_parseable_epoch_has_none() -> None:
    assert _row_fields({"name": "a"})["tmux_created_epoch"] is None
    assert _row_fields({"name": "a", "created_at_epoch": "soon"})["tmux_created_epoch"] is None


def test_dict_row_with_an_epoch_keeps_it() -> None:
    assert _row_fields({"name": "a", "created_at_epoch": "1800000000"})["tmux_created_epoch"] == 1800000000
