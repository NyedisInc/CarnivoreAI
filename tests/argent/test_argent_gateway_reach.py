
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Optional

import pytest
from pydantic import ValidationError

from src.core.argent import gateway_reach, health, overlay, poll_relay
from src.core.argent import settings as settings_module
from src.core.argent.gateway_reach import CARRIED, DIRECT, OFF, UNREACHABLE, ConnectProxy, GatewayTarget, Reach, ReachError, target_of
from src.core.argent.pair_credential import PairRefused
from src.core.argent.settings import ArgentSettings
from src.core.sessions.launch_overlay import OverlayContext

GATEWAY = "https://gw.argent.test"
NOW = 1_800_000_000.0


@pytest.fixture()
def sockdir():
    path = Path(tempfile.mkdtemp(prefix="cc-p20-", dir="/tmp"))
    os.chmod(path, 0o700)
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture()
def switch(monkeypatch):
    def _set(enabled: bool = True, gateway: str = GATEWAY) -> None:
        monkeypatch.setattr(settings_module, "read", lambda path=None: ArgentSettings(enabled=enabled, gateway_url=gateway, ca_path="/ca.pem"))
    _set()
    return _set


class FakeSide:

    def __init__(self, direct_rc: int = 7, up: bool = True, forward_error: Optional[Exception] = None) -> None:
        self.direct_rc, self.is_up, self.forward_error = direct_rc, up, forward_error
        self.scripts: List[str] = []
        self.forwards: List[str] = []

    async def run(self, argv: Any = None, *, script: Optional[str] = None, timeout: float = 30.0) -> Any:
        self.scripts.append(script or "")
        return SimpleNamespace(returncode=0 if " -x " in (script or "") else self.direct_rc)

    async def forward_remote_tcp(self, local_path: str) -> int:
        if self.forward_error is not None:
            raise self.forward_error
        self.forwards.append(local_path)
        return 41001


def make_reach(side: Optional[FakeSide], sockdir: Path) -> Reach:
    return Reach(side_for=lambda key: side, label_for=lambda key: key, socket_dir=sockdir, clock=lambda: NOW)


async def echo_dial(seen: List[Any]):
    async def handle(reader, writer):
        data = await reader.read(64)
        writer.write(data)
        await writer.drain()
        writer.close()
    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    async def dial(host: str, _port: int):
        seen.append((host, _port))
        return await asyncio.open_connection("127.0.0.1", port)
    return server, dial


async def connect_line(path: str, request: bytes) -> bytes:
    reader, writer = await asyncio.open_unix_connection(path)
    writer.write(request)
    await writer.drain()
    line = await asyncio.wait_for(reader.readline(), 5)
    writer.close()
    return line


async def assert_proxy_only_serves_gateway(proxy: ConnectProxy, seen: List[Any]) -> None:
    for other in (b"CONNECT evil.example:443 HTTP/1.1\r\n\r\n", b"CONNECT gw.argent.test:8443 HTTP/1.1\r\n\r\n", b"CONNECT 127.0.0.1:443 HTTP/1.1\r\n\r\n",
                  b"CONNECT gw.argent.test.evil.example:443 HTTP/1.1\r\n\r\n"):
        assert b" 403 " in await connect_line(proxy.path, other), other
    assert b" 405 " in await connect_line(proxy.path, b"GET http://gw.argent.test/ HTTP/1.1\r\n\r\n")
    assert seen == [], f"the proxy dialed {seen}"
    reader, writer = await asyncio.open_unix_connection(proxy.path)
    writer.write(b"CONNECT GW.argent.test.:443 HTTP/1.1\r\nHost: gw.argent.test:443\r\n\r\n")
    assert b" 200 " in await asyncio.wait_for(reader.readline(), 5)
    await reader.readuntil(b"\r\n")
    writer.write(b"hello")
    assert await asyncio.wait_for(reader.read(5), 5) == b"hello"
    writer.close()
    assert seen == [("gw.argent.test", 443)]


class LeakyTarget(GatewayTarget):

    def matches(self, authority: str) -> bool:
        return True


def test_target_parse_is_strict() -> None:
    assert target_of("https://GW.argent.test.") == GatewayTarget("gw.argent.test", 443)
    for bad in ("http://gw.argent.test", "https://u:p@gw.argent.test", "https://", "https://bad host", "ftp://x",
                "https://gw.argent.test:8443/x", "https://10.0.0.5", "https://[::1]", "https://2130706433", "https://localhost", "https://db.corp.internal",
                "https://nas.lan", "https://singlelabel"):
        with pytest.raises(ReachError):
            target_of(bad)


