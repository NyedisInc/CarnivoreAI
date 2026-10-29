
from __future__ import annotations

import asyncio

from src.core.log_monitor import LogMonitor


class _Manager:

    def has_active_session(self) -> bool:
        raise AssertionError("the log monitor polled has_active_session")


def test_start_monitoring_creates_no_task_and_polls_nothing():
    async def scenario():
        monitor = LogMonitor(_Manager())
        before = asyncio.all_tasks()
        await monitor.start_monitoring()
        await asyncio.sleep(0)
        assert asyncio.all_tasks() == before
        assert monitor.is_monitoring is True
        await monitor.stop_monitoring()
        assert monitor.is_monitoring is False

    asyncio.run(scenario())
