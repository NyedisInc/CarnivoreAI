
import pytest

from tests.phone_link.pairing_helpers import pair_device

from src.core.phone_link import gate as g
from src.core.phone_link.custom_domain import names
from src.core.phone_link.custom_domain.repair import SETTING, RepairGate
from src.core.phone_link.pairing import PairingStore
from src.core.relay_identity.session import RelayAuthError
from tests.phone_link.test_gate import Recorder, call, status
from tests.relay_v2_support import Issuer
from tests.test_relay_identity import FakeControl, _session

LINK = "abcdefghijklmnopqrstuvwxyz.link.carnivore.ai"
CUSTOM = "sync.example.com"


@pytest.fixture
def rig(tmp_path):
    pairing = PairingStore(path=tmp_path / "p.db")
    link_cookie = pair_device(pairing, "203.0.113.5", host=LINK)
    custom_cookie = pair_device(pairing, "203.0.113.5", host=CUSTOM)
    legacy_cookie = pair_device(pairing, "203.0.113.5")
    streams, app, live = g.StreamTable(), Recorder(), {"host": CUSTOM}
    streams.add(40001, g.LinkStream(stream_id=1, client_ip="203.0.113.77", client_port=1, sni=LINK))
    streams.add(40002, g.LinkStream(stream_id=2, client_ip="203.0.113.77", client_port=2, sni=CUSTOM))
    gate = g.LinkGate(app, hostname=LINK, streams=streams, pairing=pairing, send_trust=lambda sid: None,
                      custom_host=lambda: live["host"])
    yield gate, app, live, link_cookie, custom_cookie, legacy_cookie
    pairing.close()


@pytest.mark.asyncio
async def test_a_cookie_is_refused_on_any_name_but_the_one_it_was_issued_on(rig):
    gate, app, _, link_cookie, custom_cookie, legacy_cookie = rig
    _, sent = await call(gate, "/x", host=CUSTOM, cookie=link_cookie, port=40002)
    assert status(sent) == 302 and not app.scopes
    _, sent = await call(gate, "/x", host=LINK, cookie=custom_cookie, port=40001)
    assert status(sent) == 302 and not app.scopes
    _, sent = await call(gate, "/x", host=CUSTOM, cookie=legacy_cookie, port=40002)
    assert status(sent) == 302 and not app.scopes
    for host, cookie, port in ((LINK, link_cookie, 40001), (CUSTOM, custom_cookie, 40002), (LINK, legacy_cookie, 40001)):
        _, sent = await call(gate, "/x", host=host, cookie=cookie, port=port)
        assert status(sent) == 200, host
    assert [s["link_host"] for s in app.scopes] == [LINK, CUSTOM, LINK]


@pytest.mark.asyncio
async def test_host_must_equal_the_streams_open_sni_and_a_live_name(rig):
    gate, app, live, _, custom_cookie, _ = rig
    _, sent = await call(gate, "/pair", host=CUSTOM, port=40001)
    assert status(sent) == 421
    _, sent = await call(gate, "/pair", host=LINK, port=40002)
    assert status(sent) == 421
    live["host"] = None
    _, sent = await call(gate, "/pair", host=CUSTOM, port=40002)
    assert status(sent) == 421 and not app.scopes
    live["host"] = CUSTOM
    _, sent = await call(gate, "/pair", host=CUSTOM, port=40002)
    assert status(sent) == 200


def test_pairing_records_the_host_and_survives_a_reopen(tmp_path):
    path = tmp_path / "p.db"
    store = PairingStore(path=path)
    cookie = pair_device(store, "203.0.113.5", host="Sync.Example.com")
    store.close()
    again = PairingStore(path=path)
    assert again.device_for_cookie(cookie, CUSTOM) is not None
    assert again.device_for_cookie(cookie, LINK) is None
    assert again.device_for_cookie(cookie) is not None
    again.close()


@pytest.mark.parametrize("raw,expected", [
    (" Sync.Example.com. ", "sync.example.com"), ("sync.example.co.uk", "sync.example.co.uk"),
    ("bücher.example.de", "xn--bcher-kva.example.de"), ("sync.user.github.io", "sync.user.github.io")])
def test_good_names_normalise_to_the_a_label(raw, expected):
    assert names.normalise(raw) == expected


@pytest.mark.parametrize("raw,reason", [
    ("", "length"), ("a." * 130 + "com", "length"), ("*.example.com", "wildcard"), ("1.2.3.4", "ip_literal"),
    ("a.b.c.123", "ip_literal"), ("-a.example.com", "idna"), ("sync.carnivore.ai", "our_zone"),
    ("carnivore.ai", "our_zone"), ("x.localhost", "special_use"), ("x.home.arpa", "special_use"),
    ("co.uk", "public_suffix"), ("github.io", "public_suffix"), ("example.com", "apex"),
    ("example.co.uk", "apex"), ("user.github.io", "apex"), ("localhost", "special_use")])
