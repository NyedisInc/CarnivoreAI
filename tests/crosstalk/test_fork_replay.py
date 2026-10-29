
import pytest

from src.core.crosstalk.fork.replay import ReplayPart, render_replay


def test_replay_preserves_dialogue_then_trims_oldest_tool_output_with_utf8_budget() -> None:
    parts = [ReplayPart("user", "remember the original goal"),
             ReplayPart("tool_call", 'read_file({"path":"example.txt"})'),
             ReplayPart("tool_output", "old output " + "x" * 1000),
             ReplayPart("assistant", "the relevant finding is intact"),
             ReplayPart("tool_output", "recent tool result"),
             ReplayPart("user", "continue with this literal text: café 東京 <tag>\nline two")]
    complete = render_replay(parts, max_bytes=10_000)
    assert all(part.text in complete.text for part in parts)
    assert complete.omitted_tool_outputs == complete.omitted_other_parts == 0
    limited = render_replay(parts, max_bytes=700)
    assert len(limited.text.encode("utf-8")) <= 700
    assert parts[2].text not in limited.text
    assert all(part.text in limited.text for i, part in enumerate(parts) if i != 2)
    assert limited.omitted_tool_outputs == 1
    assert limited.omitted_other_parts == 0
    assert "history trimmed" in limited.text
    with pytest.raises(ValueError, match="latest user request"):
        render_replay(parts, max_bytes=100)
    with pytest.raises(ValueError, match="no user request"):
        render_replay([ReplayPart("assistant", "no owner request")], max_bytes=1000)
