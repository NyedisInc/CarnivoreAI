
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_pt_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_pt_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.skills.plan_tokens import MAX_OUTSTANDING_TOKENS, StagedPlanStore

CLAIMANTS = MAX_OUTSTANDING_TOKENS + 4


class StillClock:

    def now(self) -> float:
        return 1_700_000_000.0

    def monotonic(self) -> float:
        return 1000.0


def _one_plan(store: StagedPlanStore, name: str = "acme/sme"):
    plan, dropped = store.put(
        staging=Path("/nonexistent/staging") / name.replace("/", "-"),
        staged=object(),
        item_id=name,
        version="1.0.0",
        scope="global",
        project_path=None,
    )
    assert dropped == [] or all(entry.token != plan.token for entry in dropped)
    return plan


@pytest.mark.asyncio
async def test_only_one_of_many_concurrent_claims_gets_the_staged_copy():
    store = StagedPlanStore(clock=StillClock())
    plan = _one_plan(store)

    async def claim():
        claimed, _expired = store.take(plan.token)
        return claimed

    results = await asyncio.gather(*(claim() for _ in range(CLAIMANTS)))

    winners = [entry for entry in results if entry is not None]
    assert len(winners) == 1, f"{len(winners)} callers were handed one copy"
    assert winners[0].token == plan.token
    assert store.outstanding() == 0


def test_a_claimed_token_is_gone_for_good():
    store = StagedPlanStore(clock=StillClock())
    plan = _one_plan(store)

    first, _ = store.take(plan.token)
    second, _ = store.take(plan.token)

    assert first is not None
    assert second is None
    assert store.outstanding() == 0


def test_over_the_cap_the_oldest_is_evicted_and_handed_back():
    store = StagedPlanStore(clock=StillClock())
    plans = [_one_plan(store, f"acme/skill-{index}") for index in range(20)]

    assert store.outstanding() == MAX_OUTSTANDING_TOKENS
    survivors = {entry.token for entry in plans[-MAX_OUTSTANDING_TOKENS:]}
    claimed = {
        entry.token
        for entry in plans
        if store.take(entry.token)[0] is not None
    }
    assert claimed == survivors
