
import asyncio

import pytest

from tests.phone_link.pairing_helpers import pair_device

from src.core.phone_link import gate as g
from src.core.phone_link.pairing import PairingStore

HOST = "abcdefghijklmnopqrstuvwxyz.link.carnivore.ai"


class Recorder:

    def __init__(self):
        self.scopes = []

    async def __call__(self, scope, receive, send):
        self.scopes.append(scope)
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})


@pytest.fixture
def rig(tmp_path):
    pairing = PairingStore(path=tmp_path / "p.db")
    cookie = pair_device(pairing, "203.0.113.5")
    streams, trusts, app = g.StreamTable(), [], Recorder()
    streams.add(40001, g.LinkStream(stream_id=7, client_ip="203.0.113.77", client_port=51234))
    gate = g.LinkGate(app, hostname=HOST, streams=streams, pairing=pairing, send_trust=trusts.append)
    yield gate, app, streams, trusts, cookie, pairing
    pairing.close()


async def call(gate, path, *, method="GET", host=HOST, cookie=None, port=40001, kind="http"):
    headers = [(b"host", host.encode())]
    if cookie:
        headers.append((b"cookie", f"{g.COOKIE_NAME}={cookie}".encode()))
    scope = {"type": kind, "path": path, "method": method, "headers": headers, "client": ("127.0.0.1", port)}
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b""}

    await gate(scope, receive, send)
    return scope, sent


def status(sent):
    return sent[0].get("status") if sent and sent[0]["type"] == "http.response.start" else None


@pytest.mark.asyncio
async def test_a_connection_the_tunnel_did_not_open_is_refused(rig):
    gate, app, *_ = rig
    _, sent = await call(gate, "/pair", port=55555)
    assert status(sent) == 403 and not app.scopes


@pytest.mark.asyncio
async def test_the_host_must_be_exactly_the_link_name(rig):
    gate, app, _, _, cookie, _ = rig
    for host in ("evil.example", "127.0.0.1", "x." + HOST, "192.168.1.5:8000", ""):
        _, sent = await call(gate, "/pair", host=host, cookie=cookie)
        assert status(sent) == 421, host
    _, sent = await call(gate, "/pair", host=HOST.upper() + ":443")
    assert status(sent) == 200 and app.scopes


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "/api/v1/hosts", "/api/v1/hosts/abc/sessions", "/api/v1/federation/hello",
    "/api/v1/federation", "/mcp", "/MCP", "/mcp/x", "/api/v1/phone-link",
    "/api/v1/phone-link/pairing-window", "/api/v1/phone-link/devices",
    "/api/v1/phone-link/devices/abc", "/Api/V1/Hosts"])
async def test_denied_route_classes_are_refused_even_with_a_valid_cookie(rig, path):
    gate, app, _, _, cookie, _ = rig
    for method in ("GET", "POST", "DELETE"):
        _, sent = await call(gate, path, method=method, cookie=cookie)
        assert status(sent) == 403, (path, method)
    assert not app.scopes


@pytest.mark.asyncio
async def test_a_denied_websocket_closes_before_accept(rig):
    gate, app, _, _, cookie, _ = rig
    _, sent = await call(gate, "/mcp", cookie=cookie, kind="websocket")
    assert sent[0]["type"] == "websocket.close" and not app.scopes


@pytest.mark.asyncio
@pytest.mark.parametrize("path", sorted(g.PUBLIC_PATHS))
async def test_the_pre_cookie_allow_list_passes_without_a_cookie(rig, path):
    gate, app, *_ = rig
    _, sent = await call(gate, path)
    assert status(sent) == 200 and app.scopes


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "/", "/api/v1/sessions/list", "/api/v1/auth/verify", "/ws/events", "/static/js/app.js",
    "/pair/other", "/pairing", "/health", "/pair/pair.js", "/static/dist/app.css", "/static/dist/app.js",
    "/static/dist/pair.js.map", "/static/fonts/jetbrains-mono/a.woff2", "/static/fonts/jetbrains-mono/OFL.txt"])
async def test_everything_else_needs_the_cookie(rig, path):
    gate, app, *_ = rig
    _, sent = await call(gate, path)
    assert status(sent) == 302 and (b"location", b"/pair") in sent[0]["headers"]
    _, sent = await call(gate, path, method="POST")
    assert status(sent) == 401
    _, sent = await call(gate, path, kind="websocket")
    assert sent[0]["type"] == "websocket.close"
    _, sent = await call(gate, path, cookie="not-a-real-cookie")
    assert status(sent) == 302
    assert not app.scopes


@pytest.mark.asyncio
async def test_a_paired_request_gets_the_real_address_via_link_and_one_trust(rig):
    gate, app, streams, trusts, cookie, _ = rig
    for _n in range(3):
        scope, sent = await call(gate, "/api/v1/sessions/list", cookie=cookie)
        assert status(sent) == 200
    assert scope["client"] == ("203.0.113.77", 51234) and scope["client"][0] != "127.0.0.1"
    assert scope["via_link"] is True and scope["link_host"] == HOST.lower()
    assert trusts == [7]
    assert streams.lookup(40001).trusted and streams.lookup(40001).request_seen


@pytest.mark.asyncio
async def test_a_pre_cookie_request_sends_no_trust_but_marks_the_request_seen(rig):
    gate, _, streams, trusts, *_ = rig
    await call(gate, "/pair")
    assert trusts == [] and streams.lookup(40001).request_seen


