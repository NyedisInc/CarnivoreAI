import socket

import httpx
import pytest

from src.core.byoai import transport
from src.core.byoai.contracts import (
    MAX_TIMEOUT_S, ByoaiError, ByoaiUnreachable, Connection, ProviderTimeout,
)


def _conn(port: int) -> Connection:
    return Connection(id="c1", preset="custom", label="t", base_url=f"http://127.0.0.1:{port}",
                      key_host="127.0.0.1", options={"auth": "none"})


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.asyncio
async def test_refused_port_raises_unreachable_and_stays_a_byoai_error():
    with pytest.raises(ByoaiUnreachable) as caught:
        await transport.request(_conn(_free_port()), None, "GET", "/models")
    assert isinstance(caught.value, ByoaiError)


def test_connect_timeout_is_unreachable_read_timeout_is_not():
    assert isinstance(transport._map(httpx.ConnectTimeout("x")), ByoaiUnreachable)
    assert isinstance(transport._map(httpx.ReadTimeout("x")), ProviderTimeout)


def test_per_call_timeout_is_honored_defaulted_and_capped():
    assert transport.bound_timeout(None) is transport.DEFAULT_TIMEOUT
    assert transport.bound_timeout(300).read == 300.0
    assert transport.bound_timeout(300).connect == transport.DEFAULT_TIMEOUT.connect
    assert transport.bound_timeout(99999).read == MAX_TIMEOUT_S