@pytest.mark.asyncio
async def test_the_proxy_tunnels_only_to_the_gateway_and_a_leaky_one_is_caught(sockdir) -> None:
    seen: List[Any] = []
    server, dial = await echo_dial(seen)
    proxy = ConnectProxy(GatewayTarget("gw.argent.test", 443), dial)
    await proxy.start(str(sockdir / "p.sock"))
    try:
        assert oct(os.stat(proxy.path).st_mode & 0o777) == "0o600"
        await assert_proxy_only_serves_gateway(proxy, seen)
    finally:
        await proxy.stop()
    assert not os.path.exists(proxy.path or str(sockdir / "p.sock"))
    seen2: List[Any] = []
    leaky = ConnectProxy(LeakyTarget("gw.argent.test", 443), (await echo_dial(seen2))[1])
    await leaky.start(str(sockdir / "q.sock"))
    try:
        with pytest.raises(AssertionError):
            await assert_proxy_only_serves_gateway(leaky, seen2)
    finally:
        await leaky.stop()
        server.close()


@pytest.mark.asyncio
async def test_a_direct_computer_is_left_alone(sockdir, switch) -> None:
    side = FakeSide(direct_rc=0)
    reach = make_reach(side, sockdir)
    state = await reach.ensure("studio")
    assert state.state == DIRECT and side.forwards == [] and reach.exports_for("studio") == "" and reach.reason_for("studio") == ""
    assert list(sockdir.iterdir()) == []
    assert (await reach.ensure("studio")) is state and len(side.scripts) == 1


@pytest.mark.asyncio
async def test_an_unreachable_computer_gets_the_proxy_and_a_forward_to_the_gateway_proxy_only(sockdir, switch) -> None:
    side = FakeSide(direct_rc=7)
    reach = make_reach(side, sockdir)
    state = await reach.ensure("studio")
    assert state.state == CARRIED and state.port == 41001
    assert side.forwards == [str(sockdir / "argent-gw.sock")] and os.path.exists(side.forwards[0])
    exports = reach.exports_for("studio")
    assert "HTTPS_PROXY=http://127.0.0.1:41001" in exports and "NO_PROXY=" in exports
    assert (await reach.ensure("studio")).state == CARRIED and side.forwards == side.forwards[:1]
    await reach.close()
    assert not os.path.exists(str(sockdir / "argent-gw.sock"))


def insecure(script: str) -> bool:
    return any(bad in script for bad in (" -k ", "--insecure", "NODE_TLS_REJECT_UNAUTHORIZED", "CODEX_CA_CERTIFICATE=''", "ANTHROPIC_BASE_URL='http://127", "ANTHROPIC_BASE_URL=http://127"))


@pytest.mark.asyncio
async def test_tls_verification_stays_on_end_to_end(sockdir, switch) -> None:
    side = FakeSide(direct_rc=7)
    reach = make_reach(side, sockdir)
    await reach.ensure("studio")
    carried = overlay.preamble(GATEWAY, "/ca.pem", reach.exports_for("studio"))
    assert not any(insecure(s) for s in side.scripts) and not insecure(carried)
    assert f"ANTHROPIC_BASE_URL={GATEWAY}" in carried and "NODE_EXTRA_CA_CERTS=/ca.pem" in carried
    assert carried.index("HTTPS_PROXY") > carried.index('if [ -n "$_ak" ]')
    assert insecure(carried + " export NODE_TLS_REJECT_UNAUTHORIZED=0;")
    assert insecure("curl -k https://x ")
    await reach.close()


@pytest.mark.asyncio
async def test_no_forward_or_a_dropped_master_gives_the_named_reason(sockdir, switch) -> None:
    refused = FakeSide(direct_rc=7, forward_error=RuntimeError("administratively prohibited"))
    reach = make_reach(refused, sockdir)
    state = await reach.ensure("studio")
    assert state.state == UNREACHABLE and state.reason == "gateway unreachable from studio" == reach.reason_for("studio") and reach.exports_for("studio") == ""
    down = FakeSide(direct_rc=7, up=False)
    reach2 = make_reach(down, sockdir)
    assert (await reach2.ensure("studio")).reason == "gateway unreachable from studio" and down.scripts == []
    gone = make_reach(None, sockdir)
    assert (await gone.ensure("studio")).state == UNREACHABLE
    up = FakeSide(direct_rc=7)
    reach3 = make_reach(up, sockdir)
    await reach3.ensure("studio")
    up.is_up = False
    assert reach3.exports_for("studio") == "" and reach3.reason_for("studio") == "gateway unreachable from studio"
    await reach.close(), await reach3.close()


@pytest.mark.asyncio
async def test_off_opens_nothing(sockdir, switch) -> None:
    switch(enabled=False)
    side = FakeSide(direct_rc=7)
    reach = make_reach(side, sockdir)
    assert (await reach.ensure("studio")).state == OFF
    assert side.scripts == [] and side.forwards == [] and list(sockdir.iterdir()) == [] and reach.exports_for("studio") == ""
    assert gateway_reach.get() is None


