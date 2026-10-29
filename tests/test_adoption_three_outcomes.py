
from __future__ import annotations

import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")

from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_models import (  # noqa: E402
    SESSION_LIFECYCLE_STOPPED,
    SESSION_ORIGIN_CREATED,
)
from src.core.session_adopt_persist import (  # noqa: E402
    PERSIST_LISTING_UNAVAILABLE,
    PERSIST_SESSION_GONE,
    persist_adoption,
)
from src.core.session_identity import (  # noqa: E402
    ADOPT_CLAIMED,
    ADOPT_NO_DATASTORE,
    ADOPT_NO_SUCH_INSTANCE,
    ADOPT_NOT_RUNNING,
    claim_instance,
    record_instance,
)
from tests.s7_helpers import (  # noqa: E402
    TEST_SOCKET,
    listing_of,
    listing_row,
    listing_unavailable,
    migrated_connection,
    session_row,
)

EPOCH = 1786913176
NAME = "cloudes7_ext"


@pytest.fixture()
def conn(tmp_path):
    with closing(migrated_connection(tmp_path)):
        pass
    with closing(connect(db_path_for(tmp_path))) as connection:
        yield connection




def test_claiming_an_absent_instance_updates_zero_rows_and_says_so(conn):
    before = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    result = claim_instance(
        conn, socket=TEST_SOCKET, name="never-existed", epoch=999
    )
    assert result.claimed is False
    assert result.outcome == ADOPT_NO_SUCH_INSTANCE
    assert result.determined is True
    after = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    assert after == before, "a failed claim must not create a row"


def test_the_three_failure_outcomes_are_distinguishable_from_each_other(conn):
    record_instance(
        conn,
        socket=TEST_SOCKET,
        name="corpse",
        epoch=EPOCH,
        origin=SESSION_ORIGIN_CREATED,
        lifecycle=SESSION_LIFECYCLE_STOPPED,
    )
    stopped = claim_instance(
        conn, socket=TEST_SOCKET, name="corpse", epoch=EPOCH
    )
    absent = claim_instance(
        conn, socket=TEST_SOCKET, name="ghost", epoch=EPOCH
    )

    empty = sqlite3.connect(":memory:")
    empty.row_factory = sqlite3.Row
    no_datastore = claim_instance(
        empty, socket=TEST_SOCKET, name="anything", epoch=EPOCH
    )
    empty.close()

    assert stopped.outcome == ADOPT_NOT_RUNNING
    assert absent.outcome == ADOPT_NO_SUCH_INSTANCE
    assert no_datastore.outcome == ADOPT_NO_DATASTORE
    assert len({stopped.outcome, absent.outcome, no_datastore.outcome}) == 3
    assert all(r.claimed is False for r in (stopped, absent, no_datastore))
    assert stopped.determined is True
    assert absent.determined is True
    assert no_datastore.determined is False
    assert session_row(conn, "corpse")["origin"] == SESSION_ORIGIN_CREATED


def test_a_session_that_died_between_listing_and_adopt_is_named_gone(conn):
    result = persist_adoption(
        conn,
        socket=TEST_SOCKET,
        name=NAME,
        listing=listing_of([listing_row("someone-else", 55)]),
    )
    assert result.persisted is False
    assert result.outcome == PERSIST_SESSION_GONE
    assert "no longer there" in (result.detail or "")
    assert session_row(conn, NAME) is None


def test_an_unavailable_listing_is_not_reported_as_gone(conn):
    result = persist_adoption(
        conn,
        socket=TEST_SOCKET,
        name=NAME,
        listing=listing_unavailable("timeout"),
    )
    assert result.outcome == PERSIST_LISTING_UNAVAILABLE
    assert result.outcome != PERSIST_SESSION_GONE
    assert session_row(conn, NAME) is None, "nothing may be written"


def test_the_manager_raises_the_NAMED_gone_error_not_a_bare_runtime_error():
    import asyncio

    from src.core.session_adopt_persist import (
        AdoptPersistResult,
        AdoptTargetGoneError,
    )
    from src.core.session_manager import SessionManager
    from src.core.sessions.name_locks import NameLocks
    from src.core.sessions.registry import SessionRegistry

    manager = object.__new__(SessionManager)
    manager._registry = SessionRegistry(log_cap=lambda: 1000)
    manager._adopt_locks = NameLocks()
    manager.persist_adoption = lambda _name: AdoptPersistResult(
        outcome=PERSIST_SESSION_GONE, detail="that session is no longer there"
    )

    with pytest.raises(AdoptTargetGoneError) as caught:
        asyncio.run(manager.adopt_external_session(name=NAME))
    assert "no longer there" in str(caught.value)
    assert type(caught.value) is not RuntimeError


