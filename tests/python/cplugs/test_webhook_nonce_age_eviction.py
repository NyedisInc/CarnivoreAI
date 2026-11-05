
from __future__ import annotations

import pytest

from src.cplugs.runtime import webhooks

SECRET = b"s" * 32
NOW = 1_000_000.0


def headers_at(ts: int, nonce: str, body: bytes = b"{}") -> dict:
    return {"x-timestamp": str(ts), "x-nonce": nonce, "x-signature": webhooks.sign(SECRET, ts, nonce, body)}


def fill_cache(verifier: webhooks.InboundVerifier, ts: int) -> dict:
    first = headers_at(ts, "n0")
    for i in range(webhooks.NONCE_CACHE_SIZE):
        verifier.verify(f"hook{i // webhooks.PER_HOOK_PER_MINUTE}", SECRET, first if i == 0 else headers_at(ts, f"n{i}"), b"{}")
    return first


def refusal(verifier: webhooks.InboundVerifier, hook: str, headers: dict) -> str:
    try:
        verifier.verify(hook, SECRET, headers, b"{}")
    except webhooks.WebhookRefused as err:
        return err.code
    return "accepted"


def test_flood_of_fresh_nonces_cannot_reopen_replay_of_an_earlier_request() -> None:
    now = [NOW + 60]
    verifier = webhooks.InboundVerifier(clock=lambda: now[0], started_at=NOW)
    ts = int(now[0])
    first = fill_cache(verifier, ts)
    assert refusal(verifier, "spare", headers_at(ts, "one-more")) == "cache_full"
    now[0] += 61
    assert refusal(verifier, "hook0", first) == "replay"


def test_nonces_age_out_with_their_timestamp_and_free_the_cache() -> None:
    now = [NOW + 60]
    verifier = webhooks.InboundVerifier(clock=lambda: now[0], started_at=NOW)
    ts = int(now[0])
    first = fill_cache(verifier, ts)
    now[0] = ts + webhooks.MAX_SKEW_SECONDS + 1
    assert refusal(verifier, "hook0", headers_at(int(now[0]), "fresh")) == "accepted"
    assert refusal(verifier, "hook0", first) == "stale"
    assert len(verifier._nonces) == 1


def test_cache_is_sized_from_the_per_hook_rate_cap() -> None:
    per_hook_live = webhooks.PER_HOOK_PER_MINUTE * webhooks.NONCE_LIFETIME_MINUTES
    assert webhooks.NONCE_CACHE_SIZE >= per_hook_live
    assert webhooks.NONCE_LIFETIME_MINUTES * 60 >= webhooks.MAX_SKEW_SECONDS + webhooks.MAX_FUTURE_SECONDS


def test_clock_stepping_backward_cannot_bring_purged_nonces_back_into_the_window() -> None:
    now = [NOW + 60]
    verifier = webhooks.InboundVerifier(clock=lambda: now[0], started_at=NOW)
    captured = headers_at(int(now[0]), "cap")
    assert refusal(verifier, "a", captured) == "accepted"
    now[0] += webhooks.MAX_SKEW_SECONDS + 1
    assert refusal(verifier, "b", headers_at(int(now[0]), "other")) == "accepted"
    now[0] -= 200
    assert refusal(verifier, "a", captured) == "stale"


def test_a_busy_hook_hits_its_own_quota_without_starving_other_hooks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(webhooks, "HOOK_NONCE_QUOTA", 5)
    now = [NOW + 60]
    verifier = webhooks.InboundVerifier(clock=lambda: now[0], started_at=NOW)
    ts = int(now[0])
    for i in range(5):
        assert refusal(verifier, "busy", headers_at(ts, f"b{i}")) == "accepted"
    assert refusal(verifier, "busy", headers_at(ts, "b5")) == "cache_full"
    assert refusal(verifier, "quiet", headers_at(ts, "q0")) == "accepted"
    now[0] += webhooks.MAX_SKEW_SECONDS + 1
    assert refusal(verifier, "busy", headers_at(int(now[0]), "b6")) == "accepted"


def test_a_nonce_reused_after_its_first_use_expired_is_not_a_replay() -> None:
    now = [NOW + 60]
    verifier = webhooks.InboundVerifier(clock=lambda: now[0], started_at=NOW)
    assert refusal(verifier, "a", headers_at(int(now[0]), "n")) == "accepted"
    now[0] += webhooks.MAX_SKEW_SECONDS + 100
    assert refusal(verifier, "a", headers_at(int(now[0]), "n")) == "accepted"


def test_a_host_clock_that_ran_ahead_and_was_corrected_causes_no_outage() -> None:
    now = [NOW + 60]
    verifier = webhooks.InboundVerifier(clock=lambda: now[0], started_at=NOW)
    assert refusal(verifier, "a", headers_at(int(now[0]), "first")) == "accepted"
    now[0] += 3600
    assert refusal(verifier, "a", headers_at(int(NOW + 70), "real")) == "stale"
    now[0] = NOW + 80
    assert refusal(verifier, "a", headers_at(int(now[0]), "after")) == "accepted"


def test_host_and_one_sender_both_an_hour_off_refuse_the_replay_and_accept_new_real_requests() -> None:
    now = [NOW + 60]
    verifier = webhooks.InboundVerifier(clock=lambda: now[0], started_at=NOW)
    captured = headers_at(int(now[0]), "cap")
    assert refusal(verifier, "a", captured) == "accepted"
    now[0] += 3600
    assert refusal(verifier, "x", headers_at(int(now[0]), "far")) == "accepted"
    now[0] = NOW + 90
    assert refusal(verifier, "a", captured) == "stale"
    assert refusal(verifier, "a", headers_at(int(now[0]), "ok")) == "accepted"
