
from __future__ import annotations

import math
import sqlite3

import pytest

from src.core.crate_format import canonical
from src.core.crate_format.canonical import RawText


def test_dumps_is_sorted_compact_utf8_with_one_newline() -> None:
    assert canonical.dumps({"b": 1, "a": "é", "c": [1, {"z": None, "y": True}]}) == (
        '{"a":"é","b":1,"c":[1,{"y":true,"z":null}]}\n'.encode("utf-8"))


def test_dumps_refuses_nan_and_infinity() -> None:
    for bad in (math.nan, math.inf):
        with pytest.raises(ValueError):
            canonical.dumps({"x": bad})


def test_loads_refuses_nan_literals() -> None:
    with pytest.raises(ValueError):
        canonical.loads(b'{"x": NaN}')
    with pytest.raises(ValueError):
        canonical.loads(b"\xff")


def test_jsonl_one_line_per_record() -> None:
    assert b"".join(canonical.jsonl([{"a": 1}, {"b": 2}])) == b'{"a":1}\n{"b":2}\n'


@pytest.mark.parametrize("value", [0, -5, 2**62, 1.5, -0.25, "text", "", None, b"", b"\x00\xff", RawText(b"\xff"),
                                   math.inf, -math.inf])
def test_encode_decode_round_trip(value) -> None:
    encoded = canonical.encode_value(value)
    canonical.dumps(encoded)
    back = canonical.decode_value(encoded)
    assert back == value and type(back) is type(value)


def test_text_and_blob_stay_apart() -> None:
    assert canonical.encode_value(b"\xff") == {"$b64": "/w=="}
    assert canonical.encode_value(RawText(b"\xff")) == {"$t64": "/w=="}
    assert canonical.encode_value(math.inf) == {"$f": "inf"}
    assert canonical.encode_value(-math.inf) == {"$f": "-inf"}


def test_encode_refuses_nan_and_non_sqlite_types() -> None:
    with pytest.raises(ValueError):
        canonical.encode_value(math.nan)
    with pytest.raises(ValueError):
        canonical.encode_value([1])


@pytest.mark.parametrize("bad", [{"$b64": "!!"}, {"$q": "x"}, {"$f": "nan"}, {"$b64": 1}, {"$b64": "", "x": 1}])
def test_decode_refuses_malformed_forms(bad) -> None:
    with pytest.raises(ValueError):
        canonical.decode_value(bad)


def test_text_factory_reads_invalid_utf8_text_without_failing() -> None:
    conn = sqlite3.connect(":memory:")
    conn.text_factory = canonical.text_factory
    conn.execute("CREATE TABLE t (v)")
    conn.execute("INSERT INTO t VALUES (CAST(X'FFFE41' AS TEXT)), ('ok'), (?)", (math.inf,))
    values = [row[0] for row in conn.execute("SELECT v FROM t ORDER BY rowid")]
    assert isinstance(values[0], RawText) and bytes(values[0]) == b"\xff\xfeA"
    assert values[1] == "ok"
    assert [canonical.encode_value(v) for v in values] == [{"$t64": "//5B"}, "ok", {"$f": "inf"}]
