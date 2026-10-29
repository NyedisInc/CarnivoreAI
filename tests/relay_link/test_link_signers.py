
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from relay.auth import (
    LINK_TUNNEL_POP_AUDIENCE, ReplayCache, TokenRefused, b64url, unb64url, verify_pop,
    verify_relay_token)
from src.core.relay_identity import device_key as mac
from tests.relay_v2_support import Issuer

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hosted" / "relay-control"))
import rc_crypto  # noqa: E402

SEED = bytes(range(32))
VALUE = "A" * 43


@pytest.fixture
def key() -> "mac.DeviceKey":
    return mac.DeviceKey.from_seed(SEED)


def claims_for(key):

    class Device:
        pub, device_id, ten = key.raw_pub, key.device_id, b64url(bytes(16))

    issuer = Issuer()
    return verify_relay_token(issuer.token(Device), issuer.pins)


def pop(key, claims, ts, message=mac.link_tunnel_pop_message):
    return key.sign(message(claims.jti, ts))


def test_the_mac_tunnel_pop_is_accepted_by_the_relay_verifier(key):
    claims, ts = claims_for(key), int(time.time())
    verify_pop(claims, str(ts), pop(key, claims, ts), ReplayCache(),
               audience=LINK_TUNNEL_POP_AUDIENCE)
    assert mac.LINK_TUNNEL_POP_AUDIENCE == LINK_TUNNEL_POP_AUDIENCE


def test_a_publish_pop_is_refused_as_a_tunnel_pop_and_the_reverse(key):
    claims, ts = claims_for(key), int(time.time())
    publish = pop(key, claims, ts, mac.pop_message)
    with pytest.raises(TokenRefused) as wrong:
        verify_pop(claims, str(ts), publish, ReplayCache(), audience=LINK_TUNNEL_POP_AUDIENCE)
    assert wrong.value.reason == "pop_bad_signature"
    with pytest.raises(TokenRefused):
        verify_pop(claims, str(ts), pop(key, claims, ts), ReplayCache())


def test_tunnel_pop_tampering_and_replay_are_refused(key):
    claims, ts = claims_for(key), int(time.time())
    good = pop(key, claims, ts)
    cache = ReplayCache()
    for text, sig in ((str(ts + 1), good), (str(ts), pop(key, claims, ts + 1)),
                      (str(ts), b64url(bytes(64))), (str(ts), good[:10] + ("A" if good[10] != "A" else "B") + good[11:])):
        with pytest.raises(TokenRefused):
            verify_pop(claims, text, sig, cache, audience=LINK_TUNNEL_POP_AUDIENCE)
    verify_pop(claims, str(ts), good, cache, audience=LINK_TUNNEL_POP_AUDIENCE)
    with pytest.raises(TokenRefused) as replayed:
        verify_pop(claims, str(ts), good, cache, audience=LINK_TUNNEL_POP_AUDIENCE)
    assert replayed.value.reason == "pop_replayed"


def test_the_acme_message_is_byte_identical_on_both_sides_and_verifies(key):
    nonce = bytes(range(16))
    for action, arg in (("set", VALUE), ("clear", VALUE), ("status", "C2682N5HXP0BZ4")):
        signed = mac.acme_txt_message(key.device_id, 1_790_000_000, nonce, action, arg)
        assert signed == rc_crypto.acme_txt_message(key.device_id, 1_790_000_000, nonce, action, arg)
        assert rc_crypto.verify_ed25519(key.raw_pub, unb64url(key.sign(signed), 64), signed)
    assert mac.ACME_TXT_PREFIX == rc_crypto.ACME_TXT_PREFIX == b"carnivore-relay-acme-txt-v1\x00"


def test_acme_message_tampering_fails_the_control_plane_verifier(key):
    nonce, ts = bytes(16), 1_790_000_000
    sig = unb64url(key.sign(mac.acme_txt_message(key.device_id, ts, nonce, "set", VALUE)), 64)
    for tampered in (
        rc_crypto.acme_txt_message(key.device_id, ts, nonce, "clear", VALUE),
        rc_crypto.acme_txt_message(key.device_id, ts, nonce, "set", "B" * 43),
        rc_crypto.acme_txt_message(key.device_id, ts + 1, nonce, "set", VALUE),
        rc_crypto.acme_txt_message(key.device_id, ts, bytes(15) + b"\x01", "set", VALUE),
        rc_crypto.acme_txt_message("b" * 26, ts, nonce, "set", VALUE),
        rc_crypto.token_message(key.device_id, ts, nonce),
    ):
        assert not rc_crypto.verify_ed25519(key.raw_pub, sig, tampered)
