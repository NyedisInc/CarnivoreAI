from __future__ import annotations

import asyncio
import time

import pytest

from tests.test_relay_identity import FakeControl, Issuer, _session


@pytest.mark.asyncio
async def test_concurrent_token_callers_post_one_token_request(tmp_path) -> None:
    class SlowControl(FakeControl):
        async def __call__(self, base, method, path, *, json_body=None, bearer=None):
            if path == "/token":
                await asyncio.sleep(0.05)
            return await super().__call__(base, method, path, json_body=json_body, bearer=bearer)

    control = SlowControl(Issuer())
    session = _session(tmp_path, control, clock=time.time)
    tokens = await asyncio.gather(*(session.token() for _ in range(5)))
    assert [c[0] for c in control.calls].count("/token") == 1
    assert all(t is tokens[0] for t in tokens)
