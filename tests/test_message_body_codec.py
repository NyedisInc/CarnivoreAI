
from __future__ import annotations

import os
import sqlite3
import sys
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.message_body_codec import (
    BODY_FRAME_HEADER_BYTES,
    BODY_FRAME_MAGIC,
    BodyCodecError,
    body_chars,
    decode_body,
    encode_body,
    is_compressed,
    register_body_functions,
)

SAMPLE = (
    '{"type":"assistant","message":{"role":"assistant","content":'
    '[{"type":"text","text":"café naïve über '
    + "the quick brown fox jumps over the lazy dog " * 20
    + '"}]}}'
)


def test_a_round_trip_returns_the_same_string() -> None:
    assert decode_body(encode_body(SAMPLE)) == SAMPLE


def test_text_passes_through_unchanged() -> None:
    assert decode_body(SAMPLE) is SAMPLE
    assert body_chars(SAMPLE) == len(SAMPLE)


def test_the_character_count_is_code_points_not_bytes() -> None:
    framed = encode_body(SAMPLE)
    assert len(SAMPLE.encode("utf-8")) != len(SAMPLE), (
        "the sample must be multi-byte or this test proves nothing")
    assert body_chars(framed) == len(SAMPLE)


def test_the_length_is_read_without_inflating() -> None:
    framed = encode_body(SAMPLE)
    truncated = framed[:BODY_FRAME_HEADER_BYTES + 4]
    assert body_chars(truncated) == len(SAMPLE)
    with pytest.raises(BodyCodecError):
        decode_body(truncated)


def test_a_blob_without_the_magic_is_refused() -> None:
    foreign = zlib.compress(b"not ours", 6)
    assert not is_compressed(foreign)
    with pytest.raises(BodyCodecError) as exc:
        decode_body(foreign)
    assert "frame magic" in str(exc.value)


def test_a_frame_whose_count_lies_is_refused() -> None:
    framed = bytearray(encode_body(SAMPLE))
    framed[len(BODY_FRAME_MAGIC)] = (framed[len(BODY_FRAME_MAGIC)] + 1) % 256
    with pytest.raises(BodyCodecError) as exc:
        decode_body(bytes(framed))
    assert "disagree" in str(exc.value)


def test_a_short_frame_is_refused() -> None:
    with pytest.raises(BodyCodecError):
        body_chars(BODY_FRAME_MAGIC + b"\x01")


def test_a_non_text_non_blob_value_is_refused() -> None:
    with pytest.raises(BodyCodecError):
        decode_body(7)  # type: ignore[arg-type]
    with pytest.raises(BodyCodecError):
        body_chars(None)  # type: ignore[arg-type]


def test_encode_refuses_a_non_string() -> None:
    with pytest.raises(TypeError):
        encode_body(b"already bytes")  # type: ignore[arg-type]


def _mixed_table(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(tmp_path / "mixed.db"))
    conn.execute("CREATE TABLE message_bodies (id INTEGER PRIMARY KEY, "
                 "body_json TEXT NOT NULL)")
    conn.execute("INSERT INTO message_bodies VALUES (1, ?)", (SAMPLE,))
    conn.execute("INSERT INTO message_bodies VALUES (2, ?)",
                 (encode_body(SAMPLE),))
    conn.execute("INSERT INTO message_bodies VALUES (3, ?)", ("{}",))
    register_body_functions(conn)
    return conn


def test_the_sql_functions_agree_across_both_shapes(tmp_path: Path) -> None:
    conn = _mixed_table(tmp_path)
    try:
        rows = dict(conn.execute(
            "SELECT id, cloude_body_text(body_json) FROM message_bodies"))
        lengths = dict(conn.execute(
            "SELECT id, cloude_body_chars(body_json) FROM message_bodies"))
        shapes = dict(conn.execute(
            "SELECT id, typeof(body_json) FROM message_bodies"))
    finally:
        conn.close()
    assert shapes == {1: "text", 2: "blob", 3: "text"}, (
        "the fixture must actually hold both shapes")
    assert rows[1] == rows[2] == SAMPLE
    assert lengths[1] == lengths[2] == len(SAMPLE)


def test_the_naive_reader_is_wrong_on_the_compressed_row(
    tmp_path: Path,
) -> None:
    conn = _mixed_table(tmp_path)
    try:
        naive = dict(conn.execute(
            "SELECT id, LENGTH(body_json) FROM message_bodies"))
        cut = dict(conn.execute(
            "SELECT id, SUBSTR(body_json, 1, 4) FROM message_bodies"))
        found = dict(conn.execute(
            "SELECT id, INSTR(body_json, 'assistant') FROM message_bodies"))
        valid = dict(conn.execute(
            "SELECT id, json_valid(body_json) FROM message_bodies"))
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(
                "SELECT json_extract(body_json, '$.type') FROM message_bodies "
                "WHERE id = 2").fetchone()
    finally:
        conn.close()
    assert naive[1] == len(SAMPLE)
    assert naive[2] != len(SAMPLE), (
        "LENGTH over the frame must differ, or this control proves nothing")
    assert isinstance(cut[1], str) and isinstance(cut[2], bytes), (
        "SUBSTR over the frame cuts the zlib stream and returns bytes")
    assert found[1] > 0 and found[2] == 0, (
        "INSTR over the frame silently answers 0 - the search defect this "
        "whole change is coupled to")
    assert valid[1] == 1 and valid[2] == 0


def test_an_unregistered_connection_fails_loudly(tmp_path: Path) -> None:
    conn = sqlite3.connect(str(tmp_path / "bare.db"))
    try:
        conn.execute("CREATE TABLE t (v TEXT)")
        conn.execute("INSERT INTO t VALUES (?)", (SAMPLE,))
        with pytest.raises(sqlite3.OperationalError) as exc:
            conn.execute("SELECT cloude_body_text(v) FROM t").fetchone()
        assert "no such function" in str(exc.value)
    finally:
        conn.close()
