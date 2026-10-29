
from __future__ import annotations

import asyncio
import hashlib

import pytest

from src.core.catalog import pow_client

CHALLENGE = "v1.email_start.9999999999.8.salt.mac"


def _bits(solution: str) -> int:
    value = int.from_bytes(hashlib.sha256(solution.encode()).digest(), "big")
    return 256 - value.bit_length()


def test_a_solution_has_the_required_leading_zero_bits():
    solution = pow_client.solve(CHALLENGE, 8)
    assert solution.startswith(CHALLENGE + "~") and _bits(solution) >= 8


def test_the_async_wrapper_solves_off_the_loop():
    solution = asyncio.run(pow_client.solve_off_loop({"challenge": CHALLENGE, "bits": 6}))
    assert _bits(solution) >= 6


@pytest.mark.parametrize("challenge,bits", [
    (CHALLENGE, pow_client.MAX_BITS + 1), (CHALLENGE, 0), (5, 8), ("café", 8),
])
def test_out_of_range_or_malformed_work_is_refused(challenge, bits):
    with pytest.raises(pow_client.PowUnsolvable):
        pow_client.solve(challenge, bits)


def test_a_time_budget_stops_the_search():
    with pytest.raises(pow_client.PowUnsolvable):
        pow_client.solve(CHALLENGE, pow_client.MAX_BITS, max_seconds=0.0)


def test_a_missing_difficulty_is_refused():
    with pytest.raises(pow_client.PowUnsolvable):
        asyncio.run(pow_client.solve_off_loop({"challenge": CHALLENGE, "bits": "8"}))
