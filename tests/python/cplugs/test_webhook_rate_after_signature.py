
from __future__ import annotations

import pytest

from src.cplugs.runtime import webhooks

SECRET = b"s" * 32
NOW = 1_000_000.0


def signed(nonce: str, body: bytes = b"{}") -> dict:
    return {"x-timestamp": str(int(NOW)), "x-nonce": nonce, "x-signature": webhooks.sign(SECRET, int(NOW), nonce, body)}


def test_unsigned_flood_does_not_lock_out_the_real_sender() -> None:
    verifier = webhooks.InboundVerifier(clock=lambda: NOW, started_at=NOW - 1000)
    for i in range(webhooks.PER_HOOK_PER_MINUTE * 3):
        junk = {"x-timestamp": str(int(NOW)), "x-nonce": f"j{i}", "x-signature": "00" * 32}
        with pytest.raises(webhooks.WebhookRefused) as err:
            verifier.verify("h", SECRET, junk, b"{}")
        assert err.value.code == "bad_signature"
    assert verifier.verify("h", SECRET, signed("real"), b"{}") == b"{}"


def test_signed_requests_still_hit_the_rate_limit() -> None:
    verifier = webhooks.InboundVerifier(clock=lambda: NOW, started_at=NOW - 1000)
    for i in range(webhooks.PER_HOOK_PER_MINUTE):
        verifier.verify("h", SECRET, signed(f"n{i}"), b"{}")
    with pytest.raises(webhooks.WebhookRefused) as err:
        verifier.verify("h", SECRET, signed("over"), b"{}")
    assert err.value.code == "rate_limited"


def test_replayed_request_does_not_lock_out_the_real_sender() -> None:
    verifier = webhooks.InboundVerifier(clock=lambda: NOW, started_at=NOW - 1000)
    captured = signed("captured")
    assert verifier.verify("h", SECRET, captured, b"{}") == b"{}"
    for _ in range(webhooks.PER_HOOK_PER_MINUTE + 5):
        with pytest.raises(webhooks.WebhookRefused) as err:
            verifier.verify("h", SECRET, captured, b"{}")
        assert err.value.code == "replay"
    assert verifier.verify("h", SECRET, signed("fresh"), b"{}") == b"{}"


def test_stale_signed_request_does_not_spend_the_budget() -> None:
    verifier = webhooks.InboundVerifier(clock=lambda: NOW, started_at=NOW - 1000)
    old_ts = int(NOW) - webhooks.MAX_SKEW_SECONDS - 1
    old = {"x-timestamp": str(old_ts), "x-nonce": "old", "x-signature": webhooks.sign(SECRET, old_ts, "old", b"{}")}
    for _ in range(webhooks.PER_HOOK_PER_MINUTE + 5):
        with pytest.raises(webhooks.WebhookRefused) as err:
            verifier.verify("h", SECRET, old, b"{}")
        assert err.value.code == "stale"
    assert verifier.verify("h", SECRET, signed("fresh"), b"{}") == b"{}"
