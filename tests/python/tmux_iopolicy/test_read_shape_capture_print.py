
from __future__ import annotations

import pytest

from src.core.tmux_control.read_shape import has_flag, shape


@pytest.mark.parametrize("args", [
    ["capture-pane", "-t", "=s:"],
    ["capture-pane", "-J", "-S", "-2000", "-t", "=s:"],
    ["capture-pane", "-b", "keep", "-t", "=s:"],
    ["capture-pane", "-e", "-t", "=s:"],
])
def test_a_capture_without_print_is_not_routed(args):
    assert shape(args) is None


@pytest.mark.parametrize("args", [
    ["capture-pane", "-p", "-t", "=s:"],
    ["capture-pane", "-pJ", "-S", "-2000", "-t", "=s:"],
    ["capture-pane", "-e", "-p", "-t", "=s:"],
])
def test_a_printed_capture_is_routed_unchanged(args):
    assert shape(args) == (args, False)


def test_a_negative_number_is_a_value_not_a_flag_cluster():
    assert not has_flag(["-S", "-2000"], "p") and has_flag(["-eJp"], "p")
