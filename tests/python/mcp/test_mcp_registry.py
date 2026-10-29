
from __future__ import annotations

import json

import pytest

from src.core.mcp import aliases, protocol, tools
from src.core.mcp.caller import AgentCaller
from src.core.mcp.registry import gates, index
from src.core.mcp.registry.model import HEADINGS, MAX_SUMMARY_CHARS, Capability, id_problems, problems
from src.cplugs.host import runtime
from src.cplugs.sdk import ToolSpec, with_capabilities

def _current() -> list:
    return [n for n in tools.tool_names() if not aliases.is_alias(n)]


def test_every_registered_tool_core_and_plugin_has_one_valid_record():
    names = _current()
    plugin_tools = {n for d in runtime.definitions() for n in d.tools}
    assert len(names) > 250 and len(plugin_tools) > 30
    assert index.problems(names) == []
    entries = index.entries()
    assert set(entries) == set(names)
    assert {c.heading for c in entries.values()} <= set(HEADINGS) and len(HEADINGS) == 13
    assert all(1 <= len(c.summary) <= MAX_SUMMARY_CHARS and c.sub_heading for c in entries.values())
    assert len({c.id for c in entries.values()}) == len(entries)
    assert all(runtime.find(d.id).tools[n].capability_id == entries[n].id for d in runtime.definitions() for n in d.tools)


def test_the_rules_go_red_on_a_bad_record():
    assert id_problems("Sessions.list") and id_problems("sessions") and id_problems("nope.thing.get")
    assert id_problems("ui." + ".".join(["a"] * 8)) and id_problems("ui.x" + "y" * 40 + ".get")
    assert problems([Capability("a", "ui.files.open", "x"), Capability("b", "ui.files.open", "y")])
    assert problems([Capability("a", "ui.files", "x"), Capability("b", "ui.files.open", "y")])
    assert problems([Capability("a", "ui.files.open", "x" * 241)]) and problems([Capability("a", "ui.files.open", "")])
    assert Capability("a", "sessions.create", "x").sub_heading == "sessions"
    assert Capability("a", "projects.companies.list", "x").sub_heading == "companies"
    assert index.problems(_current() + ["a_tool_with_no_record"]) == ["a_tool_with_no_record: registered tool with no registry record"]


def test_a_plugin_cannot_attach_metadata_that_misses_or_invents_a_tool():
    spec = ToolSpec("d", {}, [], handler=None)
    assert with_capabilities({"x_get": spec}, {"x_get": ("ui.x.get", "s")})["x_get"].capability_id == "ui.x.get"
    with pytest.raises(ValueError):
        with_capabilities({"x_get": spec}, {})
    with pytest.raises(ValueError):
        with_capabilities({}, {"x_get": ("ui.x.get", "s")})


def test_every_write_has_a_declared_gate_class_and_the_undeclared_allowlist_is_empty():
    classes = gates.gate_classes()
    assert set(classes.values()) <= set(gates.CLASSES)
    assert all(c != gates.READ for n, c in classes.items() if n in tools.WRITE_TOOLS)
    assert all(c == gates.READ for n, c in classes.items() if n not in tools.WRITE_TOOLS)
    assert {n for n, c in classes.items() if c == gates.UNDECLARED} == set(gates.UNDECLARED_WRITES) == set()
    assert gates.gate_class("session_delete") == gates.ALWAYS_WAITS_CLASS and gates.gate_class("session_create") == gates.ACT
    assert gates.gate_class("notify") == gates.ARRANGE and gates.gate_class("pack_master_set") == gates.ACT
    assert gates.gate_class("huddle_add") == gates.gate_class("task_manager_add") == gates.AGENT
    assert gates.gate_class("task_manager_lead_set") == gates.ALWAYS_WAITS_CLASS


def test_flat_names_and_dotted_ids_round_trip_and_retired_names_resolve_to_their_target():
    table = aliases.id_table()
    assert set(table) == set(tools.tool_names())
    for name, cid in table.items():
        assert aliases.capability_id(name) == cid and aliases.capability_id(cid) == cid
        assert aliases.flat_name(cid) == aliases.canonical(name) and aliases.flat_name(name) == aliases.canonical(name)
    for old, new in aliases.table().items():
        assert table[old] == table[new]
    assert aliases.capability_id("huddle_list") == "task_manager.tasks.list"
    assert aliases.flat_name("task_manager.tasks.list") == "task_manager_tasks_list"
    assert aliases.capability_id("no_such_tool") is None and aliases.flat_name("ui.no.such") is None
    assert aliases.capability_id("ui.no.such") is None


def test_registry_metadata_never_reaches_tools_list_or_its_fingerprint(monkeypatch):
    caller = AgentCaller("tok", "tok", "tok", "tok", "write")
    before = json.dumps(tools.tool_definitions(), sort_keys=True)
    fingerprint = protocol.tool_fingerprint(caller)
    assert all(set(row) <= {"name", "description", "inputSchema", "annotations"} for row in json.loads(before))
    ids = {c.id for c in index.entries().values() if c.id.count(".") > 1}
    assert not [i for i in ids if f'"{i}"' in before]
    junk = {n: Capability(n, f"system.junk.n{i}", "junk") for i, n in enumerate(index.entries())}
    monkeypatch.setattr(index, "_built", (runtime.definitions(), junk))
    assert index.get("whoami").summary == "junk"
    assert json.dumps(tools.tool_definitions(), sort_keys=True) == before
    assert protocol.tool_fingerprint(caller) == fingerprint