@pytest.mark.asyncio
async def test_overlay_proxies_only_a_tethered_launch_and_refuses_an_unreachable_computer(sockdir, switch, monkeypatch) -> None:
    side = FakeSide(direct_rc=7)
    reach = make_reach(side, sockdir)
    gateway_reach.set_reach(reach)
    try:
        monkeypatch.setattr(health, "latest", lambda: health.HealthReport(state=health.UP, mints_accepted=True, checked_at=NOW))
        provider = overlay.ArgentOverlay(clock=lambda: NOW)
        assert "HTTPS_PROXY" not in provider.plan("claude", "pane").preamble
        await reach.ensure("studio")
        plan = provider.plan("claude", "pane", "studio")
        assert "HTTPS_PROXY=http://127.0.0.1:41001" in plan.preamble
        assert provider._reach_reason("studio", plan) == ""
        bare = provider.plan("claude", "pane", "other")
        assert "HTTPS_PROXY" not in bare.preamble and provider._reach_reason("other", bare) == "gateway unreachable from other"
        delivery = await provider.materialize(bare, OverlayContext(harness="claude", session_ref="s", host_key="other"))
        assert delivery.note["tethered"] is False and delivery.note["reason"] == "gateway unreachable from other"
    finally:
        await reach.close()
        gateway_reach.set_reach(None)


def test_a_relayed_poll_carries_no_credential_and_a_polling_computer_refuses_it(monkeypatch) -> None:
    ok = {"as_of": NOW, "health": {"state": "up"}, "cost": {"state": "ok", "items": {"w1": {"held": True}}}}
    PollBody = poll_relay.PollBody
    for extra in ({"access_token": "FIXTURE-not-a-secret"}, {"refresh_token": "FIXTURE-not-a-secret"}):
        with pytest.raises(ValidationError):
            PollBody.model_validate({**ok, **extra})
    with pytest.raises(ValidationError):
        PollBody.model_validate({**ok, "cost": {"blob": "x" * (poll_relay.MAX_BYTES + 1)}})
    body = PollBody.model_validate(ok)
    monkeypatch.setattr(settings_module, "read", lambda path=None: ArgentSettings(enabled=True, gateway_url=GATEWAY))
    poll_relay.forget()
    monkeypatch.setattr(health, "latest", lambda: health.HealthReport(state=health.UP, checked_at=NOW))
    with pytest.raises(PairRefused) as refused:
        poll_relay.receive("desk", body, listed=lambda s: True)
    assert refused.value.code == "polls_itself" and poll_relay.relayed() is None
    monkeypatch.setattr(health, "latest", lambda: health.HealthReport(state=health.DOWN, checked_at=NOW))
    with pytest.raises(PairRefused) as unlisted:
        poll_relay.receive("stranger", body, listed=lambda s: False)
    assert unlisted.value.code == "not_listed"
    poll_relay.receive("desk", body, listed=lambda s: s == "desk", clock=lambda: NOW)
    fresh = poll_relay.relayed(lambda: NOW + 1)
    assert fresh is not None and fresh["stale"] is False and "token" not in str(fresh)
    stale = poll_relay.relayed(lambda: NOW + poll_relay.STALE_SECONDS + 1)
    assert stale["stale"] is True and stale["cost"]["items"]["w1"]["held"] is True
    monkeypatch.setattr(settings_module, "read", lambda path=None: ArgentSettings(enabled=False, gateway_url=GATEWAY))
    with pytest.raises(PairRefused) as off:
        poll_relay.receive("desk", body, listed=lambda s: True)
    assert off.value.code == "feature_off"
    poll_relay.forget()


@pytest.mark.asyncio
async def test_the_sender_sends_only_own_results_on_change_to_capable_computers(monkeypatch) -> None:
    from src.core.argent import cost_poller

    monkeypatch.setattr(settings_module, "read", lambda path=None: ArgentSettings(enabled=True, gateway_url=GATEWAY))
    monkeypatch.setattr(health, "latest", lambda: health.HealthReport(state=health.UP, checked_at=NOW))
    snap = {"state": "ok", "items": {"w1": {"held": False}}}
    monkeypatch.setattr(cost_poller, "snapshot", lambda: snap)
    posted: List[Any] = []

    def post_for(code: int):
        async def post(method: str, path: str, body: Any):
            posted.append((path, body))
            return code, {}
        return post

    sender = poll_relay.PollSender(lambda: [("a", post_for(200), [poll_relay.CAP_POLL]), ("b", post_for(200), []), ("c", post_for(409), [poll_relay.CAP_POLL])],
                                   clock=lambda: NOW)
    assert await sender.after_poll() == ["a"]
    assert sender.sent == {"a": "applied", "c": "polls_itself"} and len(posted) == 2
    assert all("token" not in str(body) for _, body in posted)
    assert await sender.after_poll() == [] and len(posted) == 2
    snap["items"]["w1"]["held"] = True
    assert await sender.after_poll() == ["a"] and len(posted) == 3
    monkeypatch.setattr(health, "latest", lambda: health.HealthReport(state=health.DOWN, checked_at=NOW))
    assert await sender.after_poll() == []
    monkeypatch.setattr(settings_module, "read", lambda path=None: ArgentSettings(enabled=False, gateway_url=GATEWAY))
    monkeypatch.setattr(health, "latest", lambda: health.HealthReport(state=health.UP, checked_at=NOW))
    snap["items"]["w1"]["held"] = False
    assert await sender.after_poll() == [] and len(posted) == 3
