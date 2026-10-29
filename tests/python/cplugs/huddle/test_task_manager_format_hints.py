
from __future__ import annotations

from src.core.mcp import tools
from tests.python.cplugs.huddle.test_task_manager_mcp import manager  # noqa: F401


def _defs() -> dict:
    return {d["name"]: d for d in tools.tool_definitions()}


def test_reply_and_batch_name_the_table_and_key_value_forms(manager):
    for name in ("task_manager_reply", "task_manager_batch_run"):
        text = _defs()[name]["description"]
        assert "pipe table" in text and "```kv" in text


def test_the_text_fields_that_render_markdown_say_so(manager):
    defs = _defs()
    assert "Markdown renders" in defs["task_manager_reply"]["inputSchema"]["properties"]["text"]["description"]
    assert "Markdown renders" in defs["task_manager_ask"]["inputSchema"]["properties"]["context"]["description"]
    op = defs["task_manager_batch_run"]["inputSchema"]["properties"]["ops"]["items"]["properties"]["text"]["description"]
    assert "Markdown renders" in op


def test_item_text_is_documented_as_plain(manager):
    defs = _defs()
    for name in ("task_manager_add", "task_manager_update"):
        assert "Plain text" in defs[name]["inputSchema"]["properties"]["text"]["description"]
