
from __future__ import annotations

import asyncio
import time

import pytest

from relay.auth import (
    ReplayCache,
    TokenRefused,
    b64url,
    verify_pop,
    verify_relay_token,
)
from relay.config import RelayConfigError, parse_issuer_keys
from relay.denylist import Denylist, DenylistRefused
from relay.tenancy import Tenancy
from tests.relay_v2_support import DEFAULT_LIM, Device, Issuer


@pytest.fixture
def issuer() -> Issuer:
    return Issuer()


@pytest.fixture
def device() -> Device:
    return Device()




def test_a_good_token_verifies_to_its_claims(issuer, device):
    claims = verify_relay_token(issuer.token(device), issuer.pins)
    assert (claims.sub, claims.dpk, claims.ten) == (device.device_id, device.pub, device.ten)
    assert claims.lim == DEFAULT_LIM


def test_a_bad_signature_is_refused(issuer, device):
    other = Issuer()
    with pytest.raises(TokenRefused) as refused:
        verify_relay_token(other.token(device), issuer.pins)
    assert refused.value.reason == "bad_signature"


def test_a_tampered_payload_is_refused(issuer, device):
    head, body, sig = issuer.token(device).split(".")
    forged = issuer.token(device, sub=Device().device_id).split(".")[1]
    with pytest.raises(TokenRefused):
        verify_relay_token(f"{head}.{forged}.{sig}", issuer.pins)


def test_the_wrong_audience_is_refused(issuer, device):
    with pytest.raises(TokenRefused) as refused:
        verify_relay_token(issuer.token(device, aud="api.carnivore.ai"), issuer.pins)
    assert refused.value.reason == "wrong_audience"


def test_an_expired_token_is_refused_past_the_skew(issuer, device):
    now = int(time.time())
    token = issuer.token(device, exp=now - 61)
    with pytest.raises(TokenRefused) as refused:
        verify_relay_token(token, issuer.pins)
    assert refused.value.reason == "expired"
    assert verify_relay_token(issuer.token(device, exp=now - 30), issuer.pins)


def test_a_token_not_yet_valid_is_refused(issuer, device):
    with pytest.raises(TokenRefused) as refused:
        verify_relay_token(issuer.token(device, nbf=int(time.time()) + 120), issuer.pins)
    assert refused.value.reason == "not_yet_valid"


def test_an_unknown_kid_is_refused(device):
    rogue = Issuer(kid="rt9")
    with pytest.raises(TokenRefused) as refused:
        verify_relay_token(rogue.token(device), {"rt1": Issuer().pins["rt1"]})
    assert refused.value.reason == "header_not_allowed"


@pytest.mark.parametrize("header", [
    b'{"alg":"none","kid":"rt1","typ":"carnivore-relay+jwt"}',
    b'{"alg":"EdDSA","kid":"rt1","typ":"carnivore-relay-denylist+jws"}',
    b'{"kid":"rt1","alg":"EdDSA","typ":"carnivore-relay+jwt"}',
    b'{"alg":"EdDSA", "kid":"rt1","typ":"carnivore-relay+jwt"}',
])
def test_header_bytes_that_are_not_exactly_the_allowlisted_ones_are_refused(issuer, device, header):
    with pytest.raises(TokenRefused) as refused:
        verify_relay_token(issuer.token(device, header=header), issuer.pins)
    assert refused.value.reason == "header_not_allowed"


def test_a_sub_that_is_not_the_hash_of_dpk_is_refused(issuer, device):
    with pytest.raises(TokenRefused) as refused:
        verify_relay_token(issuer.token(device, sub=Device().device_id), issuer.pins)
    assert refused.value.reason == "sub_not_key"


def test_limits_must_all_be_positive_whole_numbers(issuer, device):
    for lim in ({**DEFAULT_LIM, "links": 0}, {**DEFAULT_LIM, "pubs": True},
                {k: v for k, v in DEFAULT_LIM.items() if k != "bps"}):
        with pytest.raises(TokenRefused):
            verify_relay_token(issuer.token(device, lim=lim), issuer.pins)




def test_a_good_proof_passes_once_and_its_replay_is_refused(issuer, device):
    token = issuer.token(device)
    claims = verify_relay_token(token, issuer.pins)
    pop = device.pop(token)
    cache = ReplayCache()
    verify_pop(claims, pop["carnivore-relay-pop-ts"], pop["carnivore-relay-pop"], cache)
    with pytest.raises(TokenRefused) as refused:
        verify_pop(claims, pop["carnivore-relay-pop-ts"], pop["carnivore-relay-pop"], cache)
    assert refused.value.reason == "pop_replayed"
    later = device.pop(token, ts=int(pop["carnivore-relay-pop-ts"]) + 1)
    verify_pop(claims, later["carnivore-relay-pop-ts"], later["carnivore-relay-pop"], cache)


