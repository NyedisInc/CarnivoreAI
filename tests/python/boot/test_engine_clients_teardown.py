
from __future__ import annotations

import asyncio

import pytest
from structlog.testing import capture_logs

from src.core.boot import schedulers
from src.core.boot.context import BootContext
from src.core.boot.steps import BootRegistry, BootRunner


def test_a_raising_control_input_shutdown_does_not_skip_the_readers_or_the_catalog_client(
        monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.catalog import client as catalog_client
    from src.core.tmux_control import client as control_client
    from src.core.tmux_control import reader as control_reader

    calls: list[str] = []

    async def failing_shutdown() -> None:
        raise RuntimeError("control input said no")

    async def recording_catalog_shutdown() -> None:
        calls.append("catalog_client")

    monkeypatch.setattr(control_client, "shutdown_all", failing_shutdown)
    monkeypatch.setattr(control_reader, "close_readers", lambda: calls.append("tmux_control_readers"))
    monkeypatch.setattr(catalog_client, "shutdown", recording_catalog_shutdown)
    step = next(s for s in schedulers.steps() if s.name == "engine_clients")
    runner = BootRunner(BootRegistry([step]))
    ctx = BootContext(app=None)  # type: ignore[arg-type]

    async def go() -> None:
        await runner.start_all(ctx)
        await runner.stop_all(ctx)

    with capture_logs() as logs:
        asyncio.run(go())
    assert calls == ["tmux_control_readers", "catalog_client"]
    failed = [(e["step"], e["error_type"]) for e in logs if e["event"] == "lifespan_teardown_step_failed"]
    assert failed == [("control_input", "RuntimeError")]
