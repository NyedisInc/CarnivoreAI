
from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from typing import Iterator, Tuple

import pytest
import uvicorn
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from relay.__main__ import server_options
from relay.app import create_app
from relay.config import MAX_FRAME_BYTES
from relay.protocol import PUBLISH_SUBPROTOCOL
from tests.relay_support import RecordingFactory, data_frame, links_frame
from tests.test_relay_sockets import PUBLISH_TOKEN, build_settings

MESSAGE_TOO_BIG = 1009


@contextmanager
def real_relay() -> Iterator[Tuple[int, RecordingFactory]]:
    factory = RecordingFactory()
    settings = replace(build_settings(), port=0)
    config = uvicorn.Config(
        create_app(settings, redactor_factory=factory), **server_options(settings)
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10.0
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise AssertionError("uvicorn never started")
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield port, factory
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)


def data_frame_of_size(total: int) -> str:
    empty = json.dumps(data_frame("l1", ""))
    frame = json.dumps(data_frame("l1", "x" * (total - len(empty))))
    assert len(frame.encode("utf-8")) == total
    return frame


def test_the_deployed_server_options_carry_a_128_kib_frame_limit():
    assert MAX_FRAME_BYTES == 128 * 1024
    assert server_options(build_settings())["ws_max_size"] == MAX_FRAME_BYTES


def test_an_oversize_frame_closes_the_publisher_and_is_never_fed():
    with real_relay() as (port, factory):
        with connect(
            f"ws://127.0.0.1:{port}/publish",
            additional_headers={"Authorization": f"Bearer {PUBLISH_TOKEN}"},
            subprotocols=[PUBLISH_SUBPROTOCOL],
            max_size=None,
        ) as pub:
            pub.send(json.dumps(links_frame({"l1": "share"})))
            at_limit = data_frame_of_size(MAX_FRAME_BYTES)
            pub.send(at_limit)
            deadline = time.monotonic() + 5.0
            while not (factory.made and factory.made[0].fed):
                if time.monotonic() > deadline:
                    raise AssertionError("a frame at the limit was never fed")
                time.sleep(0.02)
            pub.send(data_frame_of_size(MAX_FRAME_BYTES + 1))
            with pytest.raises(ConnectionClosed) as closed:
                pub.recv(timeout=5.0)
    assert closed.value.rcvd is not None
    assert closed.value.rcvd.code == MESSAGE_TOO_BIG
    (redactor,) = factory.made
    assert redactor.fed == [json.loads(at_limit)["payload"]]
