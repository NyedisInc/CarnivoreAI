
from __future__ import annotations

import pytest

from src.config.settings import Settings
from src.core.computers import runtime
from src.core.federation.peer_links import PeerLinks
from tests.python.computers.test_computers_runtime import _runtime
from tests.python.computers.test_join_commit import _main_prov, world  # noqa: F401


def test_default_host_is_still_every_interface_while_the_loopback_default_is_deferred() -> None:
    assert Settings.model_fields["host"].default == "0.0.0.0"


def test_link_and_join_ports_follow_the_main_bind() -> None:
    assert runtime.bind_host("127.0.0.1") == "127.0.0.1"
    assert runtime.bind_host("0.0.0.0") == "0.0.0.0"
    assert runtime.bind_host("192.168.1.20") == "192.168.1.20"


@pytest.mark.asyncio
async def test_a_loopback_bind_turns_tls_joins_off(world, monkeypatch) -> None:
    main, join = world
    await _main_prov(main, join, "new")
    states = {}
    for host in ("127.0.0.1", "0.0.0.0"):
        rt = _runtime(main, monkeypatch, host=host)
        await rt.prepare(PeerLinks(open_db=main.open_db, listener_path=rt._listener_path))
        await rt.start()
        try:
            states[host] = (rt.loopback_bind, rt.link_state, rt.advertised_port())
        finally:
            await rt.stop()
    assert states["127.0.0.1"] == (True, "off_loopback", None)
    assert states["0.0.0.0"][:2] == (False, "dialing") and states["0.0.0.0"][2] is not None
