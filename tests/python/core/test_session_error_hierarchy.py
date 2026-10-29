from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.core.session_manager import SessionManager


class _CrashingBackend:

    tmux_session = None

    async def start(self, **_kw: object) -> None:
        raise KeyError("missing-env-key")

    async def stop(self) -> None:
        return None


def _manager() -> SessionManager:
    with patch.object(SessionManager, "_load_session_metadata", return_value=None):
        return SessionManager()


@pytest.mark.asyncio
async def test_backend_bug_is_not_rewrapped_as_value_error(tmp_path) -> None:
    manager = _manager()
    with patch("src.core.session_manager.build_backend", return_value=_CrashingBackend()):
        with pytest.raises(KeyError):
            await manager.create_session(session_id="ses_x", working_dir=str(tmp_path), auto_start_claude=False)


def _create_answer(error: BaseException, tmp_path) -> int:
    import asyncio

    from fastapi import HTTPException

    from src.api.session_crud_routes import create_session_with_extra
    from src.models import CreateSessionRequest

    async def boom(**_kw: object) -> None:
        raise error

    manager = SimpleNamespace(create_session=boom)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_manager=manager)))
    body = CreateSessionRequest(working_dir=str(tmp_path))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(create_session_with_extra(request, body))
    return caught.value.status_code


def test_create_route_maps_each_error_to_its_own_status(tmp_path) -> None:
    from src.core.sessions.errors import SessionCreateFailed, TmuxError

    assert _create_answer(TmuxError("tmux new-session failed"), tmp_path) == 502
    assert _create_answer(SessionCreateFailed("Failed to create session: x"), tmp_path) == 502
    assert _create_answer(ValueError("bad folder"), tmp_path) == 400
    assert _create_answer(KeyError("k"), tmp_path) == 500
    assert _create_answer(RuntimeError("dictionary changed size during iteration"), tmp_path) == 500


def test_hierarchy_roots() -> None:
    from src.core import session_store
    from src.core.bookmarks.errors import SessionNotFound as BookmarkSessionNotFound
    from src.core.inventory.model import SessionNotFound as InventorySessionNotFound
    from src.core.open_files.session_folder import SessionNotFound as FolderSessionNotFound
    from src.core.session_move.apply import SessionNotFound as MoveSessionNotFound
    from src.core.sessions.errors import SessionError, SessionNotFound, TmuxError
    from src.core.tmux_backend import PaneDeadError

    assert issubclass(PaneDeadError, TmuxError) and issubclass(TmuxError, RuntimeError)
    assert issubclass(SessionNotFound, (SessionError, LookupError))
    for cls in (session_store.SessionNotFoundError, BookmarkSessionNotFound, InventorySessionNotFound,
                FolderSessionNotFound, MoveSessionNotFound):
        assert issubclass(cls, SessionNotFound)


def test_tmux_driver_does_not_import_the_session_domain() -> None:
    from pathlib import Path

    import src.core.tmux_backend as tb
    from src.core.tmux_control import tmux_error as tmux_errors

    assert "from src.core.sessions.errors import" not in Path(tb.__file__).read_text()
    from src.core.sessions.errors import TmuxError

    assert TmuxError is tmux_errors.TmuxError


def test_caller_misuse_states_are_not_tmux_failures() -> None:
    import asyncio

    from src.core.tmux_backend import TmuxBackend
    from src.core.tmux_control.tmux_error import TmuxError

    backend = TmuxBackend.__new__(TmuxBackend)
    backend._running = False
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(backend.write(b"x"))
    assert not isinstance(caught.value, TmuxError)
