
from __future__ import annotations

import base64
import os
import re

from src.core.message_model_secrets import DETECTOR_BEARER_TOKEN, DETECTOR_JWT, scan_text
from src.core.stream_redactor import StreamRedactor


def _b64url(n: int) -> str:
    while True:
        out = base64.urlsafe_b64encode(os.urandom(n)).decode().rstrip("=")
        if "hf_" not in out:
            return out


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


def _jwe(key: str | None = None) -> str:
    return ".".join(["eyJ" + _b64url(20), _b64url(30) if key is None else key, _b64url(12), _b64url(24), _b64url(16)])


def test_a_five_part_jwe_is_detected_bare_and_with_an_empty_key_part():
    assert DETECTOR_JWT in _names(f"token {_jwe()} end")
    assert DETECTOR_JWT in _names(f"token {_jwe('')} end")


def test_a_placeholder_jwe_and_dotted_text_are_not_detected():
    assert DETECTOR_JWT not in _names("eyJ.a.b.c.d and one.two.three.four.five")
    assert DETECTOR_JWT not in _names("eyJhbGciOiJkaXIifQ.<key>.<iv>.<ciphertext>.<tag>")
    assert DETECTOR_JWT not in _names("eyJhbGciOiJkaXIifQ..short.short.short")


def _assert_every_segment_starred(jwe: str) -> None:
    r = StreamRedactor()
    out = r.feed(f"x {jwe}\n") + r.flush(end=True)
    for segment in filter(None, jwe.split(".")):
        assert segment not in out, segment[:6]


def test_stream_redactor_stars_every_segment_of_a_jwe():
    _assert_every_segment_starred(_jwe())
    _assert_every_segment_starred(_jwe(""))


def test_a_jwe_whose_key_part_starts_eyj_is_redacted_whole():
    jwe = _jwe("eyJ" + _b64url(30))
    assert [f.length for f in scan_text(jwe, trust_vendor_marker=True) if f.detector == DETECTOR_JWT] == [len(jwe)]
    _assert_every_segment_starred(jwe)


def test_a_long_run_of_eyj_with_no_dots_scans_in_linear_time():
    import time

    from src.core.message_model_secret_redaction import JWT

    started = time.monotonic()
    JWT.search("eyJ" * 70_000)
    assert time.monotonic() - started < 2.0


_GLUES = ("abc", "a_", "9", "x-")


def _glued_tokens() -> list[tuple[str, str]]:
    import random

    rng = random.Random(2673)
    part = lambda n: "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz0123456789") for _ in range(n))  # noqa: E731
    tokens = [
        f"eyJ{part(20)}.eyJ{part(20)}.{part(24)}",
        f"eyJ{part(20)}.{part(30)}.{part(12)}.{part(24)}.{part(16)}",
        f"eyJ{part(20)}..{part(12)}.{part(24)}.{part(16)}",
    ]
    return [(g, t) for g in _GLUES for t in tokens]


def test_a_jwt_glued_after_a_word_character_is_redacted_whole():
    from src.core.stream_redactor import redact_whole

    for glue, token in _glued_tokens():
        out = redact_whole(f"see {glue}{token} end")
        for segment in filter(None, token.split(".")):
            assert segment not in out, (glue, segment[:6])


def test_a_glued_jwt_is_found_by_the_scan_and_counted_by_the_file_scan():
    from src.cplugs.sdk import file_secrets

    for glue, token in _glued_tokens():
        found = [f for f in scan_text(f"{glue}{token}", trust_vendor_marker=True) if f.detector == DETECTOR_JWT]
        assert [(f.offset, f.length) for f in found] == [(len(glue), len(token))], glue
        assert file_secrets.credential_counts(f"x={glue}{token}") == {"jwt": 1}, glue


