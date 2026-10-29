
from __future__ import annotations

import ssl
import smtplib

import pytest
import structlog

from src.core.notifications.kinds import smtp_transport as st
from src.core.notifications.kinds.smtp_transport import (
    MailAuthError, MailBlocked, MailNetworkError, MailRejected, MailTempFailure, send_mail,
)
from tests.python.notifications.fake_smtp import FakeSMTP, make_cert

SENTINEL = "s3ntinel-pw-Zq9"


def resolver_to(*addrs):
    calls = []

    async def r(host, port):
        calls.append(host)
        return list(addrs)

    r.calls = calls
    return r


def kw(srv_port, **over):
    base = dict(host="127.0.0.1", port=srv_port, security="plain", sender="a@example.net",
                recipients=["b@example.net"], subject="approval needed", body="body text", dest_id="d1",
                timeout=5.0)
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_plain_to_loopback_delivers_envelope():
    srv = FakeSMTP()
    try:
        await send_mail(**kw(srv.port, recipients=["b@example.net", "c@example.net"], username="u", password=SENTINEL))
    finally:
        srv.close()
    assert srv.mail_from == "a@example.net"
    assert srv.rcpts == ["b@example.net", "c@example.net"]
    assert "Subject: approval needed" in srv.data and "body text" in srv.data
    assert srv.login == b"\0u\0" + SENTINEL.encode()


@pytest.mark.asyncio
async def test_plain_to_non_loopback_refused_before_connect():
    srv = FakeSMTP()
    r = resolver_to("93.184.216.34")
    try:
        with pytest.raises(MailBlocked) as e:
            await send_mail(**kw(srv.port, host="mail.example.com", resolver=r))
    finally:
        srv.close()
    assert e.value.reason == "plain_not_loopback" and srv.connections == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("addr", ["192.0.2.13", "192.0.2.15", "169.254.169.254", "0.0.0.0", "224.0.0.1",
                                  "fe80::1", "::ffff:203.0.113.16"])
async def test_non_global_non_loopback_refused(addr):
    srv = FakeSMTP()
    try:
        with pytest.raises(MailBlocked) as e:
            await send_mail(**kw(srv.port, host="mail.example.com", security="starttls",
                                 resolver=resolver_to(addr)))
    finally:
        srv.close()
    assert e.value.reason == "address" and srv.connections == 0


@pytest.mark.asyncio
async def test_every_address_is_checked_not_just_the_first():
    with pytest.raises(MailBlocked):
        await send_mail(**kw(1, host="m.example.com", security="starttls",
                             resolver=resolver_to("93.184.216.34", "203.0.113.16")))


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("subject", "a\r\nBcc: x@example.net"), ("subject", "a\nb"),
                                         ("sender", "a@example.net\r\nBcc: z"), ("recipients", ["b@example.net\nX: 1"]),
                                         ("recipients", [])])
async def test_header_injection_and_empty_refused(field, value):
    srv = FakeSMTP()
    try:
        with pytest.raises(MailBlocked):
            await send_mail(**kw(srv.port, **{field: value}))
    finally:
        srv.close()
    assert srv.connections == 0


@pytest.mark.asyncio
async def test_recipient_cap():
    srv = FakeSMTP()
    try:
        await send_mail(**kw(srv.port, recipients=[f"r{i}@example.net" for i in range(10)]))
        with pytest.raises(MailBlocked) as e:
            await send_mail(**kw(srv.port, recipients=[f"r{i}@example.net" for i in range(11)]))
    finally:
        srv.close()
    assert e.value.reason == "recipients" and len(srv.rcpts) == 10


@pytest.mark.asyncio
async def test_error_mapping():
    for srv_kw, exc in [(dict(auth_ok=False), MailAuthError), (dict(rcpt_reply="451 try later"), MailTempFailure),
                        (dict(rcpt_reply="550 no such user"), MailRejected)]:
        srv = FakeSMTP(**srv_kw)
        try:
            with pytest.raises(exc):
                await send_mail(**kw(srv.port, username="u", password=SENTINEL))
        finally:
            srv.close()


@pytest.mark.asyncio
async def test_connection_refused_is_network_error():
    srv = FakeSMTP()
    port = srv.port
    srv.close()
    with pytest.raises(MailNetworkError):
        await send_mail(**kw(port))


def client_ctx(cert):
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(str(cert[0]))
    return ctx


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["starttls", "tls"])
async def test_tls_pins_ip_and_verifies_hostname(tmp_path, mode):
    cert = make_cert(tmp_path, "mail.test.invalid")
    srv = FakeSMTP(cert=cert, implicit_tls=(mode == "tls"), offer_starttls=(mode == "starttls"))
    r = resolver_to("127.0.0.1")
    try:
        await send_mail(**kw(srv.port, host="mail.test.invalid", security=mode, resolver=r,
                             ssl_context=client_ctx(cert)))
        assert srv.rcpts == ["b@example.net"] and r.calls == ["mail.test.invalid"]
        with pytest.raises(MailNetworkError):
            await send_mail(**kw(srv.port, host="other.test.invalid", security=mode, resolver=r,
                                 ssl_context=client_ctx(cert)))
    finally:
        srv.close()
    assert len(srv.rcpts) == 1


@pytest.mark.asyncio
async def test_untrusted_certificate_refused(tmp_path):
    cert = make_cert(tmp_path, "mail.test.invalid")
    srv = FakeSMTP(cert=cert, implicit_tls=True)
    try:
        with pytest.raises(MailNetworkError):
            await send_mail(**kw(srv.port, host="mail.test.invalid", security="tls",
                                 resolver=resolver_to("127.0.0.1")))
    finally:
        srv.close()
    assert srv.rcpts == []


@pytest.mark.asyncio
async def test_password_never_in_logs_or_exceptions(capsys):
    structlog.configure(processors=[structlog.processors.KeyValueRenderer()],
                        logger_factory=structlog.PrintLoggerFactory())
    extra = dict(username="secretuser", password=SENTINEL, recipients=["private@example.net"], subject="private subject")
    ok = FakeSMTP()
    bad = FakeSMTP(auth_ok=False)
    try:
        await send_mail(**kw(ok.port, **extra))
        with pytest.raises(MailAuthError) as e:
            await send_mail(**kw(bad.port, **extra))
    finally:
        ok.close()
        bad.close()
    out = capsys.readouterr()
    text = out.out + out.err + str(e.value) + repr(e.value) + str(e.value.__cause__)
    assert "smtp." in out.out + out.err
    for secret in (SENTINEL, "secretuser", "private@example.net", "private subject"):
        assert secret not in text