def test_a_skewed_proof_is_refused(issuer, device):
    token = issuer.token(device)
    claims = verify_relay_token(token, issuer.pins)
    stale = device.pop(token, ts=int(time.time()) - 61)
    with pytest.raises(TokenRefused) as refused:
        verify_pop(claims, stale["carnivore-relay-pop-ts"], stale["carnivore-relay-pop"],
                   ReplayCache())
    assert refused.value.reason == "pop_skewed"


def test_a_non_ascii_digit_timestamp_is_a_refusal_not_a_crash(issuer, device):
    claims = verify_relay_token(issuer.token(device), issuer.pins)
    with pytest.raises(TokenRefused) as refused:
        verify_pop(claims, "\u00b2", "x", ReplayCache())
    assert refused.value.reason == "pop_malformed"


def test_a_proof_by_another_key_is_refused(issuer, device):
    token = issuer.token(device)
    claims = verify_relay_token(token, issuer.pins)
    thief = Device().pop(token)
    with pytest.raises(TokenRefused) as refused:
        verify_pop(claims, thief["carnivore-relay-pop-ts"], thief["carnivore-relay-pop"],
                   ReplayCache())
    assert refused.value.reason == "pop_bad_signature"


def test_the_replay_cache_forgets_after_its_window():
    now = [1000.0]
    cache = ReplayCache(clock=lambda: now[0])
    assert cache.claim("j", 1, "d") is None and cache.claim("j", 1, "d") == "pop_replayed"
    now[0] += 121
    assert cache.claim("j", 1, "d") is None


def test_the_replay_cache_is_bounded_and_prunes_what_expired():
    now = [1000.0]
    cache = ReplayCache(clock=lambda: now[0], max_entries=2)
    assert cache.claim("a", 1, "da") is None and cache.claim("b", 1, "db") is None
    assert cache.claim("c", 1, "dc") == "pop_cache_full", "a full cache refuses"
    assert cache.claim("a", 1, "da") == "pop_replayed", "and never forgets early"
    now[0] += 121
    assert cache.claim("c", 1, "dc") is None
    assert len(cache) == 1, "expired entries are removed, not just ignored"


def test_one_device_cannot_fill_the_replay_cache():
    now = [1000.0]
    cache = ReplayCache(clock=lambda: now[0], max_entries=100, max_per_device=3)
    for ts in range(3):
        assert cache.claim(f"j{ts % 2}", ts, "greedy") is None
    assert cache.claim("j0", 99, "greedy") == "pop_device_limit"
    assert cache.claim("j9", 99, "greedy") == "pop_device_limit", "counted across tokens"
    assert cache.claim("k", 1, "other") is None, "another device is unaffected"
    now[0] += 121
    assert cache.claim("j0", 99, "greedy") is None, "the share frees as the window closes"


def test_a_device_over_its_proof_share_is_refused_by_verify_pop(issuer, device):
    cache = ReplayCache(max_per_device=2)
    base = int(time.time())
    for offset in range(2):
        token = issuer.token(device)
        claims = verify_relay_token(token, issuer.pins)
        pop = device.pop(token, ts=base + offset)
        verify_pop(claims, pop["carnivore-relay-pop-ts"], pop["carnivore-relay-pop"], cache)
    token = issuer.token(device)
    claims = verify_relay_token(token, issuer.pins)
    pop = device.pop(token, ts=base + 2)
    with pytest.raises(TokenRefused) as refused:
        verify_pop(claims, pop["carnivore-relay-pop-ts"], pop["carnivore-relay-pop"], cache)
    assert refused.value.reason == "pop_device_limit"




def test_the_issuer_pin_parses_and_refuses_garbage():
    assert parse_issuer_keys("rt1:BoQUO9ZTL5_LhHOinJBXvdKSsvFIXuKbNm4BdZkIsFs")["rt1"]
    assert parse_issuer_keys("") == {}
    for bad in ("rt1:short", "rt1:" + b64url(bytes(32)) + "=", "rt 1:" + b64url(bytes(32)),
                "rt1:" + b64url(bytes(32)) + ",rt1:" + b64url(bytes(32))):
        with pytest.raises(RelayConfigError):
            parse_issuer_keys(bad)




