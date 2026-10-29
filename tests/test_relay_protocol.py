
from __future__ import annotations

import pytest

from relay.auth import publisher_token_ok, sha256_hex, watch_token_ok
from relay.config import (
    DEFAULT_IDLE_FLUSH_MS,
    DEFAULT_PORT,
    DEFAULT_TAIL_BYTES,
    RelayConfigError,
    settings_from_env,
)
from relay.protocol import (
    WATCH_SUBPROTOCOL,
    ProtocolError,
    frame_type,
    parse_data_frame,
    parse_links_frame,
    token_from_subprotocols,
)
from relay.publish_socket import bearer_token
from tests.relay_support import sha256_of

GOOD_DIGEST = sha256_of("token-a")


class FakeHeaders:

    def __init__(self, **headers: str) -> None:
        self.headers = {key.replace("_", "-"): value for key, value in headers.items()}




def test_a_valid_links_frame_parses_into_declarations():
    frame = {
        "type": "links",
        "links": [
            {
                "link_id": "l1",
                "token_sha256": GOOD_DIGEST,
                "session_id": "ses_1",
            }
        ],
    }
    declared = parse_links_frame(frame)
    assert len(declared) == 1
    assert declared[0].link_id == "l1"
    assert declared[0].token_sha256 == GOOD_DIGEST
    assert declared[0].session_id == "ses_1"


def test_an_empty_links_frame_is_a_valid_declaration_of_nothing():
    assert parse_links_frame({"type": "links", "links": []}) == []


@pytest.mark.parametrize(
    "digest",
    [
        "",
        "abc",
        GOOD_DIGEST.upper(),
        GOOD_DIGEST + "0",
        "z" * 64,
        None,
        12345,
    ],
)
def test_a_malformed_digest_is_refused(digest):
    frame = {
        "type": "links",
        "links": [
            {"link_id": "l1", "token_sha256": digest, "session_id": "s"}
        ],
    }
    with pytest.raises(ProtocolError):
        parse_links_frame(frame)


@pytest.mark.parametrize(
    "frame",
    [
        "not an object",
        {"type": "links"},
        {"type": "links", "links": "nope"},
        {"type": "links", "links": ["nope"]},
        {"type": "links", "links": [{"token_sha256": GOOD_DIGEST}]},
        {
            "type": "links",
            "links": [
                {"link_id": "", "token_sha256": GOOD_DIGEST, "session_id": "s"}
            ],
        },
        {
            "type": "links",
            "links": [
                {
                    "link_id": "x" * 200,
                    "token_sha256": GOOD_DIGEST,
                    "session_id": "s",
                }
            ],
        },
    ],
)
def test_a_malformed_links_frame_is_refused(frame):
    with pytest.raises(ProtocolError):
        parse_links_frame(frame)


def test_a_link_declared_twice_in_one_frame_is_refused():
    entry = {"link_id": "l1", "token_sha256": GOOD_DIGEST, "session_id": "s"}
    with pytest.raises(ProtocolError):
        parse_links_frame({"type": "links", "links": [entry, dict(entry)]})




def test_a_valid_data_frame_parses():
    parsed = parse_data_frame(
        {"type": "data", "link_id": "l1", "payload": "raw text"}
    )
    assert parsed.link_id == "l1"
    assert parsed.payload == "raw text"


@pytest.mark.parametrize(
    "frame",
    [
        {"type": "data", "link_id": "l1"},
        {"type": "data", "link_id": "l1", "payload": 42},
        {"type": "data", "link_id": "", "payload": "x"},
        {"type": "data", "payload": "x"},
        [],
    ],
)
def test_a_malformed_data_frame_is_refused(frame):
    with pytest.raises(ProtocolError):
        parse_data_frame(frame)


def test_frame_type_never_trusts_the_rest_of_the_frame():
    assert frame_type({"type": "data"}) == "data"
    assert frame_type({"type": 7}) == ""
    assert frame_type({}) == ""
    assert frame_type("nonsense") == ""




def test_publisher_token_compare_answers_correctly():
    assert publisher_token_ok("abc", "abc") is True
    assert publisher_token_ok("abd", "abc") is False
    assert publisher_token_ok("ab", "abc") is False
    assert publisher_token_ok(None, "abc") is False
    assert publisher_token_ok("", "abc") is False


