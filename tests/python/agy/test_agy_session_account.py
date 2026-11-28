
import json
import time

from src.core.agy.session_account import session_account
from src.core.session_token_usage.agy_reader import usage_from_state


def _state(model_id, display):
    return {
        "conversation_id": "c1", "email": "Jo@example.com", "plan_tier": "Google AI Ultra", "written_at": time.time(),
        "model": {"id": model_id, "display_name": display},
        "quota": {
            "3p-5h": {"remaining_fraction": 0.9}, "3p-weekly": {"remaining_fraction": 0.8},
            "gemini-5h": {"remaining_fraction": 0.5}, "gemini-weekly": {"remaining_fraction": 0.25},
        },
    }


def _put(tmp_path, state):
    folder = tmp_path / "agy-state"
    folder.mkdir()
    (folder / "1.json").write_text(json.dumps(state))


def _used(row):
    return {w.kind: (w.label, w.used_pct) for w in row.windows}


def test_gemini_model_picks_gemini_buckets(tmp_path):
    _put(tmp_path, _state("g", "Gemini 4 Neon (High)"))
    row = session_account(tmp_path, "c1")
    assert _used(row) == {"five_hour": ("5h", 50.0), "seven_day": ("7d", 75.0)}
    assert row.provider == "antigravity" and row.short_name == "Jo" and row.plan == "Google AI Ultra"


def test_other_model_picks_third_party_buckets(tmp_path):
    _put(tmp_path, _state("claude-x", "Claude X"))
    assert _used(session_account(tmp_path, "c1")) == {"five_hour": ("5h", 10.0), "seven_day": ("7d", 20.0)}


def test_no_state_or_email_is_none(tmp_path):
    assert session_account(tmp_path, "c1") is None
    _put(tmp_path, {"conversation_id": "c1"})
    assert session_account(tmp_path, "c1") is None


def test_context_tokens_follow_used_percentage():
    window = {"context_window_size": 1000, "used_percentage": 16.87, "current_usage": {"input_tokens": 0}}
    assert usage_from_state({"context_window": window}).context_used_tokens == 169
    del window["used_percentage"]
    assert usage_from_state({"context_window": window}).context_used_tokens == 0
