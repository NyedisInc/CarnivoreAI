
from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any, Dict

MAX_BITS = 24

MAX_SOLVE_SECONDS = 30.0


class PowUnsolvable(Exception):
    pass


def solve(challenge: str, bits: int, max_seconds: float = MAX_SOLVE_SECONDS) -> str:
    if not isinstance(challenge, str) or not challenge.isascii() or not 1 <= bits <= MAX_BITS:
        raise PowUnsolvable("the challenge is not one this app will solve")
    base = hashlib.sha256(f"{challenge}~".encode("ascii"))
    shift = 32 - bits
    deadline = time.monotonic() + max_seconds
    nonce = 0
    while True:
        digest = base.copy()
        digest.update(str(nonce).encode("ascii"))
        if int.from_bytes(digest.digest()[:4], "big") >> shift == 0:
            return f"{challenge}~{nonce}"
        nonce += 1
        if nonce % 4096 == 0 and time.monotonic() > deadline:
            raise PowUnsolvable("the proof of work took too long")


async def solve_off_loop(body: Dict[str, Any]) -> str:
    challenge, bits = body.get("challenge"), body.get("bits")
    if not isinstance(bits, int) or isinstance(bits, bool):
        raise PowUnsolvable("the challenge carries no difficulty")
    return await asyncio.to_thread(solve, challenge, bits)
