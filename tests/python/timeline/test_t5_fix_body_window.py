
from __future__ import annotations

import json
from typing import Any, Tuple

import pytest

from src.core.cross_session_search import strip_ansi
from src.core.stream_redactor import redact_whole
from src.core.timeline import bodies
from tests.python.timeline.exposure_helpers import CONV
from tests.python.timeline.test_t5_fix_reads import KEY, _url

SMALL_LINE = 200_000


def _line(main: Any, text: str) -> None:
    record = {"type": "user", "uuid": "u-big", "timestamp": "2026-11-01T10:00:00.000Z", "message": {"role": "user", "content": text}}
    main.parent.mkdir(parents=True, exist_ok=True)
    main.write_bytes(json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode() + b"\n")


def _body(client: Any, main: Any, monkeypatch: pytest.MonkeyPatch, text: str) -> Tuple[str, str, bool]:
    monkeypatch.setattr(bodies, "MAX_LINE_BYTES", SMALL_LINE)
    _line(main, text)
    listed = client.get(_url("events"), params={"after": f"{CONV}:main:0:"}).json()["events"]
    shown = client.get(_url(f"events/{listed[0]['id']}")).json()
    whole = main.read_bytes()[:-1].decode("utf-8")
    return shown["body"], redact_whole(strip_ansi(whole))[:bodies.MAX_BODY_CHARS], shown["truncated"]


def test_cjk_text_over_the_byte_window_still_shows_the_full_cut(api, monkeypatch: pytest.MonkeyPatch) -> None:
    client, main = api
    text = "漢字カナ🙂" * 30000
    shown, expected, truncated = _body(client, main, monkeypatch, text)
    assert truncated is True and len(expected) == bodies.MAX_BODY_CHARS and shown == expected


def test_heavy_ansi_stripping_does_not_shrink_the_shown_text() -> None:
    raw = ("\x1b[31mab\x1b[0m" * 60000).encode()
    shown, truncated = bodies.clean_prefix(raw)
    assert truncated is True and shown == redact_whole(strip_ansi(raw.decode()))[:bodies.MAX_BODY_CHARS] and len(shown) == bodies.MAX_BODY_CHARS


def test_a_credential_straddling_the_cut_of_multibyte_text_is_starred(api, monkeypatch: pytest.MonkeyPatch) -> None:
    client, main = api
    lead = bodies.MAX_BODY_CHARS - 10
    text = "漢" * lead + KEY + "字" * 70000
    shown, expected, truncated = _body(client, main, monkeypatch, text)
    assert truncated is True and KEY[:8] not in shown and shown == expected
