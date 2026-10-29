import asyncio
import base64
import logging
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketDisconnect
from uvicorn.protocols.utils import ClientDisconnected
import structlog
from structlog.testing import capture_logs

from src.api.ws_viewer_drain import _drain_viewer
from src.core import viewer_fanout


def _run(exc):
    async def send_bytes(_data):
        raise exc

    ws = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=None)),
                         send_bytes=send_bytes)
    stream = viewer_fanout.new_viewer_stream("t")
    viewer_fanout.offer_pty(stream, base64.b64encode(b"x").decode())
    original = structlog.get_config()["wrapper_class"]
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG))
    try:
        with capture_logs() as logs:
            asyncio.run(asyncio.wait_for(_drain_viewer(ws, stream), timeout=2))
    finally:
        structlog.configure(wrapper_class=original)
    return logs


@pytest.mark.parametrize("exc", [
    WebSocketDisconnect(1001),
    ClientDisconnected(),
    RuntimeError('Cannot call "send" once a close message has been sent.'),
])
def test_client_gone_is_debug(exc):
    logs = _run(exc)
    assert [l["log_level"] for l in logs] == ["debug"]
    assert logs[0]["event"] == "drain_viewer_client_gone"


def test_other_failure_stays_error():
    logs = _run(ValueError("boom"))
    assert [(l["event"], l["log_level"]) for l in logs] == [("drain_viewer_error", "error")]
