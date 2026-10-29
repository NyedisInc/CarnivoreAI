
from __future__ import annotations

import random
import time
from typing import Callable, List, Sequence

import pytest

from src.core.message_model_secrets import DETECTOR_JWT, scan_text
from src.core.stream_redactor import redact_whole
from src.cplugs.sdk.file_secrets import credential_counts

_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
_RNG = random.Random(2687)


def _seg(n: int) -> str:
    return "".join(_RNG.choice(_ALPHABET) for _ in range(n))


def _jws() -> str:
    return f"eyJ{_seg(30)}.eyJ{_seg(60)}.{_seg(43)}"


def _jwe(ciphertext: str = "") -> str:
    return ".".join([f"eyJ{_seg(30)}", "", _seg(16), ciphertext or _seg(40), _seg(22)])


def _visible(token: str, out: str) -> List[str]:
    return [p[i:i + 8] for p in _parts(token) for i in range(len(p) - 7) if p[i:i + 8] in out]


def _parts(token: str) -> List[str]:
    return [p for p in token.split(".") if len(p) >= 6]


_SHAPES: Sequence[Callable[[], List[str]]] = (
    lambda: [_jws(), _jws(), _jws()],
    lambda: [_jwe(), _jwe()],
    lambda: [_jwe(), _jws()],
    lambda: [_jws(), _jwe()],
)


@pytest.mark.parametrize("joiner", ["-", "_"])
@pytest.mark.parametrize("shape", range(len(_SHAPES)))
def test_chained_tokens_are_fully_redacted(shape: int, joiner: str) -> None:
    tokens = _SHAPES[shape]()
    text = f"x {joiner.join(tokens)} y"
    out = redact_whole(text)
    assert [p for t in tokens for p in _parts(t) if p in out] == []
    spans = [(f.offset, f.offset + f.length) for f in scan_text(text, trust_vendor_marker=True) if f.detector == DETECTOR_JWT]
    for t in tokens:
        start = text.index(t)
        assert any(s <= start and start + len(t) <= e for s, e in spans)
    assert credential_counts(text).get(DETECTOR_JWT) == len(tokens)


def test_decoy_header_before_a_jws_does_not_expose_the_signature() -> None:
    token = _jws()
    text = f"id eyJ{_seg(12)}.{token} end"
    out = redact_whole(text)
    assert [p for p in _parts(token) if p in out] == []
    assert credential_counts(text).get(DETECTOR_JWT) == 1


@pytest.mark.parametrize("ciphertext", ["a", "Zq4", "Zq4Xk92"])
def test_jwe_with_short_ciphertext_is_redacted(ciphertext: str) -> None:
    token = _jwe(ciphertext)
    text = f" {token} "
    out = redact_whole(text)
    assert [p for p in _parts(token) if p in out] == []
    assert credential_counts(text).get(DETECTOR_JWT) == 1


def test_plain_jws_and_two_by_space_still_match_once_each() -> None:
    a, b = _jws(), _jws()
    assert credential_counts(f"{a} {b}").get(DETECTOR_JWT) == 2
    assert credential_counts(f"abc{a}").get(DETECTOR_JWT) == 1


def test_dashed_junk_without_a_token_matches_nothing() -> None:
    assert scan_text("eyJaaaaaaaa-" * 200, trust_vendor_marker=True) == []


@pytest.mark.parametrize("joiner", ["-", "_"])
def test_jws_whose_payload_holds_a_joiner_and_header_start_is_still_fully_redacted(joiner: str) -> None:
    payload, sig = f"eyJ{_seg(40)}", _seg(43)
    payload = payload[:20] + f"{joiner}eyJ{_seg(9)}" + payload[20:]
    token = f"eyJ{_seg(30)}.{payload}.{sig}"
    text = f"x {token} y"
    out = redact_whole(text)
    assert _visible(token, out) == []
    assert credential_counts(text).get(DETECTOR_JWT) == 1


def test_chains_still_split_when_the_fallback_exists() -> None:
    tokens = [_jws(), _jws(), _jws()]
    assert credential_counts("-".join(tokens)).get(DETECTOR_JWT) == 3


def test_joiner_flood_stays_linear() -> None:
    def cost(n: int) -> float:
        text = "eyJaaaaaaaa_" * n
        best = float("inf")
        for _ in range(2):
            start = time.perf_counter()
            scan_text(text, (DETECTOR_JWT,), trust_vendor_marker=True)
            best = min(best, time.perf_counter() - start)
        return best
    assert cost(40000) / cost(10000) < 10
