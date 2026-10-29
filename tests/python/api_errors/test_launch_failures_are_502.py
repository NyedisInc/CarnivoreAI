
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.hosts.remote_transport import RemoteTransport
from src.core.sessions.errors import TmuxError
from src.core.tmux_discovery import TmuxVersionSkewError

from .conftest import LEAK
from .test_session_routes_codes import _Boom, _assert_fixed


class _DownHost:

    host_key = "far"
    socket = "far"
    tmux_path = "/t"
    is_up = False
    pipe_dir = "/far/pipes"


class _NoFileHost(_DownHost):

    is_up = True

    async def exec(self, **_kwargs):
        return SimpleNamespace(returncode=1)


def _host_not_connected() -> Exception:
    try:
        RemoteTransport(_DownHost()).preflight("far", Path("/tmp"))
    except Exception as exc:  # noqa: BLE001
        return exc
    raise AssertionError("preflight did not refuse a down host")


def _file_not_created() -> Exception:
    try:
        asyncio.run(RemoteTransport(_NoFileHost()).ensure_pipe_file(Path("/tmp/x/mirror"), "/far/pipes/x", truncate=True))
    except Exception as exc:  # noqa: BLE001
        return exc
    raise AssertionError("ensure_pipe_file did not fail")


def test_each_launch_failure_is_a_tmux_error() -> None:
    assert isinstance(TmuxVersionSkewError("s", "tmux 3.6", None, None, ()), TmuxError)
    assert isinstance(_host_not_connected(), TmuxError)
    assert isinstance(_file_not_created(), TmuxError)


@pytest.mark.parametrize("make", [
    lambda: TmuxVersionSkewError("s", "tmux 3.6", LEAK, "tmux 3.7", ()),
    _host_not_connected,
    _file_not_created,
])
def test_create_session_answers_502_for_each(driver, make) -> None:
    exc = make()
    response, _events = driver.call("POST", "/sessions", _Boom(exc), json={})
    assert response.status_code == 502, response.text
    assert response.json()["detail"]["code"] == "session_launch_failed"
