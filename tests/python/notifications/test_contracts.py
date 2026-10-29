
from __future__ import annotations

import asyncio
import threading
import time

from src.core.notifications import contracts as C


def _event() -> C.NotifyEvent:
    return C.NotifyEvent(type_id="session.finished", kind="Stop", title="turn finished", ts=time.time())


def test_failure_classes_and_retryable_set_are_exact() -> None:
    assert {f.value for f in C.FailureClass} == {
        "timeout", "network", "server", "rate_limited", "auth", "gone", "invalid", "blocked", "keychain_locked",
        "secret_missing", "private_off", "plain_http_off", "origin_changed"}
    assert C.NOT_COUNTED == frozenset({C.FailureClass.KEYCHAIN_LOCKED, C.FailureClass.SECRET_MISSING,
                                       C.FailureClass.PRIVATE_OFF, C.FailureClass.PLAIN_HTTP_OFF,
                                       C.FailureClass.ORIGIN_CHANGED})
    assert not C.NOT_COUNTED & C.RETRYABLE
    assert C.RETRYABLE == frozenset({C.FailureClass.TIMEOUT, C.FailureClass.NETWORK, C.FailureClass.SERVER,
                                     C.FailureClass.RATE_LIMITED})
    assert C.DeliveryResult(ok=False, failure=C.FailureClass.SERVER).retryable
    assert not C.DeliveryResult(ok=False, failure=C.FailureClass.AUTH).retryable
    assert not C.DeliveryResult(ok=True).retryable


def test_emit_with_no_sink_is_a_noop_and_a_sink_receives_the_event() -> None:
    C.uninstall_sink()
    C.emit(_event())
    seen: list = []
    C.install_sink(seen.append)
    try:
        C.emit(_event())
        assert len(seen) == 1 and seen[0].type_id == "session.finished" and seen[0].origin == C.ORIGIN_LOCAL
    finally:
        C.uninstall_sink()
    C.emit(_event())
    assert len(seen) == 1


def test_emit_never_raises_and_works_from_a_thread_and_a_loop() -> None:
    def boom(event: C.NotifyEvent) -> None:
        raise RuntimeError("sink down")

    seen: list = []
    C.install_sink(boom)
    try:
        C.emit(_event())
        C.install_sink(seen.append)
        worker = threading.Thread(target=lambda: C.emit(_event()))
        worker.start()
        worker.join()

        async def on_loop() -> None:
            C.emit(_event())

        asyncio.run(on_loop())
        assert len(seen) == 2
    finally:
        C.uninstall_sink()


def test_sender_protocol_is_satisfied_by_an_async_send() -> None:
    class Fake:
        async def send(self, event, config, secrets):
            return C.DeliveryResult(ok=True)

    assert isinstance(Fake(), C.Sender)
    assert asyncio.run(Fake().send(_event(), {}, {})).ok