def test_the_manager_does_not_abort_the_adoption_for_other_persist_failures():
    import asyncio

    from src.core.session_adopt_persist import (
        PERSIST_LISTING_UNAVAILABLE,
        AdoptPersistResult,
        AdoptTargetGoneError,
    )
    from src.core.session_manager import SessionManager
    from src.core.sessions.name_locks import NameLocks
    from src.core.sessions.registry import SessionRegistry

    manager = object.__new__(SessionManager)
    manager._registry = SessionRegistry(log_cap=lambda: 1000)
    manager._adopt_locks = NameLocks()
    manager.persist_adoption = lambda _name: AdoptPersistResult(
        outcome=PERSIST_LISTING_UNAVAILABLE, detail="datastore unreadable"
    )

    with pytest.raises(Exception) as caught:
        asyncio.run(manager.adopt_external_session(name=NAME))
    assert not isinstance(caught.value, AdoptTargetGoneError), (
        "a failed bookkeeping write refused the adoption. The user must "
        "still get his session; only the badge degrades"
    )


def test_the_route_answers_409_session_gone_rather_than_500():
    import asyncio

    import httpx

    from src.api.auth import require_auth
    from src.core.session_adopt_persist import AdoptTargetGoneError

    os.environ.setdefault("TOTP_SECRET", "s7secretnotreal")
    os.environ.setdefault("JWT_SECRET", "s7jwtnotreal")
    from src.main import app

    class _GoneManager:

        async def adopt_external_session(self, **_kwargs):
            raise AdoptTargetGoneError("that session is no longer there")

    previous = getattr(app.state, "session_manager", None)
    app.state.session_manager = _GoneManager()
    app.dependency_overrides[require_auth] = lambda: True

    async def _drive():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://s7.local/api/v1"
        ) as client:
            return await client.post(
                "/sessions/adopt",
                json={"session_name": NAME, "confirm_detach": False},
            )

    try:
        response = asyncio.run(_drive())
    finally:
        app.dependency_overrides.pop(require_auth, None)
        app.state.session_manager = previous

    assert response.status_code == 409, response.text
    body = response.json()["detail"]
    assert body["code"] == "session_gone"
    assert body["refresh"] is True
    assert body["session_name"] == NAME




def test_a_husk_the_probe_measures_dead_yields_409_not_500():
    import asyncio
    from pathlib import Path as _Path
    from unittest.mock import AsyncMock, MagicMock, patch

    from src.core.session_adopt_persist import AdoptTargetGoneError
    from src.core.session_manager import SessionManager
    from src.core.tmux_backend import PaneDeadError

    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        sm = SessionManager()
    sm.has_active_session = MagicMock(return_value=False)
    sm._resolve_external_cwd = AsyncMock(return_value=_Path("/tmp"))

    fake_backend = MagicMock()
    fake_backend.attach_existing = AsyncMock(
        side_effect=PaneDeadError(f"cannot adopt {NAME}: pane already dead")
    )
    fake_backend.capture_scrollback = MagicMock(return_value=b"")
    fake_backend._pipe_path = Path("/tmp/never_existent.pipe")

    with patch(
        "src.core.tmux_backend.TmuxBackend.for_external",
        return_value=fake_backend,
    ), patch("src.core.session_manager.settings") as mock_settings:
        auth_cfg = MagicMock()
        auth_cfg.session.tmux_socket_name = TEST_SOCKET
        auth_cfg.session.scrollback_lines = 3000
        mock_settings.load_auth_config.return_value = auth_cfg

        with pytest.raises(AdoptTargetGoneError) as caught:
            asyncio.run(sm.adopt_external_session(NAME, confirm_detach=False))
    assert "pane already dead" in str(caught.value)
    assert type(caught.value) is not RuntimeError


def test_a_probe_that_could_not_measure_the_pane_still_500s():
    import asyncio
    from pathlib import Path as _Path
    from unittest.mock import AsyncMock, MagicMock, patch

    from src.core.session_adopt_persist import AdoptTargetGoneError
    from src.core.session_manager import SessionManager

    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        sm = SessionManager()
    sm.has_active_session = MagicMock(return_value=False)
    sm._resolve_external_cwd = AsyncMock(return_value=_Path("/tmp"))

    fake_backend = MagicMock()
    fake_backend.attach_existing = AsyncMock(
        side_effect=RuntimeError(
            f"cannot adopt {NAME}: pane-dead probe failed: timeout"
        )
    )
    fake_backend.capture_scrollback = MagicMock(return_value=b"")
    fake_backend._pipe_path = Path("/tmp/never_existent.pipe")

    with patch(
        "src.core.tmux_backend.TmuxBackend.for_external",
        return_value=fake_backend,
    ), patch("src.core.session_manager.settings") as mock_settings:
        auth_cfg = MagicMock()
        auth_cfg.session.tmux_socket_name = TEST_SOCKET
        auth_cfg.session.scrollback_lines = 3000
        mock_settings.load_auth_config.return_value = auth_cfg

        with pytest.raises(RuntimeError) as caught:
            asyncio.run(sm.adopt_external_session(NAME, confirm_detach=False))
    assert not isinstance(caught.value, AdoptTargetGoneError), (
        "an unmeasured probe failure must never be reported as gone"
    )
