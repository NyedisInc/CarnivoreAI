
from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import codex_helpers_listing, codex_helpers_routes  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.core.codex_helpers import constants as K  # noqa: E402
from src.core.codex_helpers import runtime  # noqa: E402
from src.core.codex_helpers.check import HelperCheck  # noqa: E402
from src.core.codex_helpers.handshake import HandshakeResult  # noqa: E402
from src.core.codex_helpers.quarantine import HelperFlag  # noqa: E402
from src.core.mcp import tools  # noqa: E402
from src.models import AgentUpdateInfo, Session, SessionInfo  # noqa: E402

BLOCKED_TEXT = "macos blocked codex 0.170 helpers: approve them in system settings > privacy & security"


def _blocked(identity=("/x/codex/0.170.0/bin/codex", 1, 1), version="0.170.0") -> HelperCheck:
    return HelperCheck(identity=identity, binary=identity[0], version=version, verdict=K.BLOCKED,
                       helpers=[HelperFlag(K.HOST_NAME, "/x/" + K.HOST_NAME, "0381", False)],
                       handshake=HandshakeResult(K.HS_TIMEOUT, 5000), checked_at=datetime.now(timezone.utc))


@pytest.fixture()
def armed():
    check = _blocked()
    runtime.install(lambda: None, lambda _b: None, checker=lambda i, v: check)
    runtime._store(check)  # noqa: SLF001
    yield check
    runtime.uninstall()


def _row(family, running=None) -> SessionInfo:
    info = SessionInfo(session=Session(id=f"ses_{family}", working_dir="/tmp"))
    info.agent_family = family
    if running:
        info.agent_update = AgentUpdateInfo(running=running, installed="0.170.0", ready=True)
    return info


def test_codex_rows_carry_the_readable_reason_and_others_stay_null(armed):
    codex, claude, older = _row("codex"), _row("claude"), _row("codex", running="0.166.0")
    codex_helpers_listing.mark_codex_helpers([codex, claude, older])
    assert codex.codex_helpers.verdict == K.BLOCKED and codex.codex_helpers.text == BLOCKED_TEXT
    assert claude.codex_helpers is None
    assert older.codex_helpers is None


def test_an_unchecked_codex_row_is_null():
    runtime.uninstall()
    row = _row("codex")
    codex_helpers_listing.mark_codex_helpers([row])
    assert row.codex_helpers is None


def test_the_route_answers_the_status(armed):
    app = FastAPI()
    app.include_router(codex_helpers_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    body = TestClient(app).get("/api/v1/agents/codex/helpers").json()
    assert body["armed"] is True
    assert body["check"]["verdict"] == K.BLOCKED and body["check"]["text"] == BLOCKED_TEXT
    assert body["check"]["unapproved"] == [K.HOST_NAME]


def test_the_route_requires_auth():
    app = FastAPI()
    app.include_router(codex_helpers_routes.router, prefix="/api/v1")
    assert TestClient(app).get("/api/v1/agents/codex/helpers").status_code in (401, 403)


def test_the_mcp_tools_are_registered_with_their_scopes():
    names = set(tools.tool_names())
    assert {"codex_helpers_status", "codex_helpers_check"} <= names
    assert "codex_helpers_check" in tools.WRITE_TOOLS and "codex_helpers_status" not in tools.WRITE_TOOLS
