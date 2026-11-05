
from __future__ import annotations

import asyncio

import pytest

from src.core.notifications.presence import PresenceLeases
from tests.python.notifications.engine_fakes import dest, ev
from tests.python.notifications.test_engine import Rig, _clean, _no_alert  # noqa: F401

pytestmark = pytest.mark.asyncio


async def test_watched_session_push_is_held_then_sent_only_if_needs_you_still_open():
    r = Rig([dest()], manual=True)
    leases = PresenceLeases(clock=r.clock)
    r.engine._screens = leases
    assert leases.beacon("c_watch_1", True, "ses_watched")
    await r.engine.handle(ev("session.finished", session_id="ses_other", instance_key="o1"))
    await r.engine.join()
    assert len(r.sender.calls) == 1
    await r.engine.handle(ev("session.finished", session_id="ses_watched", instance_key="w0"))
    await r.engine.join()
    assert len(r.sender.calls) == 1
    await r.engine.handle(ev("session.question", session_id="ses_watched", instance_key="w1"))
    await asyncio.sleep(0)
    assert len(r.sender.calls) == 1 and r.sleep.waiting[0][0] == 120.0
    await r.sleep.release()
    await r.engine.join()
    assert len(r.sender.calls) == 2 and r.sender.calls[1][0].session_id == "ses_watched"
    leases.beacon("c_watch_1", True, "")
    assert not leases.is_watched("ses_watched")
