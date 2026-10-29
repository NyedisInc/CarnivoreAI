
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.session_token_usage.cache import IncrementalCache, TranscriptTotals
from src.core.session_token_usage.claude_reader import read_transcript_totals
from src.core.session_token_usage.claude_selection import read_selection


def _turn(model: Optional[str], effort: Optional[str], msg_id: str) -> Dict[str, Any]:
    message: Dict[str, Any] = {
        "role": "assistant",
        "id": msg_id,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    if model is not None:
        message["model"] = model
    record: Dict[str, Any] = {"type": "assistant", "message": message}
    if effort is not None:
        record["effort"] = effort
    return record


def _command(text: str) -> Dict[str, Any]:
    return {"type": "system", "subtype": "local_command", "content": text}


def _legacy_command(text: str) -> Dict[str, Any]:
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": f"<local-command-stdout>{text}</local-command-stdout>",
        },
    }


def _scan(tmp_path: Path, records: List[Dict[str, Any]]) -> TranscriptTotals:
    path = tmp_path / "transcript.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    totals = read_transcript_totals(path, cache=IncrementalCache())
    assert totals is not None, "the reader must be able to open the file it was handed"
    return totals




def test_a_model_change_shows_before_any_further_turn(tmp_path: Path) -> None:
    totals = _scan(
        tmp_path,
        [
            _turn("claude-fable-5-1", "xhigh", "m1"),
            _command("Set model to `Opus 5` for this session only"),
        ],
    )
    assert totals.last_model == "claude-opus-5"
    assert totals.input_tokens == 10
    assert totals.output_tokens == 5


def test_an_effort_change_shows_before_any_further_turn(tmp_path: Path) -> None:
    totals = _scan(
        tmp_path,
        [
            _turn("claude-opus-5", "high", "m1"),
            _command("Set effort level to xhigh (this session only): Deeper reasoning"),
        ],
    )
    assert totals.last_effort == "xhigh"
    assert totals.last_model == "claude-opus-5"


def test_a_model_change_leaves_the_effort_beside_it_alone(tmp_path: Path) -> None:
    totals = _scan(
        tmp_path,
        [
            _turn("claude-opus-5", "xhigh", "m1"),
            _command("Set model to `Sonnet 5` and saved as your default for new sessions"),
        ],
    )
    assert totals.last_model == "claude-sonnet-5"
    assert totals.last_effort == "xhigh"


def test_a_later_turn_overwrites_an_earlier_selection(tmp_path: Path) -> None:
    totals = _scan(
        tmp_path,
        [
            _command("Set model to `Sonnet 5` for this session only"),
            _turn("claude-opus-5", "high", "m1"),
        ],
    )
    assert totals.last_model == "claude-opus-5"
    assert totals.last_effort == "high"


def test_the_older_user_record_shape_reads_the_same(tmp_path: Path) -> None:
    totals = _scan(
        tmp_path,
        [
            _turn("claude-fable-5-1", "high", "m1"),
            _legacy_command("Set model to \x1b[1mOpus 5 (1M context)\x1b[22m "
                            "and saved as your default for new sessions"),
        ],
    )
    assert totals.last_model == "claude-opus-5"


def test_a_context_window_suffix_is_the_same_model(tmp_path: Path) -> None:
    totals = _scan(
        tmp_path,
        [_command("Set model to `Opus 5 (1M context)` for this session only")],
    )
    assert totals.last_model == "claude-opus-5"
    assert totals.last_model_display is None




def test_an_unpriced_model_keeps_its_name_and_claims_no_id(tmp_path: Path) -> None:
    totals = _scan(
        tmp_path,
        [
            _turn("claude-opus-5", "high", "m1"),
            _command("Set model to `Fable 9000` for this session only"),
        ],
    )
    assert totals.last_model == "claude-opus-5", "an unresolved pick must not erase a known model"
    assert totals.last_model_display == "Fable 9000"
    assert totals.last_effort == "high"


def test_an_unpriced_pick_with_nothing_known_stays_null(tmp_path: Path) -> None:
    totals = _scan(
        tmp_path,
        [_command("Set model to `Fable 9000` for this session only")],
    )
    assert totals.last_model is None, "no id may be invented for an unpriced name"
    assert totals.last_model_display == "Fable 9000"


def test_a_resolved_pick_after_an_unresolved_one_clears_it(tmp_path: Path) -> None:
    totals = _scan(
        tmp_path,
        [
            _turn("claude-opus-5", "high", "m1"),
            _command("Set model to `Fable 9000` for this session only"),
            _command("Set model to `Sonnet 5` for this session only"),
        ],
    )
    assert totals.last_model == "claude-sonnet-5"
    assert totals.last_model_display is None


