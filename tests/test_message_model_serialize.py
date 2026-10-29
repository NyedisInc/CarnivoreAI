
from __future__ import annotations

import json

import pytest

from src.core.message_model_serialize import (
    APPEARANCE_KEYS,
    KEY_ORDER_NOT_AN_OBJECT,
    SERIALIZER_STYLES,
    STYLE_NAMES,
    canonical_json,
    identity_key,
    parse_line,
    render_line,
    render_with_style,
    session_ref_scheme,
    sha256_text,
    split_record,
    stored_body_json,
)

REAL_SHAPED_LINE = (
    '{"parentUuid":"p1","isSidechain":false,"userType":"external",'
    '"cwd":"/Users/j","sessionId":"s1","version":"2.0.76",'
    '"gitBranch":"main","type":"assistant",'
    '"message":{"role":"assistant","model":"claude-opus-5",'
    '"content":[{"type":"text","text":"hi"}]},'
    '"uuid":"u1","timestamp":"2026-01-01T00:00:00.000Z"}'
)


def _round_trip(line: str) -> str:
    value = json.loads(line)
    split = split_record(value)
    style = next((n for n in STYLE_NAMES if render_with_style(value, n) == line), None)
    assert style is not None, "no registered style reproduced the line"
    return render_line(split.body, split.envelope, split.key_order, style)



def test_a_real_shaped_line_round_trips_byte_exact():
    assert _round_trip(REAL_SHAPED_LINE) == REAL_SHAPED_LINE


def test_nested_key_order_survives_the_round_trip():
    line = '{"uuid":"u","message":{"role":"a","model":"m","content":"c"}}'
    assert _round_trip(line) == line


def test_an_envelope_key_in_the_middle_goes_back_to_the_middle():
    line = '{"a":1,"isSidechain":true,"b":2}'
    assert _round_trip(line) == line


def test_non_ascii_round_trips():
    line = '{"text":"café — done"}'
    assert _round_trip(line) == line



def test_only_the_measured_appearance_keys_leave_the_body():
    split = split_record(json.loads(REAL_SHAPED_LINE))
    assert set(split.envelope) == {"isSidechain"}
    for key in APPEARANCE_KEYS:
        assert key not in split.body


def test_key_order_difference_shares_a_meaning_hash_not_a_bytes_hash():
    one = split_record({"a": 1, "b": 2})
    two = split_record({"b": 2, "a": 1})
    assert one.body_sha256 == two.body_sha256
    assert one.body_bytes_sha256 != two.body_bytes_sha256


def test_a_genuinely_different_body_differs_on_both_hashes():
    one = split_record({"a": 1})
    two = split_record({"a": 2})
    assert one.body_sha256 != two.body_sha256
    assert one.body_bytes_sha256 != two.body_bytes_sha256


def test_a_non_object_line_is_kept_whole_and_marked_as_such():
    split = split_record(["a", "b"])
    assert split.key_order == KEY_ORDER_NOT_AN_OBJECT
    assert split.envelope == {}
    assert _round_trip('["a","b"]') == '["a","b"]'


def test_reassembly_refuses_to_emit_a_short_object():
    from src.core.message_model_serialize import reassemble
    with pytest.raises(KeyError):
        reassemble({"a": 1}, {}, ["a", "missing"])



def test_identity_key_has_no_null_to_be_exempted_by():
    assert identity_key(None, "ab") == ":ab"
    assert identity_key("u", "ab") == "u:ab"
    assert identity_key(None, "ab") != identity_key("", "ba")



def test_both_measured_agent_prefixes_are_recognised():
    assert session_ref_scheme("agent:a7b0a2e") == "agent"
    assert session_ref_scheme("agent-a00fdb4") == "agent"


def test_a_session_uuid_is_not_mistaken_for_an_agent_ref():
    assert session_ref_scheme("07e1cc0e-8a47-4029-8cfc-554f883ba28f") == "uuid"


def test_parse_line_names_its_three_outcomes():
    assert parse_line("   ")[0] == "blank"
    assert parse_line("{nope")[0] == "invalid_json"
    assert parse_line('{"a":1}') == ("ok", {"a": 1})


def test_canonical_and_stored_renderings_differ_where_it_matters():
    value = {"b": 1, "a": 2}
    assert canonical_json(value) == '{"a":2,"b":1}'
    assert stored_body_json(value) == '{"b":1,"a":2}'


def test_sha256_text_is_over_utf8_bytes():
    assert sha256_text("a") == sha256_text("a")
    assert sha256_text("é") != sha256_text("e")


def test_style_table_has_no_duplicate_names():
    names = [name for name, _, _ in SERIALIZER_STYLES]
    assert len(names) == len(set(names))
