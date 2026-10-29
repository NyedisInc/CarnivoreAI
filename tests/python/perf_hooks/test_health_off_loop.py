
from __future__ import annotations

import asyncio
import os
import tempfile
from types import SimpleNamespace

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_health_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_health_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.api.health_routes import health_endpoint  # noqa: E402


class _Manager:

    def health_summary(self):
        return "proj", 42

    def has_active_session(self) -> bool:
        raise AssertionError("health forked tmux")

    async def get_session_info(self):
        raise AssertionError("health built a SessionInfo")


def test_health_answers_from_the_summary_alone():
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_manager=_Manager())))
    response = asyncio.run(health_endpoint(request))
    assert response.session_name == "proj" and response.uptime == 42