@pytest.mark.asyncio
async def test_a_revoked_cookie_stops_working_and_devices_map_to_streams(rig):
    gate, app, streams, _, cookie, pairing = rig
    await call(gate, "/", cookie=cookie)
    device = pairing.device_for_cookie(cookie)
    assert [s.stream_id for s in streams.for_device(device)] == [7]
    pairing.revoke(device)
    _, sent = await call(gate, "/", cookie=cookie)
    assert status(sent) == 302


@pytest.mark.asyncio
async def test_the_lifespan_scope_passes_through(rig):
    gate, app, *_ = rig
    await gate({"type": "lifespan"}, None, None)
    assert app.scopes[-1]["type"] == "lifespan"



DENIED = ["/api/v1/hosts", "/api/v1/federation/pair/begin", "/mcp", "/api/v1/phone-link",
          "/api/v1/auth/qr", "/api/v1/setup/state", "/setup"]
VARIANTS = ["{p}\n", "{p}\r", "{p}\t", "{p}/", "/{p}", "{p}\x00", "{p}\x7f", "{p_upper}", "{p}/../x",
            "/.{p}", "{p_dot}"]


def _variants(p):
    return [v.format(p=p, p_upper=p.upper(), p_dot=p.replace("/", "/./", 1)) for v in VARIANTS]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["http", "websocket"])
@pytest.mark.parametrize("prefix", DENIED)
async def test_no_denied_prefix_is_reachable_by_any_spelling(rig, kind, prefix):
    gate, app, _, _, cookie, _ = rig
    for path in [prefix] + _variants(prefix):
        _, sent = await call(gate, path, cookie=cookie, kind=kind)
        assert not app.scopes, path
        if kind == "http":
            assert status(sent) in (400, 403), (path, status(sent))
        else:
            assert sent[0]["type"] == "websocket.close", path


@pytest.mark.asyncio
async def test_a_raw_path_with_an_encoded_control_character_is_refused(rig):
    gate, app, _, _, cookie, _ = rig
    scope_extra = {"raw_path": b"/api/v1/hosts\x0a"}
    headers = [(b"host", HOST.encode()), (b"cookie", f"{g.COOKIE_NAME}={cookie}".encode())]
    scope = {"type": "http", "path": "/api/v1/hosts", "method": "GET", "headers": headers,
             "client": ("127.0.0.1", 40001), **scope_extra}
    sent = []

    async def send(m):
        sent.append(m)

    async def receive():
        return {"type": "http.request", "body": b""}

    await gate(scope, receive, send)
    assert status(sent) == 400 and not app.scopes


@pytest.mark.asyncio
async def test_forwarding_headers_are_stripped_from_a_link_scope(rig):
    gate, app, *_ , cookie, _ = rig[0], rig[1], rig[2], rig[3], rig[4], rig[5]
    scope = {"type": "http", "path": "/pair", "method": "GET", "client": ("127.0.0.1", 40001),
             "headers": [(b"host", HOST.encode()), (b"x-forwarded-for", b"1.1.1.1"),
                         (b"forwarded", b"for=1.1.1.1"), (b"x-real-ip", b"1.1.1.1")]}

    async def send(m):
        pass

    async def receive():
        return {}

    await gate(scope, receive, send)
    names = {k for k, _ in app.scopes[0]["headers"]}
    assert names == {b"host"} and app.scopes[0]["via_link"] is True


@pytest.mark.asyncio
async def test_a_refused_request_does_not_clear_the_pre_auth_deadline(rig):
    gate, app, streams, *_ = rig
    await call(gate, "/api/v1/sessions")
    await call(gate, "/mcp")
    await call(gate, "/pair", host="evil.example")
    assert streams.lookup(40001).request_seen is False
    await call(gate, "/pair")
    assert streams.lookup(40001).request_seen is True


@pytest.mark.asyncio
async def test_a_dot_dot_segment_is_a_400(rig):
    gate, app, *_ = rig
    _, sent = await call(gate, "/static/fonts/jetbrains-mono/../../../config.json")
    assert status(sent) == 400 and not app.scopes


def test_the_pre_cookie_routes_are_exactly_the_pair_page_its_status_the_two_claims_and_the_code_check():
    routes = {p for p in g.PUBLIC_PATHS if not p.startswith("/static/") and p != "/manifest.webmanifest"}
    assert routes == {"/pair", "/pair/status", "/pair/claim", "/pair/code", "/pair/verify"}


def test_the_pre_cookie_assets_are_exactly_the_pair_bundle_its_css_and_the_three_fonts():
    assets = {p for p in g.PUBLIC_PATHS if p.startswith("/static/") and "/icons/" not in p}
    assert assets == {
        "/static/dist/pair.js", "/static/dist/pair.css",
        "/static/fonts/jetbrains-mono/JetBrainsMono-Regular.woff2",
        "/static/fonts/jetbrains-mono/JetBrainsMono-Medium.woff2",
        "/static/fonts/jetbrains-mono/JetBrainsMono-Bold.woff2"}


def test_every_asset_the_pair_page_loads_is_on_the_pre_cookie_list():
    import re
    from pathlib import Path

    from src.core.phone_link.pair_page import PAIR_HTML

    root = Path(__file__).resolve().parents[2]
    loaded = set(re.findall(r'(?:src|href)="(/static/[^"]+)"', PAIR_HTML))
    css = (root / "web/src/pair/pair.css").read_text()
    for name in re.findall(r"@import '\.\./opscenter/([^']+)'", css):
        loaded |= set(re.findall(r"url\('(/static/[^']+)'\)", (root / "web/src/opscenter" / name).read_text()))
    assert loaded >= {"/static/dist/pair.js", "/static/dist/pair.css"} and len(loaded) == 5, loaded
    assert loaded <= g.PUBLIC_PATHS, loaded - g.PUBLIC_PATHS