def test_the_denylist_adopts_a_verified_set_and_refuses_a_lower_seq(issuer, device):
    until = int(time.time()) + 600
    denylist = Denylist()
    assert denylist.apply(issuer.denylist(5, [{"sub": device.device_id, "until": until}]),
                          issuer.pins)
    assert denylist.is_denied(device.device_id, "other")
    with pytest.raises(DenylistRefused):
        denylist.apply(issuer.denylist(4, []), issuer.pins)
    assert denylist.is_denied(device.device_id, "other"), "the last good copy stays"
    denylist.apply(issuer.denylist(6, [{"ten": device.ten, "until": until}]), issuer.pins)
    assert not denylist.is_denied(device.device_id, "x")
    assert denylist.is_denied("x", device.ten)


def test_the_denylist_refuses_a_forged_or_mistyped_page(issuer, device):
    denylist = Denylist()
    with pytest.raises(DenylistRefused):
        denylist.apply(Issuer().denylist(9, []), issuer.pins)
    with pytest.raises(DenylistRefused):
        denylist.apply({"denylist": [issuer.token(device)]}, issuer.pins)
    assert denylist.seq is None


def test_the_denylist_refuses_a_page_under_an_unpinned_kid(issuer, device):
    denylist = Denylist()
    until = int(time.time()) + 600
    denylist.apply(issuer.denylist(3, [{"sub": device.device_id, "until": until}]), issuer.pins)
    unpinned = Issuer(kid="rt9")
    unpinned.key = issuer.key
    with pytest.raises(DenylistRefused) as refused:
        denylist.apply(unpinned.denylist(4, []), issuer.pins)
    assert "header_not_allowed" in str(refused.value)
    assert denylist.seq == 3 and denylist.is_denied(device.device_id, "x"), "last good stays"


def test_a_page_with_a_non_numeric_seq_is_refused_not_raised(issuer):
    page = issuer.jws("carnivore-relay-denylist+jws", {"seq": [1], "issued_at": 0, "page": 1,
                                                       "pages": 1, "entries": []})
    with pytest.raises(DenylistRefused):
        Denylist().apply({"denylist": [page]}, issuer.pins)


@pytest.mark.asyncio
async def test_the_poller_survives_an_unexpected_fault():
    from relay import denylist as dl

    calls = []

    def fetch(_url):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("surprise")
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await dl.poll_forever(Denylist(), url="https://x", keys={}, on_update=lambda: None,
                              interval=0, fetch=fetch)
    assert len(calls) == 2, "the loop ended on the first fault"


@pytest.mark.asyncio
async def test_the_poller_keeps_the_last_good_copy_through_failures(issuer, device):
    from structlog.testing import capture_logs

    from relay import denylist as dl

    until = int(time.time()) + 600
    bodies = [issuer.denylist(3, [{"sub": device.device_id, "until": until}]),
              OSError("down"), issuer.denylist(2, []), Issuer().denylist(9, [])]
    updates = []

    def fetch(_url):
        if not bodies:
            raise asyncio.CancelledError
        item = bodies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def no_wait(_seconds):
        return None

    denylist = Denylist()
    with capture_logs() as logs, pytest.raises(asyncio.CancelledError):
        await dl.poll_forever(denylist, url="https://x", keys=issuer.pins,
                              on_update=lambda: updates.append(denylist.seq),
                              interval=30, fetch=fetch, sleep=no_wait)
    assert denylist.seq == 3 and denylist.is_denied(device.device_id, "x")
    assert updates == [3], "only an adopted set re-checks publishers"
    misses = [e for e in logs if e["event"] in ("relay_denylist_fetch_failed",
                                                "relay_denylist_refused")]
    assert [e["event"] for e in misses] == ["relay_denylist_fetch_failed",
                                            "relay_denylist_refused", "relay_denylist_refused"]
    for miss in misses:
        assert miss["seq"] == 3 and isinstance(miss["last_good_age_s"], int)


@pytest.mark.asyncio
async def test_the_poll_interval_is_jittered_within_a_fifth():
    from relay import denylist as dl

    draws, slept, calls = [0.0, 0.5, 0.9999], [], []

    def fetch(_url):
        calls.append(1)
        if len(calls) > 3:
            raise asyncio.CancelledError
        raise OSError("down")

    async def record(seconds):
        slept.append(seconds)

    with pytest.raises(asyncio.CancelledError):
        await dl.poll_forever(Denylist(), url="https://x", keys={}, on_update=lambda: None,
                              interval=30, fetch=fetch, jitter=lambda: draws.pop(0) if draws else 0.5,
                              sleep=record)
    assert slept[0] == pytest.approx(24.0) and slept[1] == pytest.approx(30.0)
    assert 35.99 < slept[2] < 36.0