def test_the_opus_5_5_pick_resolves_to_its_own_id(tmp_path: Path) -> None:
    totals = _scan(
        tmp_path,
        [
            _turn("claude-opus-5", "high", "m1"),
            _legacy_command(
                "Set model to `Opus 5.5 (1M context)` and saved as your "
                "default for new sessions"
            ),
        ],
    )
    assert totals.last_model == "claude-opus-5-5"
    assert totals.last_model_display is None


def test_an_ordinary_message_mentioning_the_words_is_not_a_command(
    tmp_path: Path,
) -> None:
    totals = _scan(
        tmp_path,
        [
            _turn("claude-opus-5", "high", "m1"),
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Set model to `Sonnet 5` please"},
                    ],
                },
            },
        ],
    )
    assert totals.last_model == "claude-opus-5"


def test_only_the_element_body_is_the_command(tmp_path: Path) -> None:
    totals = _scan(
        tmp_path,
        [
            _turn("claude-opus-5", "high", "m1"),
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": "Set model to `Sonnet 5` for this session only "
                    "<local-command-stdout>nothing here</local-command-stdout>",
                },
            },
        ],
    )
    assert totals.last_model == "claude-opus-5"


def test_the_parser_answers_none_for_records_that_say_nothing() -> None:
    for record in (
        {"type": "assistant", "message": {"model": "claude-opus-5", "usage": {}}},
        {"type": "system", "subtype": "turn_duration", "content": "Set model to x"},
        {"type": "user", "message": {"role": "user", "content": "hello"}},
        {"type": "summary"},
        {},
    ):
        assert read_selection(record) is None, record




def test_switching_to_a_model_that_states_no_effort_clears_the_old_one(
    tmp_path: Path,
) -> None:
    totals = _scan(
        tmp_path,
        [
            _turn("claude-opus-5", "xhigh", "m1"),
            _turn("claude-haiku-4-5", None, "m2"),
        ],
    )
    assert totals.last_model == "claude-haiku-4-5"
    assert totals.last_effort is None


def test_a_record_naming_no_model_still_disturbs_neither(tmp_path: Path) -> None:
    totals = _scan(
        tmp_path,
        [
            _turn("claude-opus-5", "xhigh", "m1"),
            _turn(None, None, "m2"),
        ],
    )
    assert totals.last_model == "claude-opus-5"
    assert totals.last_effort == "xhigh"




def test_a_selection_in_an_appended_tail_is_seen(tmp_path: Path) -> None:
    path = tmp_path / "transcript.jsonl"
    cache = IncrementalCache()
    path.write_text(json.dumps(_turn("claude-fable-5-1", "xhigh", "m1")) + "\n")
    first = read_transcript_totals(path, cache=cache)
    assert first is not None and first.last_model == "claude-fable-5-1"

    with path.open("a") as handle:
        handle.write(
            json.dumps(_command("Set model to `Opus 5` for this session only")) + "\n"
        )
    second = read_transcript_totals(path, cache=cache)
    assert second is not None
    assert second.last_model == "claude-opus-5"
    assert second.input_tokens == 10




def test_the_ultracode_mark_follows_the_2_1_306_sentences(tmp_path: Path) -> None:
    def _command(text: str) -> Dict[str, Any]:
        return {
            "type": "system",
            "subtype": "local_command",
            "content": f"<local-command-stdout>{text}</local-command-stdout>",
        }

    toggle = "Ultracode on (this session only): dynamic workflows on every task. Effort stays xhigh."
    picker = "Set effort level to max (saved as your default for new sessions) \u00b7 Ultracode on"
    plain = "Set effort level to xhigh (this session only): Deeper reasoning"

    on = _scan(tmp_path, [_turn("claude-opus-5", "xhigh", "m1"), _command(toggle)])
    assert on.ultra_effort is True
    assert on.last_effort == "xhigh"

    picked = _scan(tmp_path, [_turn("claude-opus-5", "high", "m1"), _command(picker)])
    assert picked.ultra_effort is True
    assert picked.last_effort == "max"

    off = _scan(tmp_path, [_command(toggle), _command(plain)])
    assert off.ultra_effort is False
    assert off.last_effort == "xhigh"

    bogus = _command("Ultracode is great")
    assert read_selection(bogus) is None
    assert _scan(tmp_path, [_command(toggle), bogus]).ultra_effort is True
