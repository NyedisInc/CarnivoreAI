from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi.testclient import TestClient

from src.core import server_status
from tests.test_server_status_api import FakeSessionManager, _app


def test_collect_runs_on_a_worker_thread(monkeypatch) -> None:
    seen: Dict[str, Any] = {}

    def fake_collect(**_kwargs: Any) -> Dict[str, Any]:
        try:
            asyncio.get_running_loop()
            seen["loop_running_here"] = True
        except RuntimeError:
            seen["loop_running_here"] = False
        return {"tmux": {"server_running": False, "sessions": []}}

    monkeypatch.setattr(server_status, "collect", fake_collect)
    client = TestClient(_app(FakeSessionManager()))
    assert client.get("/api/v1/server/status").status_code == 200
    assert seen["loop_running_here"] is False