@pytest.mark.asyncio
async def test_a_hung_fetch_cannot_freeze_the_poller(monkeypatch):
    import threading

    from relay import denylist as dl

    monkeypatch.setattr(dl, "POLL_FETCH_WAIT_SECONDS", 0.2)
    release, calls = threading.Event(), []

    def fetch(_url):
        calls.append(1)
        if len(calls) == 1:
            release.wait(5)
            raise OSError("late")
        raise asyncio.CancelledError

    async def no_wait(_seconds):
        return None

    try:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(dl.poll_forever(Denylist(), url="https://x", keys={},
                                                   on_update=lambda: None, interval=30,
                                                   fetch=fetch, sleep=no_wait), 3)
    finally:
        release.set()
    assert len(calls) == 2, "the poller never moved past the hung fetch"


def test_an_older_copy_at_the_same_seq_is_refused(issuer, device):
    from tests.relay_v2_support import DENYLIST_TYP
    until = int(time.time()) + 600

    def page(issued_at, entries):
        return {"denylist": [issuer.jws(DENYLIST_TYP, {"seq": 5, "issued_at": issued_at, "page": 1,
                                                       "pages": 1, "entries": entries})]}

    denylist = Denylist()
    denylist.apply(page(2000, [{"sub": device.device_id, "until": until}]), issuer.pins)
    with pytest.raises(DenylistRefused):
        denylist.apply(page(1999, []), issuer.pins)
    assert denylist.is_denied(device.device_id, "x"), "the newer copy stays"
    denylist.apply(page(2001, []), issuer.pins)
    assert not denylist.is_denied(device.device_id, "x"), "a newer copy at the same seq is taken"


def test_a_backward_wall_clock_step_does_not_reopen_a_replay():
    mono, wall = [1000.0], [5000.0]
    cache = ReplayCache(clock=lambda: mono[0], wall=lambda: wall[0])
    assert cache.claim("j", 5000, "d") is None
    mono[0] += 121
    wall[0] = 5000 + 30
    assert cache.claim("j", 5000, "d") == "pop_replayed"
    wall[0] = 5000 + 61
    assert cache.claim("k", 5061, "d") is None and len(cache) == 1, "pruned once truly stale"


@pytest.mark.parametrize("head,drop", [
    (b"HTTP/1.1 200 OK\r\n", b"X"),
    (b"HTTP/1.1 200 OK\r\nContent-Length: 100000\r\n\r\n", b" "),
], ids=["headers", "body"])
def test_a_dripping_server_is_cut_at_the_deadline(monkeypatch, head, drop):
    import http.client
    import socket
    import threading

    from relay import denylist as dl

    monkeypatch.setattr(dl, "FETCH_DEADLINE_SECONDS", 1.0)
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    stop = threading.Event()

    def drip():
        conn, _ = server.accept()
        with conn:
            try:
                conn.sendall(head)
                while not stop.wait(0.2):
                    conn.sendall(drop)
            except OSError:
                pass

    threading.Thread(target=drip, daemon=True).start()
    outcome = []

    def fetch():
        try:
            dl.fetch_json(f"http://127.0.0.1:{server.getsockname()[1]}/v1/relay/denylist")
            outcome.append("returned")
        except (OSError, http.client.HTTPException) as exc:
            outcome.append(exc)

    worker = threading.Thread(target=fetch, daemon=True)
    worker.start()
    worker.join(3.0)
    stop.set()
    server.close()
    assert outcome and outcome[0] != "returned", "the fetch outlived its deadline"


def test_an_expired_entry_denies_nothing(issuer, device):
    denylist = Denylist()
    denylist.apply(issuer.denylist(1, [{"sub": device.device_id,
                                         "until": int(time.time()) - 1}]), issuer.pins)
    assert not denylist.is_denied(device.device_id, device.ten)




@pytest.mark.asyncio
async def test_the_bucket_throttles_and_the_quota_refuses():
    slept = []

    async def sleep(seconds):
        slept.append(seconds)

    tenancy = Tenancy(clock=lambda: 50.0, wall=lambda: 1_700_000_000, sleep=sleep)
    lim = {**DEFAULT_LIM, "bps": 100, "burst": 100, "bytes_day": 250}
    assert await tenancy.consume("t", 100, lim) is None and slept == []
    assert await tenancy.consume("t", 50, lim) is None and slept == [0.5]
    assert await tenancy.consume("t", 100, lim) is None
    assert await tenancy.consume("t", 1, lim) == (4402, "quota"), "over bytes_day"
    assert tenancy.quota_spent("t", lim)


def test_the_connection_cap_counts_per_tenant():
    tenancy = Tenancy()
    lim = {**DEFAULT_LIM, "pubs": 1}
    assert tenancy.admit("t", "c1", lim)
    assert not tenancy.admit("t", "c2", lim)
    assert tenancy.admit("u", "c3", lim), "another tenant is not counted"
    tenancy.release("t", "c1")
    assert tenancy.admit("t", "c2", lim)