def test_bad_names_say_which_rule_they_broke(raw, reason):
    with pytest.raises(names.BadDomain) as caught:
        names.normalise(raw)
    assert caught.value.reason == reason


def test_the_display_form_is_the_u_label():
    assert names.display("xn--bcher-kva.example.de") == "bücher.example.de"




class RepairControl(FakeControl):

    repair = None

    async def __call__(self, base, method, path, *, json_body=None, bearer=None):
        answer = await super().__call__(base, method, path, json_body=json_body, bearer=bearer)
        if path == "/token" and self.repair is not None:
            answer.body["link_repair"] = self.repair
        return answer


def paired(store, n):
    for _ in range(n):
        pair_device(store, "203.0.113.5", host=CUSTOM)


@pytest.mark.asyncio
async def test_a_larger_epoch_revokes_every_pairing_before_the_token_is_returned(tmp_path):
    store = PairingStore(path=tmp_path / "p.db")
    paired(store, 3)
    revoked, order = [], []

    async def revoke(device_id):
        assert store.setting(SETTING) is None
        revoked.append(device_id)
        store.revoke(device_id)

    control = RepairControl(Issuer())
    control.repair = 1
    gate = RepairGate(pairing=store, revoke_device=revoke, on_done=lambda: order.append("done"))

    async def enforce(epoch):
        await gate.enforce(epoch)
        order.append("enforced")

    session = _session(tmp_path, control)
    session._on_repair = enforce
    token = await session.token()
    assert order == ["done", "enforced"]
    assert len(revoked) == 3 and store.device_count() == 0 and store.setting(SETTING) == "1"
    assert token.token
    store.close()


@pytest.mark.asyncio
async def test_the_same_or_a_lower_epoch_changes_nothing_and_a_new_one_acts_again(tmp_path):
    store = PairingStore(path=tmp_path / "p.db")
    revoked = []

    async def revoke(device_id):
        revoked.append(device_id)
        store.revoke(device_id)

    gate = RepairGate(pairing=store, revoke_device=revoke)
    paired(store, 1)
    assert await gate.enforce(2) is True and len(revoked) == 1
    paired(store, 2)
    assert await gate.enforce(2) is False and await gate.enforce(1) is False and await gate.enforce(0) is False
    assert store.device_count() == 2 and gate.seen() == 2
    assert await gate.enforce(3) is True and store.device_count() == 0 and gate.seen() == 3
    store.close()


@pytest.mark.asyncio
async def test_a_fresh_install_with_no_pairings_revokes_nothing_and_stores_the_epoch(tmp_path):
    store = PairingStore(path=tmp_path / "p.db")

    async def revoke(device_id):
        raise AssertionError("nothing to revoke")

    gate = RepairGate(pairing=store, revoke_device=revoke)
    assert await gate.enforce(4) is True and gate.seen() == 4
    store.close()


@pytest.mark.asyncio
async def test_a_failed_revoke_refuses_the_token_and_leaves_the_epoch_unstored(tmp_path):
    store = PairingStore(path=tmp_path / "p.db")
    paired(store, 2)

    async def revoke(device_id):
        raise OSError("disk")

    control = RepairControl(Issuer())
    control.repair = 5
    session = _session(tmp_path, control)
    session._on_repair = RepairGate(pairing=store, revoke_device=revoke).enforce
    with pytest.raises(RelayAuthError):
        await session.token()
    assert session._token is None and store.setting(SETTING) is None and store.device_count() == 2
    store.close()


@pytest.mark.asyncio
async def test_repair_revokes_only_the_custom_hostname_pairings(tmp_path):
    store = PairingStore(path=tmp_path / "p.db")
    link = pair_device(store, "203.0.113.5", host=LINK)
    legacy = pair_device(store, "203.0.113.5")
    custom = pair_device(store, "203.0.113.5", host=CUSTOM)
    revoked = []

    async def revoke(device_id):
        revoked.append(device_id)
        store.revoke(device_id)

    gate = RepairGate(pairing=store, revoke_device=revoke, link_host=lambda: LINK)
    assert await gate.enforce(1) is True
    assert len(revoked) == 1 and store.device_count() == 2
    assert store.device_for_cookie(custom) is None
    assert store.device_for_cookie(link) is not None and store.device_for_cookie(legacy) is not None
    store.close()


@pytest.mark.asyncio
async def test_every_token_the_session_mints_calls_on_token(tmp_path):
    seen = []
    session = _session(tmp_path, FakeControl(Issuer()))
    session._on_token = lambda: seen.append(1)
    await session.token()
    assert seen == [1]
