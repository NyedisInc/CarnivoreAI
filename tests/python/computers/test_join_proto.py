
from __future__ import annotations

import subprocess
import sys

import pytest

from src.core.computers import invites as inv_mod
from src.core.computers import join_proto as jp

FID_J = "joinerfidjoinerfidjoinerfid"
MAIN_OBJ = {"install_id": "inst-main", "fid": "mainfidmainfidmainfidmainf"}
CERT = b"main-cert-der"


def run(pw_j: bytes, pw_m: bytes, *, fps_j: bytes = None, mode="code", invite_id=""):
    a, b = jp.JoinPake("joiner", pw_j), jp.JoinPake("main", pw_m)
    msg_a, msg_b = a.start(), b.start()
    k_b, k_a = b.finish(msg_a), a.finish(msg_b)
    common = dict(mode=mode, invite_id=invite_id, msg_a=msg_a, msg_b=msg_b, join_id="ab" * 8, joiner_fid=FID_J)
    t_j = jp.transcript(fps=fps_j or jp.fp_server(CERT), **common)
    t_m = jp.transcript(fps=jp.fp_server(CERT), **common)
    return jp.JoinKeys(k_a, t_j), jp.JoinKeys(k_b, t_m)


def test_right_code_gives_same_keys_and_wrong_code_fails_mac_j():
    kj, km = run(jp.password("code", code="123456"), jp.password("code", code="123456"))
    assert km.equal(kj.mac_j(), km.mac_j())
    assert km.equal(km.mac_m(MAIN_OBJ), kj.mac_m(MAIN_OBJ))
    body = {"t": "identity", "install_id": "i", "label": "x", "public_key": "p", "fid": "f", "grant_id": "g",
            "cert_der": "c", "protocol": 1, "sig": "s"}
    msg = jp.sign_identity(body, kj, "J")
    assert jp.check_identity(msg, km, "J")["grant_id"] == "g"
    bad_j, bad_m = run(jp.password("code", code="123456"), jp.password("code", code="654321"))
    assert not bad_m.equal(bad_j.mac_j(), bad_m.mac_j())


def test_invite_mode_and_password_validation():
    secret = b"s" * 20
    kj, km = run(jp.password("invite", secret=secret), jp.password("invite", secret=secret),
                 mode="invite", invite_id="abcd1234")
    assert km.equal(kj.mac_j(), km.mac_j())
    for bad in ("12345", "12345a", "１２３４５６"):
        with pytest.raises(jp.ProtoError):
            jp.password("code", code=bad)


def test_different_cert_fingerprint_fails_mac_m():
    kj, km = run(jp.password("code", code="111111"), jp.password("code", code="111111"),
                 fps_j=jp.fp_server(b"mitm-cert"))
    assert not km.equal(kj.mac_m(MAIN_OBJ), km.mac_m(MAIN_OBJ))


def test_tampered_main_object_fails_mac_m_and_tampered_identity_fails():
    kj, km = run(jp.password("code", code="222222"), jp.password("code", code="222222"))
    mac = km.mac_m(MAIN_OBJ)
    assert not kj.equal(mac, kj.mac_m({**MAIN_OBJ, "fid": "other"}))
    body = {"install_id": "i", "label": "x", "public_key": "p", "fid": "f", "grant_id": "g",
            "cert_der": "c", "protocol": 1, "sig": "s"}
    msg = jp.sign_identity(body, km, "M")
    msg["fid"] = "evil"
    with pytest.raises(jp.ProtoError):
        jp.check_identity(msg, kj, "M")


def test_framing_and_validators():
    assert jp.encode_message(jp.done())[:4] == b"\x00\x00\x00\x0c"
    assert jp.parse_message(b'{"t":"done"}') == {"t": "done"}
    for junk in (b"GET / HTTP/1.1", b"[1]", b'{"x":1}'):
        with pytest.raises(jp.ProtoError):
            jp.parse_message(junk)
    with pytest.raises(jp.ProtoError):
        jp.encode_message({"t": "x", "p": "a" * jp.MAX_MESSAGE})
    ok = jp.check_hello(jp.hello(mode="invite", msg_a=b"x" * 33, fid="f", invite_id="ab12"))
    assert ok["msg_a"] == b"x" * 33
    with pytest.raises(jp.ProtoError):
        jp.check_hello(jp.hello(mode="invite", msg_a=b"x", fid="f"))
    with pytest.raises(jp.ProtoError):
        jp.check_spake({"t": "spake", "msg": "AA==", "join_id": "zz" * 8})
    with pytest.raises(jp.ProtoError):
        jp.check_confirm({"t": "confirm", "mac": "AA==", "main": {"install_id": "i", "fid": "f", "x": 1}},
                         from_main=True)
    with pytest.raises(jp.ProtoError):
        jp.error("because")


def test_importing_join_proto_does_not_import_spake2():
    code = "import sys, src.core.computers.join_proto as j; sys.exit(1 if 'spake2' in sys.modules else 0)"
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_code_retirement_expiry_and_attempts():
    clock, changes = Clock(), []
    iv = inv_mod.Invites(clock=clock, on_change=lambda: changes.append(1))
    first = iv.mint()
    second = iv.mint()
    assert first.code is None and second.code and len(second.code) == 6
    assert iv.take_attempt("code") is second and second.attempts_left == 2
    assert iv.take_attempt("invite", first.id) is first
    assert iv.take_attempt("invite", "nope") is None
    assert inv_mod.secret_from_link(second.link_secret) == second.secret
    assert iv.finish_attempt(second, ok=False, mode="code", addr="1.2.3.4") == 2
    for _ in range(2):
        inv = iv.take_attempt("code")
        left = iv.finish_attempt(inv, ok=False, mode="code", addr="1.2.3.4")
    assert left == 0 and second not in iv.live() and iv.take_attempt("code") is None
    clock.now += inv_mod.INVITE_LIFE_S + 1
    assert iv.sweep() and not iv.any_live()
    assert changes


def test_success_deletes_and_four_live_cap():
    iv = inv_mod.Invites(clock=Clock())
    ok = iv.mint()
    iv.take_attempt("code")
    iv.finish_attempt(ok, ok=True, mode="code")
    assert not iv.any_live()
    jobs = [iv.mint("ssh_add", f"j{i}") for i in range(4)]
    assert all(j.code is None for j in jobs)
    with pytest.raises(inv_mod.TooManyInvites):
        iv.mint()
    assert iv.cancel_job("j0") == 1
    iv.mint()
    assert len(iv.live()) == 4


def test_ten_wrong_codes_in_an_hour_pause_code_mode():
    clock, notices = Clock(), []
    iv = inv_mod.Invites(clock=clock, on_notice=lambda e, a: notices.append((e, a)))
    for _ in range(4):
        inv = iv.mint()
        for _ in range(3 if len(notices) < 3 else 1):
            got = iv.take_attempt("code")
            if got is None:
                break
            iv.finish_attempt(got, ok=False, mode="code", addr="198.51.100.14")
        if iv.code_paused():
            break
    assert iv.code_paused() and ("paused", "198.51.100.14") in notices and ("burned", "198.51.100.14") in notices
    assert iv.mint().code is None and iv.take_attempt("code") is None
    clock.now += inv_mod.CODE_PAUSE_S + 1
    assert iv.mint().code is not None
