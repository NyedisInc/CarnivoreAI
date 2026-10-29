
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
from src.core.federation import peer_dial
from src.core.hosts.ssh_exec import CONTROL_PATH_MAX, SshArgumentError, SshDestination


LONG_HOME = Path("/tmp/" + "x" * 90 + "/.carnivore/cm")


def test_a_long_home_falls_back_to_a_short_directory():
    directory = peer_dial.socket_dir_for(LONG_HOME)
    assert directory != LONG_HOME
    for path in peer_dial.link_socket_paths(directory, "peer-" + "a" * 20, "dc491ea8"):
        assert len(path) <= CONTROL_PATH_MAX


def test_a_short_home_keeps_its_directory():
    preferred = Path("/Users/a/.carnivore/cm")
    assert peer_dial.socket_dir_for(preferred) == preferred


def test_a_name_that_cannot_fit_is_a_named_error_not_a_bind_failure():
    with pytest.raises(SshArgumentError):
        peer_dial.link_socket_paths(LONG_HOME, "peer-x", "dc491ea8")


def test_the_transport_builds_under_a_long_home(monkeypatch):
    short = Path(tempfile.mkdtemp(prefix="sd"))
    monkeypatch.setattr(peer_dial, "socket_dir_for", lambda preferred: short)
    transport = peer_dial.InitiatorTransport(
        host_key="peer-" + "b" * 20, dest=SshDestination("hosta"), remote_port=8000, listener_path="/x/l.sock",
        make_client=lambda r: None, control_dir=LONG_HOME, instance_tag="dc491ea8")
    assert transport.master.control_path.startswith(str(short))
    assert len(transport.out_path) <= CONTROL_PATH_MAX


@pytest.mark.asyncio
async def test_pair_answers_400_when_no_socket_path_fits(monkeypatch):
    from fastapi import HTTPException
    from src.api import federation_peer_routes as routes
    from src.core.federation import peer_links

    class Links:
        _listener = "/x/l.sock"

        async def _signer(self):
            return object()

    class Req:
        class app:
            class state:
                federation_discovery = None

    async def pinned(_dest):
        return True

    def refuse(*_a, **_k):
        raise SshArgumentError("control path too long")

    monkeypatch.setattr(peer_links, "LINKS", Links())
    monkeypatch.setattr(routes.pair_driver, "host_key_pinned", pinned)
    monkeypatch.setattr(routes, "InitiatorTransport", refuse)
    monkeypatch.setattr(routes.peer_auth, "open_db", lambda: sqlite3.connect(":memory:"))
    monkeypatch.setattr(routes.peer_auth, "read_install_id", lambda _c: "iid")
    with pytest.raises(HTTPException) as caught:
        await routes.pair(routes.PairRequest(ssh_target="hosta"), Req())
    assert caught.value.status_code == 400 and caught.value.detail["code"] == "link_socket_unusable"
