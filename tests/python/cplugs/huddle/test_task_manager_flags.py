
import pytest

from src.cplugs.huddle import flags
from tests.python.cplugs.huddle.test_task_manager_batch import _items, call, manager  # noqa: F401


@pytest.mark.parametrize("value,expected", [
    (False, False), (True, True), ("false", False), ("FALSE", False), ("true", True), ("0", False), ("1", True),
    (0, False), (1, True), (" false ", False),
])
def test_parse_flag_accepts_bools_strings_and_ints(value, expected):
    assert flags.parse_flag(value, not expected) is expected


def test_absent_or_unrecognized_gives_the_default():
    assert flags.flag({}, "x", True) is True
    assert flags.flag({"x": None}, "x", False) is False
    assert flags.parse_flag("maybe", True) is True


def test_string_false_leaves_threads_out_of_list_and_changes_and_lean(manager):  # noqa: F811
    a, = _items(manager, 1, "12")
    assert call(manager, "task_manager_ask", {"item": a, "text": "which?"})[0]
    for value in (False, "false", "0"):
        ok, listed = call(manager, "task_manager_tasks_list", {"list": "12", "include_thread": value})
        assert ok and all("thread" not in i for i in listed["items"])
        ok, changed = call(manager, "task_manager_changes", {"since": 0, "list": "12", "include_thread": value})
        assert ok and all("thread" not in i for i in changed["items"])
    ok, listed = call(manager, "task_manager_tasks_list", {"list": "12", "include_thread": "true"})
    assert any("thread" in i for i in listed["items"])
    ok, full = call(manager, "task_manager_add", {"list": "12", "text": "two", "lean": "false"}, raw=True)
    assert ok and full["text"] == "two"
