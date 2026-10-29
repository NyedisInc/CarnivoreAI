
from __future__ import annotations

import asyncio
import socket
from typing import Any, Dict, List

from src.cplugs.publicboard.service import PublicBoardService
from src.cplugs.sdk.public_listener import ListenerSpec, PublicListener
from tests.python.cplugs.publicboard.harness import HOST, LOOPBACK, edge_for

SETTLE = 0.4


def port_open(port: int) -> bool:
    try:
        socket.create_connection((LOOPBACK, port), timeout=1).close()
    except OSError:
        return False
    return True


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind((LOOPBACK, 0))
        return int(probe.getsockname()[1])


class BindSpy:

    def __init__(self) -> None:
        self.ports: List[int] = []
        self.bound = asyncio.Event()
        self.original = PublicListener._bind

    def install(self) -> None:
        spy = self

        def bind(listener: PublicListener) -> socket.socket:
            sock = spy.original(listener)
            spy.ports.append(sock.getsockname()[1])
            spy.bound.set()
            return sock

        PublicListener._bind = bind  # type: ignore[method-assign]

    def remove(self) -> None:
        PublicListener._bind = self.original  # type: ignore[method-assign]


def test_cancelling_start_mid_wait_leaves_the_port_closed() -> None:
    async def scenario() -> None:
        spy = BindSpy()
        spy.install()
        try:
            listener = PublicListener(edge_for(), ListenerSpec(host=LOOPBACK, port=0))
            task = asyncio.ensure_future(listener.start())
            await spy.bound.wait()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await asyncio.sleep(SETTLE)
            assert not await asyncio.to_thread(port_open, spy.ports[0]), "an orphaned server task still holds the port"
        finally:
            spy.remove()

    asyncio.run(scenario())


def settings(port: int) -> Dict[str, Any]:
    return {"port": port, "bindAddress": LOOPBACK, "hostnames": HOST, "trustedProxies": "203.0.113.11"}


def test_stop_during_start_before_the_bind_leaves_the_port_closed() -> None:
    async def scenario() -> None:
        service, port = PublicBoardService(), free_port()
        gate, entered = asyncio.Event(), asyncio.Event()
        real_start = PublicListener.start

        async def slow_start(listener: PublicListener, *a: Any, **k: Any) -> None:
            entered.set()
            await gate.wait()
            await real_start(listener, *a, **k)

        PublicListener.start = slow_start  # type: ignore[method-assign]
        try:
            applying = asyncio.ensure_future(service.apply(settings(port)))
            await entered.wait()
            stopping = asyncio.ensure_future(service.stop())
            await asyncio.sleep(0)
            gate.set()
            await asyncio.gather(applying, stopping)
            await asyncio.sleep(SETTLE)
            assert not await asyncio.to_thread(port_open, port), "stop during start left the port open"
            assert service.listener is None
        finally:
            PublicListener.start = real_start  # type: ignore[method-assign]

    asyncio.run(scenario())


def test_stop_during_start_after_the_bind_leaves_the_port_closed() -> None:
    async def scenario() -> None:
        spy = BindSpy()
        spy.install()
        try:
            service = PublicBoardService()
            applying = asyncio.ensure_future(service.apply(settings(free_port())))
            await spy.bound.wait()
            stopping = asyncio.ensure_future(service.stop())
            await asyncio.gather(applying, stopping)
            await asyncio.sleep(SETTLE)
            assert not await asyncio.to_thread(port_open, spy.ports[0]), "stop during start left the port open"
            assert service.listener is None
        finally:
            spy.remove()

    asyncio.run(scenario())


def test_two_applies_in_a_row_leave_exactly_the_last_one() -> None:
    async def scenario() -> None:
        service, first, second = PublicBoardService(), free_port(), free_port()
        await asyncio.gather(service.apply(settings(first)), service.apply(settings(second)))
        await asyncio.sleep(SETTLE)
        assert [await asyncio.to_thread(port_open, p) for p in (first, second)].count(True) == 1
        await service.stop()
        await asyncio.sleep(SETTLE)
        assert not await asyncio.to_thread(port_open, first) and not await asyncio.to_thread(port_open, second)

    asyncio.run(scenario())
