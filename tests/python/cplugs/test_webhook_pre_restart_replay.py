
from __future__ import annotations

import pytest

from src.cplugs.runtime import webhooks

SECRET = b"s" * 32
RESTART = 1_000_000.0


def headers_at(ts: int, nonce: str, body: bytes = b"{}") -> dict:
    return {"x-timestamp": str(ts), "x-nonce": nonce, "x-signature": webhooks.sign(SECRET, ts, nonce, body)}


def test_request_signed_before_construction_is_refused_inside_skew_window() -> None:
    now = [RESTART]
    verifier = webhooks.InboundVerifier(clock=lambda: now[0])
    captured = headers_at(int(RESTART) - 60, "captured")
    now[0] = RESTART + 10
    with pytest.raises(webhooks.WebhookRefused) as err:
        verifier.verify("h", SECRET, captured, b"{}")
    assert err.value.code == "before_start"


def test_future_dated_request_cannot_replay_across_a_restart() -> None:
    now = [RESTART]
    before = webhooks.InboundVerifier(clock=lambda: now[0])
    captured = headers_at(int(RESTART) + 120, "fut")
    with pytest.raises(webhooks.WebhookRefused) as err:
        before.verify("h", SECRET, captured, b"{}")
    assert err.value.code == "stale"
    now[0] = RESTART + 100
    after = webhooks.InboundVerifier(clock=lambda: now[0])
    with pytest.raises(webhooks.WebhookRefused) as err2:
        after.verify("h", SECRET, captured, b"{}")
    assert err2.value.code == "before_start"


def test_sender_20s_ahead_cannot_replay_across_a_restart() -> None:
    now = [RESTART]
    before = webhooks.InboundVerifier(clock=lambda: now[0], started_at=RESTART - 100)
    captured = headers_at(int(RESTART) + 20, "ahead")
    assert before.verify("h", SECRET, captured, b"{}") == b"{}"
    now[0] = RESTART + 10
    after = webhooks.InboundVerifier(clock=lambda: now[0])
    now[0] = RESTART + 15
    with pytest.raises(webhooks.WebhookRefused) as err:
        after.verify("h", SECRET, captured, b"{}")
    assert err.value.code == "before_start"


def test_started_at_keyword_sets_the_floor() -> None:
    verifier = webhooks.InboundVerifier(clock=lambda: RESTART + 50, started_at=RESTART + 40)
    with pytest.raises(webhooks.WebhookRefused) as err:
        verifier.verify("h", SECRET, headers_at(int(RESTART) + 30, "early"), b"{}")
    assert err.value.code == "before_start"
    assert verifier.verify("h", SECRET, headers_at(int(RESTART) + 75, "ok"), b"{}") == b"{}"


def test_fresh_request_after_construction_still_verifies() -> None:
    now = [RESTART]
    verifier = webhooks.InboundVerifier(clock=lambda: now[0])
    now[0] = RESTART + 40
    assert verifier.verify("h", SECRET, headers_at(int(RESTART) + 35, "fresh"), b"{}") == b"{}"
    now[0] = RESTART + webhooks.MAX_SKEW_SECONDS + 100
    with pytest.raises(webhooks.WebhookRefused) as err:
        verifier.verify("h", SECRET, headers_at(int(RESTART) + 1, "late"), b"{}")
    assert err.value.code == "stale"
