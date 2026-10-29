
from __future__ import annotations

import json
import secrets
import string

import pytest

from src.cplugs.crate import share as S
from src.cplugs.sdk import crate_sources as cs

HOME = "/Users/nobody-here"


def _secret() -> str:
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))


def _line(secret: str) -> bytes:
    inner = json.dumps({"api_key": secret})
    assert cs.scan_counts(inner), "the credential must be one the detectors find when decoded"
    content = json.dumps({"result": inner})
    return json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": content}]}}).encode() \
        + b"\n"


def test_a_jsonl_line_with_doubly_nested_json_is_starred() -> None:
    secret = _secret()
    stats = S.ShareStats()
    out = S.share_line(_line(secret), stats, S.HomeScrub.of(HOME), member="m", number=1, may_be_torn=False)
    assert secret not in out.decode() and out.endswith(b"\n")
    json.loads(out)
    assert sum(stats.findings.values()) >= 1


def test_a_text_file_holding_nested_json_is_starred() -> None:
    secret = _secret()
    text = json.dumps({"result": json.dumps({"api_key": secret})})
    assert not cs.scan_counts(text), "the raw text alone hides it"
    out = S.transform_text(text.encode(), S.ShareStats(), member="tool-results/x.txt", home=HOME)
    assert out is not None and secret not in out.decode()
    assert json.loads(out)["result"]


def test_a_plain_text_file_with_an_escaped_credential_fails_closed() -> None:
    secret = _secret()
    text = 'tool said: {\\"api_key\\": \\"' + secret + '\\"} and nothing more'
    assert not cs.scan_counts(text)
    with pytest.raises(S.ShareResidualSecret):
        S.transform_text(text.encode(), S.ShareStats(), member="tool-results/y.txt", home=HOME)


def test_text_without_any_credential_is_unchanged() -> None:
    text = json.dumps({"result": json.dumps({"rows": [1, 2, 3], "note": "nothing to hide"})}, indent=2)
    assert S.transform_text(text.encode(), S.ShareStats(), member="z.txt", home=HOME) == text.encode()
    plain = 'a quote \\"here\\" and a path \\\\tmp'
    assert S.transform_text(plain.encode(), S.ShareStats(), member="p.txt", home=HOME) == plain.encode()