def test_a_blank_configured_token_never_opens_the_door():
    assert publisher_token_ok("", "") is False
    assert publisher_token_ok(None, "") is False
    assert publisher_token_ok("anything", "") is False


def test_watch_token_matches_only_its_own_declared_digest():
    assert watch_token_ok("token-a", GOOD_DIGEST) is True
    assert watch_token_ok("token-b", GOOD_DIGEST) is False
    assert watch_token_ok("", GOOD_DIGEST) is False
    assert watch_token_ok(None, GOOD_DIGEST) is False


def test_an_unknown_link_refuses_every_token():
    assert watch_token_ok("token-a", None) is False
    assert watch_token_ok("anything at all", None) is False


def test_sha256_hex_is_the_real_thing():
    assert sha256_hex("abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )




def test_token_comes_out_of_the_subprotocol_companion_entry():
    assert token_from_subprotocols((WATCH_SUBPROTOCOL, "tok"), WATCH_SUBPROTOCOL) == "tok"
    assert token_from_subprotocols(("tok", WATCH_SUBPROTOCOL), WATCH_SUBPROTOCOL) == "tok"
    assert token_from_subprotocols((WATCH_SUBPROTOCOL,), WATCH_SUBPROTOCOL) == ""
    assert token_from_subprotocols(("tok",), WATCH_SUBPROTOCOL) == ""
    assert token_from_subprotocols((), WATCH_SUBPROTOCOL) == ""


def test_bearer_token_reads_only_a_bearer_header():
    assert bearer_token(FakeHeaders(authorization="Bearer abc")) == "abc"
    assert bearer_token(FakeHeaders(authorization="bearer abc")) == "abc"
    assert bearer_token(FakeHeaders(authorization="Basic abc")) is None
    assert bearer_token(FakeHeaders(authorization="abc")) is None
    assert bearer_token(FakeHeaders(authorization="Bearer   ")) is None
    assert bearer_token(FakeHeaders()) is None




def test_settings_require_a_publish_token():
    with pytest.raises(RelayConfigError):
        settings_from_env({})
    with pytest.raises(RelayConfigError):
        settings_from_env({"RELAY_PUBLISH_TOKEN": "   "})


def test_settings_defaults_are_the_documented_ones():
    settings = settings_from_env({"RELAY_PUBLISH_TOKEN": "s"})
    assert settings.tail_bytes == DEFAULT_TAIL_BYTES == 2048
    assert settings.idle_flush_ms == DEFAULT_IDLE_FLUSH_MS == 200
    assert settings.port == DEFAULT_PORT == 8080


def test_settings_read_the_environment_overrides():
    settings = settings_from_env(
        {
            "RELAY_PUBLISH_TOKEN": "s",
            "RELAY_TAIL_BYTES": "4096",
            "RELAY_IDLE_FLUSH_MS": "75",
            "PORT": "9001",
        }
    )
    assert settings.tail_bytes == 4096
    assert settings.idle_flush_ms == 75
    assert settings.port == 9001


@pytest.mark.parametrize("bad", ["0", "-1", "abc", "1.5"])
def test_a_present_but_unusable_number_raises(bad):
    with pytest.raises(RelayConfigError):
        settings_from_env({"RELAY_PUBLISH_TOKEN": "s", "PORT": bad})




def test_a_size_frame_is_bounded_integers_and_nothing_else():
    from relay.protocol import MAX_COLS, MAX_ROWS, parse_size_frame

    def frame(**fields):
        return {"type": "size", "link_id": "l", "cols": 170, "rows": 50, **fields}

    parsed = parse_size_frame(frame())
    assert (parsed.link_id, parsed.cols, parsed.rows) == ("l", 170, 50)
    assert (MAX_COLS, MAX_ROWS) == (1000, 500)
    assert parse_size_frame(frame(cols=1, rows=1)).cols == 1
    assert parse_size_frame(frame(cols=1000, rows=500)).rows == 500
    for bad in (frame(cols=0), frame(cols=1001), frame(rows=0), frame(rows=501),
                frame(cols=True), frame(rows=24.0), frame(cols="80"), frame(cols=None),
                frame(link_id=""), frame(link_id=7), "not an object"):
        with pytest.raises(ProtocolError):
            parse_size_frame(bad)
