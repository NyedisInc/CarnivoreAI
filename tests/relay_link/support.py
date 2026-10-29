
from __future__ import annotations

import json
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Iterator, Optional, Tuple

from relay.auth import LINK_TUNNEL_POP_AUDIENCE, b64url, pop_message
from relay.phonelink import frames
from relay.phonelink.endpoint import LINK_SUBPROTOCOL
from relay.phonelink.tunnel import LinkLimits, LinkRegistry
from tests.relay_v2_support import Device, Issuer, _payload
from tests.test_relay_sockets import build_settings, relay

DOMAIN = "link.carnivore.ai"
TIMEOUT = 5.0


def host_for(device: Device) -> str:
    return f"{device.device_id}.{DOMAIN}"


def client_hello(sni: Optional[str]) -> bytes:
    ext = b""
    if sni is not None:
        name = sni.encode("ascii")
        entry = b"\x00" + len(name).to_bytes(2, "big") + name
        listing = len(entry).to_bytes(2, "big") + entry
        ext = b"\x00\x00" + len(listing).to_bytes(2, "big") + listing
    body = (b"\x03\x03" + bytes(32) + b"\x00" + b"\x00\x02\x13\x01" + b"\x01\x00"
            + len(ext).to_bytes(2, "big") + ext)
    handshake = b"\x01" + len(body).to_bytes(3, "big") + body
    return b"\x16\x03\x01" + len(handshake).to_bytes(2, "big") + handshake


def ppv2(ip: str = "203.0.113.9", port: int = 40000, *, command: int = 1) -> bytes:
    signature = b"\r\n\r\n\x00\r\nQUIT\n"
    if command == 0:
        return signature + bytes([0x20, 0x00]) + (0).to_bytes(2, "big")
    if ":" in ip:
        addr = socket.inet_pton(socket.AF_INET6, ip) + bytes(16) + port.to_bytes(2, "big") + bytes(2)
        return signature + bytes([0x21, 0x21]) + len(addr).to_bytes(2, "big") + addr
    addr = socket.inet_aton(ip) + bytes(4) + port.to_bytes(2, "big") + (443).to_bytes(2, "big")
    return signature + bytes([0x21, 0x11]) + len(addr).to_bytes(2, "big") + addr


OPEN_PHONES: list = []


class Phone:

    def __init__(self, port: int, rcvbuf: Optional[int] = None) -> None:
        self.sock = socket.socket()
        OPEN_PHONES.append(self)
        if rcvbuf:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf)
        self.sock.settimeout(TIMEOUT)
        self.sock.connect(("127.0.0.1", port))

    def send(self, data: bytes) -> "Phone":
        self.sock.sendall(data)
        return self

    def recv_exact(self, count: int) -> bytes:
        out = b""
        while len(out) < count:
            chunk = self.sock.recv(count - len(out))
            assert chunk, "the relay closed the phone connection early"
            out += chunk
        return out

    def is_closed(self) -> bool:
        try:
            return self.sock.recv(1) == b""
        except ConnectionResetError:
            return True

    def close(self) -> None:
        self.sock.close()


class Mac:

    def __init__(self, session) -> None:
        self.session = session
        self._pool = ThreadPoolExecutor(max_workers=1)

    def frame(self, timeout: float = TIMEOUT) -> Tuple[int, int, bytes]:
        future = self._pool.submit(self.session.receive_bytes)
        try:
            return frames.unpack(future.result(timeout))
        except TimeoutError as exc:
            raise AssertionError("no frame arrived from the relay") from exc

    def send(self, kind: int, sid: int, payload: bytes = b"") -> None:
        self.session.send_bytes(frames.pack(kind, sid, payload))

    def accept_stream(self, sni: Optional[str] = None) -> Tuple[int, dict, bytes]:
        kind, sid, payload = self.frame()
        assert kind == frames.OPEN, f"expected OPEN, got {kind}"
        opened = json.loads(payload)
        kind2, sid2, first = self.frame()
        assert (kind2, sid2) == (frames.DATA, sid)
        return sid, opened, first


def link_headers(device: Device, token: str, *, audience: bytes = LINK_TUNNEL_POP_AUDIENCE,
                 ts: Optional[int] = None) -> dict:
    moment = int(time.time()) if ts is None else ts
    jti = json.loads(_payload(token))["jti"]
    signature = device.key.sign(pop_message(jti, moment, audience))
    return {"authorization": f"Bearer {token}", "carnivore-relay-client": "1.8.1",
            "carnivore-relay-pop-ts": str(moment), "carnivore-relay-pop": b64url(signature)}


def link_reauth(device: Device, token: str, *, audience: bytes = LINK_TUNNEL_POP_AUDIENCE) -> bytes:
    headers = link_headers(device, token, audience=audience)
    return json.dumps({"token": token, "pop_ts": int(headers["carnivore-relay-pop-ts"]),
                       "pop": headers["carnivore-relay-pop"]}).encode()


@contextmanager
def link_relay(issuer: Issuer, limits: Optional[LinkLimits] = None, **settings) -> Iterator[tuple]:
    fields = {"issuer_keys": issuer.pins, "link_enabled": True, "link_port": 0, **settings}
    with relay(build_settings(**fields)) as (client, _factory):
        port = 0
        if fields["link_enabled"]:
            port = client.app.state.link.server.sockets[0].getsockname()[1]
        if limits is not None:
            client.app.state.link = LinkRegistry(limits)
        yield client, port


def wait_online(client, device: Device, timeout: float = TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if client.app.state.link.online(device.device_id) is not None:
            return
        time.sleep(0.01)
    raise AssertionError("the tunnel never registered")


@contextmanager
def tunnel(client, device: Device, issuer: Issuer, **token_claims) -> Iterator[Mac]:
    token = issuer.token(device, **token_claims)
    with client.websocket_connect("/v1/link/tunnel", headers=link_headers(device, token),
                                  subprotocols=[LINK_SUBPROTOCOL]) as session:
        wait_online(client, device)
        yield Mac(session)
