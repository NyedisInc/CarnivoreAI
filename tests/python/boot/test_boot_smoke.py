
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_boot_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_boot_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from fastapi.testclient import TestClient  # noqa: E402
from structlog.testing import capture_logs  # noqa: E402

from src.main import app  # noqa: E402

_STATE_NAMES = ("sidecar_runtime", "card_art_backfill", "services", "session_manager", "event_hub", "ui_preferences_store")


def test_the_app_boots_and_shuts_down_through_the_registry() -> None:
    with capture_logs() as logs:
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
            missing = [name for name in _STATE_NAMES if not hasattr(app.state, name)]
            assert missing == []
    events = [entry["event"] for entry in logs]
    assert "application_ready" in events or "server_ready_local_only" in events
    assert events.index("application_shutting_down") < events.index("application_shutdown_complete")
    assert not [entry for entry in logs if entry["event"] == "lifespan_teardown_step_failed"]
