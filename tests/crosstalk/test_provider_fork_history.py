
import json

from src.core.crosstalk.fork.codex_to_claude import rows
from src.core.crosstalk.fork.history import replay_parts
from src.core.crosstalk.fork.replay import render_replay


def test_codex_history_converts_to_chained_claude_rows_without_losing_tools():
    source = [
        {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
            'content': [{'type': 'input_text', 'text': 'Remember VIOLET-731'}]}},
        {'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'shell',
            'arguments': '{"command":"pwd"}'}},
        {'type': 'response_item', 'payload': {'type': 'function_call_output',
            'output': '/tmp/project'}},
        {'type': 'response_item', 'payload': {'type': 'reasoning',
            'summary': [{'type': 'summary_text', 'text': 'Use the tool result'}]}},
        {'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant',
            'content': [{'type': 'output_text', 'text': 'I will remember VIOLET-731'}]}},
    ]
    parts = replay_parts('codex', ('\n'.join(json.dumps(item) for item in source) + '\n').encode())
    data = rows(parts, conversation='11111111-1111-4111-8111-111111111111', cwd='/tmp/project')
    converted = [json.loads(line) for line in data.splitlines()]
    assert len(converted) == 5
    assert [item['parentUuid'] for item in converted] == [None] + [item['uuid'] for item in converted[:-1]]
    assert 'VIOLET-731' in data.decode()
    assert 'historical tool_call' in data.decode()
    assert 'historical tool_output' in data.decode()
    assert 'historical reasoning' in data.decode()
    assert '/tmp/project' in data.decode()
    bounded = render_replay(parts, max_bytes=500)
    assert 'VIOLET-731' in bounded.text
    assert 'history trimmed:' in bounded.text
    assert len(bounded.text.encode()) <= 500
