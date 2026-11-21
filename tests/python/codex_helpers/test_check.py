
from __future__ import annotations

import functools
import time

from src.core.codex_helpers import constants as K
from src.core.codex_helpers.check import identity_of, judge, run_check
from src.core.codex_helpers.handshake import HandshakeResult, judge_reply, probe_host
from src.core.codex_helpers.quarantine import HelperFlag, parse_flag, read_flag
from tests.python.codex_helpers import fakes

FAST = functools.partial(probe_host, timeout=1.5)


@fakes.needs_xattr
def test_flags_0381_unapproved_03c1_approved_and_absent(tmp_path):
    codex = fakes.make_install(tmp_path)
    host = codex.parent / K.HOST_NAME
    fakes.quarantine(host, fakes.UNAPPROVED)
    fakes.quarantine(codex, fakes.APPROVED)
    blocked, fine = read_flag(host.name, str(host)), read_flag("codex", str(codex))
    assert (blocked.raw, blocked.approved, blocked.unapproved) == ("0381", False, True)
    assert (fine.raw, fine.approved, fine.unapproved) == ("03c1", True, False)
    clean = read_flag("codex-exec-server", str(codex.parent / "codex-exec-server"))
    assert (clean.raw, clean.approved, clean.unapproved, clean.readable) == (None, None, False, True)
    assert parse_flag("0381;x") & K.FLAG_USER_APPROVED == 0 and parse_flag("03c1;x") & K.FLAG_USER_APPROVED


@fakes.needs_xattr
def test_an_answering_host_is_ok_even_with_a_0381_helper(tmp_path):
    codex = fakes.make_install(tmp_path, host="answers")
    fakes.quarantine(codex.parent / "codex-exec-server", fakes.UNAPPROVED)
    check = run_check(identity_of(str(codex)), "0.170.0", prober=FAST)
    assert check.verdict == K.OK and not check.failing
    assert check.handshake.outcome == K.HS_READY
    assert check.unapproved_names() == ["codex-exec-server"]


@fakes.needs_xattr
def test_a_hanging_host_with_0381_is_blocked_within_the_bound_and_its_child_is_killed(tmp_path):
    codex = fakes.make_install(tmp_path, host="hangs")
    fakes.quarantine(codex.parent / K.HOST_NAME, fakes.UNAPPROVED)
    started = time.monotonic()
    check = run_check(identity_of(str(codex)), "0.170.0", prober=FAST)
    assert time.monotonic() - started < 5
    assert check.verdict == K.BLOCKED and check.failing
    assert check.handshake.outcome == K.HS_TIMEOUT
    assert check.unapproved_names() == [K.HOST_NAME]
    assert not fakes.is_alive(fakes.host_pid(codex))


@fakes.needs_xattr
def test_a_hanging_host_with_only_approved_flags_is_host_failed(tmp_path):
    codex = fakes.make_install(tmp_path, host="hangs")
    fakes.quarantine(codex.parent / K.HOST_NAME, fakes.APPROVED)
    check = run_check(identity_of(str(codex)), "0.170.0", prober=FAST)
    assert check.verdict == K.HOST_FAILED and check.unapproved_names() == []


def test_no_host_is_not_applicable_and_nothing_is_spawned(tmp_path):
    codex = fakes.make_install(tmp_path, host=None)
    calls = []
    check = run_check(identity_of(str(codex)), "0.160.0", reader=lambda p: None,
                      prober=lambda p: calls.append(p) or HandshakeResult(K.HS_READY, 1))
    assert check.verdict == K.NOT_APPLICABLE and calls == []


def test_the_verdict_table_and_reply_judging_are_pure():
    bad = HelperFlag("h", "/h", "0381", False)
    timeout, ready = HandshakeResult(K.HS_TIMEOUT, 5000), HandshakeResult(K.HS_READY, 3)
    assert judge([bad], timeout) == K.BLOCKED
    assert judge([bad], ready) == K.OK
    assert judge([HelperFlag("h", "/h", "03c1", True)], timeout) == K.HOST_FAILED
    assert judge([], None) == K.NOT_APPLICABLE
    import json
    import struct
    body = json.dumps({"type": "connection/ready"}).encode()
    assert judge_reply(struct.pack("<I", len(body)) + body) == K.HS_READY
    assert judge_reply(struct.pack("<I", len(body)) + body[:3]) is None
    other = json.dumps({"type": "error"}).encode()
    assert judge_reply(struct.pack("<I", len(other)) + other) == K.HS_BAD_REPLY
