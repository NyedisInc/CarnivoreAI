
import json

from src.core.copilot.store import read_prompts
from src.core.session_conversations.custom_prompt_texts import agy_prompt
from src.core.session_token_usage.copilot_reader import read_copilot_usage

CID = "00000000-0000-4000-8000-000000000002"


def _store(tmp_path, monkeypatch, events):
    folder = tmp_path / "session-state" / CID
    folder.mkdir(parents=True)
    (folder / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    monkeypatch.setenv("COPILOT_HOME", str(tmp_path))


def _usage(inp, out, window):
    return {"type": "session.usage_record", "data": {"usage": {
        "model": "m", "modelDisplayName": "M One", "inputTokens": inp, "outputTokens": out,
        "cacheReadTokens": 0, "cacheWriteTokens": 0, "maxPromptTokens": window}}}


def test_prompts_and_usage_read_from_events(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch, [
        {"type": "user.message", "data": {"content": " first\n\nsecond "}},
        _usage(100, 5, 1000), {"type": "user.message", "data": {"content": "next"}}, _usage(300, 7, 1000),
    ])
    assert read_prompts(CID) == ["first\n\nsecond", "next"]
    usage = read_copilot_usage(CID)
    assert (usage.input_tokens, usage.output_tokens, usage.context_used_tokens, usage.context_remaining_pct) == (400, 12, 300, 70.0)
    assert usage.cost_estimate_usd is None and usage.model_display_name == "M One"


def test_unknown_or_unsafe_id_reads_nothing(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch, [_usage(1, 1, 10)])
    assert read_copilot_usage("../../x") is None and read_prompts(None) == []
    assert read_copilot_usage("11111111-1111-1111-1111-111111111111") is None


def test_agy_prompt_drops_the_wrapper():
    assert agy_prompt("<USER_REQUEST>\nfix it\n\nplease\n</USER_REQUEST>\n<ADDITIONAL_METADATA>x</ADDITIONAL_METADATA>") == "fix it\n\nplease"
    assert agy_prompt("plain") == "plain"


def test_usage_is_cached_until_the_file_moves(tmp_path, monkeypatch):
    from src.core.session_token_usage import copilot_reader

    _store(tmp_path, monkeypatch, [_usage(100, 5, 1000)])
    calls = []
    real = copilot_reader.iter_events
    monkeypatch.setattr(copilot_reader, "iter_events", lambda *a, **k: calls.append(1) or real(*a, **k))
    assert read_copilot_usage(CID).input_tokens == 100 and read_copilot_usage(CID).input_tokens == 100
    assert len(calls) == 1
    with open(tmp_path / "session-state" / CID / "events.jsonl", "a") as handle:
        handle.write("\n" + json.dumps(_usage(50, 1, 1000)))
    assert read_copilot_usage(CID).input_tokens == 150 and len(calls) == 2
