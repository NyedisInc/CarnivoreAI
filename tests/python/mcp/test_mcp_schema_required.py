
from src.core.mcp import tools


def test_every_tool_schema_required_is_unique_and_declared() -> None:
    definitions = tools.tool_definitions()
    assert len(definitions) > 100, "the real tool table is empty or truncated"
    bad = []
    for definition in definitions:
        schema = definition["inputSchema"]
        required = schema["required"]
        if len(required) != len(set(required)) or not set(required) <= set(schema["properties"]):
            bad.append((definition["name"], required))
    assert not bad, bad