def test_a_dotted_prefix_does_not_hide_a_jwt_and_partial_tokens_still_match_whole():
    token = _jwt()
    assert [f.length for f in scan_text(f"a.{token}", trust_vendor_marker=True) if f.detector == DETECTOR_JWT] == [len(token)]
    jwe = _jwe("eyJ" + _b64url(30))
    assert [f.length for f in scan_text(f"abc{jwe}", trust_vendor_marker=True) if f.detector == DETECTOR_JWT] == [len(jwe)]


def test_the_jwt_pattern_stays_linear_on_dots_eyj_runs_and_glued_prefixes():
    import time

    from src.core.message_model_secret_redaction import JWT

    shapes = (".", "eyJ", "a" * 50_000 + "eyJ", "eyJ" * 50_000 + ".x", "abc" + "eyJ" * 50_000 + ".eyJ" * 3)
    for shape in shapes:
        text = shape * 50_000 if len(shape) < 10 else shape
        started = time.monotonic()
        JWT.search(text)
        assert time.monotonic() - started < 1.0, shape[:8]


def _vendor_key(prefix: str, n: int) -> str:
    import random

    rng = random.Random(prefix)
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ234567" if prefix == "AKIA" else "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return prefix + "".join(rng.choice(alphabet) for _ in range(n))


def test_a_jwt_glued_after_a_vendor_key_is_not_hidden_by_the_key():
    from src.core.stream_redactor import redact_whole
    from src.cplugs.sdk import file_secrets

    token = _seeded_jwt()
    for key, glue in ((_vendor_key("AKIA", 16), "-"), (_vendor_key("ghp_", 36), "_")):
        text = f"{key}{glue}{token}"
        out = redact_whole(text)
        assert not any(seg in out for seg in token.split(".")), key[:4]
        assert DETECTOR_JWT in {f.detector for f in scan_text(text, trust_vendor_marker=True)}, key[:4]
        assert file_secrets.credential_counts(text).get("jwt") == 1, key[:4]


def _seeded_jwt() -> str:
    import random

    rng = random.Random(7)
    part = lambda n: "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(n))  # noqa: E731
    return f"eyJ{part(20)}.eyJ{part(20)}.{part(24)}"


def _b64_json(obj: dict) -> str:
    import json

    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")


def test_the_tempered_prefix_compiles_without_an_atomic_group():
    from src.core.message_model_secret_redaction import JWT_SOURCE

    assert "(?>" not in JWT_SOURCE and "}+" not in JWT_SOURCE


def test_a_real_jwt_whose_base64_holds_a_placeholder_word_is_still_counted():
    from src.cplugs.sdk import file_secrets

    for word in ("test", "abcd", "Your", "FAKE", "0000", "xxxx", "dummy", "todo"):
        sig = f"Q9{word}Z7kLm3Pq8Rt2Vw"
        jws = f"eyJ{_b64url(20)}.eyJ{_b64url(20)}.{sig}"
        jwe = f"eyJ{_b64url(20)}.{_b64url(30)}.{word}K8mQ3zWp.{_b64url(24)}.{_b64url(16)}"
        for token in (jws, jwe):
            assert file_secrets.credential_counts(f"x={token}") == {"jwt": 1}, word


def test_a_jwt_with_an_obvious_stand_in_claim_is_a_placeholder():
    from src.cplugs.sdk import file_secrets

    header = _b64_json({"alg": "HS256", "typ": "JWT"})
    sig = _b64url(24)
    for claims in (
        {"sub": "your-user-id"},
        {"sub": "<your-user-id>"},
        {"sub": "your-user-id", "email": "<email>"},
        {"sub": " PLACEHOLDER ", "jti": "u-81723"},
        {"email": "<email>", "client_id": "xxxxxxxx"},
        {"sub": "------"},
    ):
        token = f"{header}.{_b64_json(claims)}.{sig}"
        assert file_secrets.credential_counts(f"x={token}") == {}, claims
    sample = f"{header}.{_b64_json({'sub': '1234567890', 'name': 'John Doe'})}.{sig}"
    assert file_secrets.credential_counts(f"x={sample}") == {"jwt": 1}


