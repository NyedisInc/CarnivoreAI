
from __future__ import annotations

import pytest

from src.api import mcp_tool_routes
from src.core.mcp import aliases, deprecated_tools, tool_groups, tools
from src.core.mcp.registry import index
from src.core.mcp.registry.model import HEADINGS


def test_group_map_has_no_orphan_thirteen_headings_and_two_part_ids_sit_at_the_heading() -> None:
    names = tools.tool_names()
    seats = tool_groups.placement(names)
    assert set(seats) == set(names)
    live = {n: s for n, s in seats.items() if not deprecated_tools.is_deprecated(n)}
    assert all(aliases.capability_id(n) for n in names), "a tool with no registry id would be an orphan"
    assert {s.heading for s in live.values()} == set(HEADINGS) and len(HEADINGS) == 13
    for name, seat in live.items():
        parts = aliases.capability_id(name).split(".")
        assert seat.heading == parts[0]
        assert (seat.sub == tool_groups.DIRECT) == (len(parts) == 2), name
        assert seat.sub in ("", parts[1])
    assert all(s.heading == deprecated_tools.GROUP for n, s in seats.items() if deprecated_tools.is_deprecated(n))
    assert seats["sessions_roster"] == seats["agents_lookup"] and seats["pack_machines_list"] == seats["computers_list"]
    assert index.problems(None) == []


def test_the_panel_answer_lists_direct_tools_first_and_app_settings_is_a_label_not_a_group(monkeypatch: pytest.MonkeyPatch) -> None:
    doc = mcp_tool_routes.tools_answer()
    heads = [g["group"] for g in doc["groups"]]
    assert heads[-1] == deprecated_tools.GROUP and heads[:-1] == [h for h in HEADINGS if h in heads]
    assert "app_settings" not in heads and "session" not in heads
    for group in doc["groups"]:
        subs = [t["sub"] for t in group["tools"]]
        assert subs == sorted(subs, key=lambda s: (s != "", s)), group["group"]
        assert all(t["sub"] != group["group"] for t in group["tools"]), "no repeated heading > heading group"
    rows = {t["name"]: t for g in doc["groups"] for t in g["tools"]}
    assert rows["preferences_get"]["family"] == "app settings tools" and rows["sessions_list"]["family"] == ""
    assert rows["sessions_roster"]["alias_of"] == "agents_lookup" and rows["agents_lookup"]["alias_of"] == ""
