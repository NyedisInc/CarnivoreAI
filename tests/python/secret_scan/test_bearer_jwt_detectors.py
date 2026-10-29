
from __future__ import annotations

import base64
import os

from src.core.message_model_secrets import DETECTOR_BEARER_TOKEN, DETECTOR_JWT, scan_text
from src.core.stream_redactor import StreamRedactor


def _b64url(n: int) -> str:
    return base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")


def _jwt() -> str:
    return ".".join(["eyJ" + _b64url(20), "eyJ" + _b64url(20), _b64url(24)])


def _names(text: str) -> set[str]:
    return {f.detector for f in scan_text(text, trust_vendor_marker=True)}


def test_bearer_fires_and_placeholders_do_not():
    token = _b64url(30)
    assert DETECTOR_BEARER_TOKEN in _names(f"Authorization: Bearer {token}")
    assert DETECTOR_BEARER_TOKEN not in _names("Authorization: Bearer ${TOKEN}")
    assert DETECTOR_BEARER_TOKEN not in _names("Authorization: Bearer <token>")
    assert DETECTOR_BEARER_TOKEN not in _names("the bearer of good news")


def test_jwt_fires_and_a_plain_dotted_path_does_not():
    assert DETECTOR_JWT in _names(f"token {_jwt()} end")
    assert DETECTOR_JWT not in _names("eyJ.eyJ.x and some.module.path")


def test_stream_redactor_stars_both():
    token, jwt = _b64url(30), _jwt()
    r = StreamRedactor()
    out = r.feed(f"Bearer {token}\nx {jwt}\n") + r.flush(end=True)
    assert token not in out and jwt not in out and "Bearer" in out