def test_real_claims_that_merely_contain_a_stand_in_word_are_still_counted():
    from src.cplugs.sdk import file_secrets

    header = {"alg": "RS256", "typ": "JWT"}
    for claims in (
        {"iss": "https://auth.example.com/"},
        {"email": "jo@example.org"},
        {"iss": "http://localhost:8080/realms/example"},
        {"aud": "my-sample-api"},
        {"scope": "rows:insert rows:replace"},
        {"app": "todo-web", "name": "Ann Yourkevich"},
    ):
        token = f"{_b64_json(header)}.{_b64_json(claims)}.{_b64url(64)}"
        assert file_secrets.credential_counts(f"x={token}") == {"jwt": 1}, claims
    jwe = ".".join([_b64_json({"alg": "RSA-OAEP", "kid": "example-key"}), _b64url(64), _b64url(12), _b64url(24), _b64url(16)])
    assert file_secrets.credential_counts(f"x={jwe}") == {"jwt": 1}


def test_a_deeply_nested_payload_does_not_crash_the_scan_and_the_token_is_counted():
    from src.cplugs.sdk import file_secrets

    noise = re.sub(r"(.)\1{2,}", r"\1", _b64url(300_000))
    deep = f'{{"a":{"[" * 100_000}"{noise}"{"]" * 100_000}}}'.encode()
    token = f"{_b64_json({'alg': 'RS256'})}.{base64.urlsafe_b64encode(deep).decode().rstrip('=')}.{_b64url(24)}"
    assert token.split(".")[1].startswith("eyJ")
    assert file_secrets.credential_counts(f"x={token}") == {"jwt": 1}


def test_a_recursion_error_from_the_json_decoder_reads_as_not_a_placeholder(monkeypatch):
    from src.core import message_model_secret_guards as guards
    from src.cplugs.sdk import file_secrets

    def _too_deep(*_: object, **__: object) -> None:
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(guards.json, "loads", _too_deep)
    token = f"{_b64_json({'alg': 'RS256'})}.{_b64_json({'sub': 'u-81723'})}.{_b64url(64)}"
    assert file_secrets.credential_counts(f"x={token}") == {"jwt": 1}


def test_one_stand_in_value_elsewhere_never_hides_a_real_token():
    from src.cplugs.sdk import file_secrets

    real_sub = {"sub": "u-81723"}
    cases = (
        ({"alg": "RS256"}, {**real_sub, "jti": "xxxxxxxx"}),
        ({"alg": "RS256"}, {**real_sub, "nonce": "00000000"}),
        ({"alg": "RS256"}, {**real_sub, "groups": ["<none>"]}),
        ({"alg": "RS256"}, {**real_sub, "address": {"street": "<redacted>"}}),
        ({"alg": "RS256", "kid": "placeholder"}, real_sub),
        ({"alg": "RS256"}, {"email": "jo@acme.io", "preferred_username": "<name>"}),
        ({"alg": "RS256"}, {"jti": "xxxxxxxx"}),
    )
    for header, claims in cases:
        token = f"{_b64_json(header)}.{_b64_json(claims)}.{_b64url(64)}"
        assert file_secrets.credential_counts(f"x={token}") == {"jwt": 1}, (header, claims)


def test_a_jwe_is_never_dropped_on_claims():
    from src.cplugs.sdk import file_secrets

    for header in ({"alg": "dir", "kid": "<your-key>"}, {"sub": "your-user-id", "alg": "dir"}):
        jwe = ".".join([_b64_json(header), _b64url(30), _b64url(12), _b64url(24), _b64url(16)])
        assert file_secrets.credential_counts(f"x={jwe}") == {"jwt": 1}, header


def test_a_numeric_sub_of_one_repeated_digit_is_a_real_id_and_is_counted():
    from src.cplugs.sdk import file_secrets

    for sub in ("1111", "77777", "00000000"):
        token = f"{_b64_json({'alg': 'RS256'})}.{_b64_json({'sub': sub})}.{_b64url(64)}"
        assert file_secrets.credential_counts(f"x={token}") == {"jwt": 1}, sub
