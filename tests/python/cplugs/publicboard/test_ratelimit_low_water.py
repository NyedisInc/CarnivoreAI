
from __future__ import annotations

from src.cplugs.publicboard import ratelimit

LOW_WATER = ratelimit.MAX_KEYS * 3 // 4


def _flooded() -> ratelimit.RateLimiter:
    limiter = ratelimit.RateLimiter(1, clock=lambda: 0.0)
    for number in range(ratelimit.MAX_KEYS + 1):
        limiter.allow(f"k{number}")
    return limiter


def test_a_flood_leaves_the_table_at_three_quarters_of_the_cap() -> None:
    assert len(_flooded()._hits) == LOW_WATER


def test_the_newest_keys_keep_their_windows_and_the_oldest_start_fresh() -> None:
    limiter = _flooded()
    assert limiter.allow(f"k{ratelimit.MAX_KEYS}") is False, "the newest key's spent window survived the trim"
    assert limiter.allow("k0") is True, "the oldest key was evicted and starts a fresh window"


def test_headroom_after_a_trim_absorbs_new_keys_without_shrinking_again() -> None:
    limiter = _flooded()
    for number in range(ratelimit.MAX_KEYS - LOW_WATER):
        limiter.allow(f"flood{number}")
    assert len(limiter._hits) == ratelimit.MAX_KEYS
    assert f"k{ratelimit.MAX_KEYS}" in limiter._hits
