
from __future__ import annotations

import asyncio
import threading
import pytest
from structlog.testing import capture_logs

LIFESPAN_BUDGET_S = 45


@pytest.fixture()
def pristine_app_state():
    import src.main as main

    saved = dict(main.app.state._state)
    main.app.state._state.clear()
    try:
        yield
    finally:
        main.app.state._state.clear()
        main.app.state._state.update(saved)


def _boot_and_stop_with_failing_beast_stop(monkeypatch, tmp_path) -> list[str]:
    from src.config import settings

    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(settings, "auth_config_file", str(config))
    monkeypatch.setattr(settings, "_auth_config_cache", None)
    monkeypatch.setenv("CLOUDE_STATE_DIR", str(tmp_path / "state"))
    from src.core.approvals import beast_lifecycle
    from src.core.catalog import client as catalog_client

    calls: list[str] = []
    real_shutdown = catalog_client.shutdown

    def failing_beast_stop(state_dir: object) -> None:
        raise RuntimeError("beast stop blew up")

    async def recording_shutdown() -> None:
        calls.append("catalog_client")
        await real_shutdown()

    monkeypatch.setattr(beast_lifecycle, "stop", failing_beast_stop)
    monkeypatch.setattr(catalog_client, "shutdown", recording_shutdown)
    return calls


def test_early_step_raising_does_not_stop_the_teardown(monkeypatch, tmp_path, pristine_app_state) -> None:
    calls = _boot_and_stop_with_failing_beast_stop(monkeypatch, tmp_path)
    import src.main as main

    async def run() -> tuple[list[dict], BaseException | None]:
        escaped: BaseException | None = None
        with capture_logs() as logs:
            try:
                await _enter_and_leave(main)
            except Exception as exc:  # noqa: BLE001
                escaped = exc
        return logs, escaped

    outcome: list[tuple[list[dict], BaseException | None]] = []
    runner = threading.Thread(target=lambda: outcome.append(asyncio.run(run())), daemon=True)
    runner.start()
    runner.join(LIFESPAN_BUDGET_S)
    if runner.is_alive():
        pytest.exit(f"lifespan boot and teardown did not finish within {LIFESPAN_BUDGET_S}s; aborting the session", returncode=1)
    logs, escaped = outcome[0]
    failures = [e for e in logs if e["event"] == "lifespan_teardown_step_failed"]
    assert escaped is None
    assert [(e["step"], e["error_type"], e["log_level"]) for e in failures] == [("beast_lifecycle", "RuntimeError", "warning")]
    assert calls == ["catalog_client"]
    assert any(e["event"] == "application_shutdown_complete" for e in logs)


async def _enter_and_leave(main) -> None:
    async with main.lifespan(main.app):
        pass
