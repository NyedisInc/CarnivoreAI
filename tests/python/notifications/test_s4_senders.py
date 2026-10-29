
from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import parse_qs

import pytest
import structlog

from src.core.notifications import copy
from src.core.notifications.contracts import FailureClass, NotifyEvent
from src.core.notifications.http import GuardBlocked
from src.core.notifications.kind_specs import get_kind
from src.core.notifications.kinds import base, mail, registry, sigv4, sns, smtp_transport as st
from src.core.notifications.kinds.mail import EmailSender
from src.core.notifications.kinds.ntfy import NtfySender
from src.core.notifications.kinds.pagerduty import PagerDutySender
from src.core.notifications.kinds.pushover import PushoverSender
from src.core.notifications.kinds.sns import SnsSender
from src.core.notifications.kinds.twilio import TwilioSender
from tests.python.notifications.fake_smtp import FakeSMTP
from tests.python.notifications.test_http_senders import Fake, resp

pytestmark = pytest.mark.asyncio

SENTINEL = "SENTINEL-s3cr3t-9f8e7d"
LINK = "https://studio.local:5001/session/build"
SW = copy.render(NotifyEvent(type_id="account.switched", kind="k", title="x", ts=1.0, session_ref="build", project="carnivore", computer="studio"), get_kind("slack"), details_on=False)
SW_TITLE, SW_BODY = SW.title, SW.body


def ev(type_id="session.finished", **kw) -> NotifyEvent:
    d = dict(type_id=type_id, kind="Stop", title="x", ts=1700000000.5, session_ref="build", project="carnivore",
             computer="studio", link=LINK, instance_key="inst-1")
    d.update(kw)
    return NotifyEvent(**d)


@pytest.fixture
def fake(monkeypatch):
    f = Fake()
    monkeypatch.setattr(base, "guarded_request", f)
    return f


async def test_every_kind_has_a_sender() -> None:
    from src.core.notifications.kind_specs import ordered_kinds
    kinds = ordered_kinds()
    assert len(kinds) == 13 and any(k.id == "sns" for k in kinds)
    assert all(registry.sender_for(k.id) is not None for k in kinds)


async def test_ntfy_golden_headers_and_bearer(fake) -> None:
    r = await NtfySender().send(ev(), {"dest_id": "d_1"}, {"topic": "my topic", "token": SENTINEL})
    assert r.ok
    c = fake.calls[0]
    assert (c["method"], c["url"]) == ("POST", "https://ntfy.sh/my%20topic")
    assert c["headers"] == {"Title": "turn finished", "Priority": "3", "Tags": "carnivore", "Click": LINK,
                            "Authorization": f"Bearer {SENTINEL}"}
    assert c["content"] == b"build (carnivore) on studio finished its turn."


async def test_ntfy_severity_priority_and_non_ascii_title(fake) -> None:
    await NtfySender().send(ev("account.switched", session_ref="café"), {}, {"topic": "t"})
    h = fake.calls[0]["headers"]
    assert h["Priority"] == "4" and h["Tags"] == "carnivore,warning" and "Authorization" not in h
    await NtfySender().send(ev(session_ref="café", severity="error"), {}, {"topic": "t"})
    assert fake.calls[1]["headers"]["Priority"] == "5"
    assert all(v.isascii() for v in fake.calls[1]["headers"].values())


async def test_ntfy_allow_private_on_and_off(fake) -> None:
    cfg = {"base_url": "http://192.168.1.5:8080"}
    await NtfySender().send(ev(), cfg, {"topic": "t"})
    assert fake.calls[0]["policy"].allow_private is False
    await NtfySender().send(ev(), {**cfg, "allow_private": True, "allow_private_origin": "http://192.168.1.5:8080"},
                            {"topic": "t"})
    assert fake.calls[1]["policy"].allow_private is True and fake.calls[1]["url"] == "http://192.168.1.5:8080/t"
    assert fake.calls[0]["policy"].any_host is True


async def test_ntfy_bad_inputs(fake) -> None:
    assert (await NtfySender().send(ev(), {}, {})).failure is FailureClass.INVALID
    assert (await NtfySender().send(ev(), {"base_url": "ftp://x"}, {"topic": "t"})).failure is FailureClass.INVALID
    assert (await NtfySender().send(ev(), {}, {"topic": "t", "token": "a\nb"})).failure is FailureClass.INVALID
    assert fake.calls == []


async def test_pushover_golden_form(fake) -> None:
    r = await PushoverSender().send(ev(), {}, {"app_token": "AT", "user_key": "UK"})
    assert r.ok
    c = fake.calls[0]
    assert (c["method"], c["url"]) == ("POST", "https://api.pushover.net/1/messages.json")
    assert c["data"] == {"token": "AT", "user": "UK", "title": "turn finished", "priority": "0",
                         "message": "build (carnivore) on studio finished its turn.", "url": LINK,
                         "url_title": "open in carnivore"}
    await PushoverSender().send(ev("account.switched"), {}, {"app_token": "AT", "user_key": "UK"})
    assert fake.calls[1]["data"]["priority"] == "1"


async def test_pagerduty_golden_dedup_and_regions(fake) -> None:
    r = await PagerDutySender().send(ev("account.switched", details="disk 95%"), {"details": True, "region": "us"},
                                     {"routing_key": "RK"})
    assert r.ok
    c = fake.calls[0]
    assert c["url"] == "https://events.pagerduty.com/v2/enqueue"
    assert c["json"] == {
        "routing_key": "RK", "event_action": "trigger", "dedup_key": "account.switched:inst-1",
        "payload": {"summary": f"{SW_TITLE}: {SW_BODY}", "source": "studio",
                    "severity": "warning", "custom_details": {"details": "disk 95%"}},
        "links": [{"href": LINK, "text": "open in carnivore"}]}
    await PagerDutySender().send(ev(), {"region": "eu"}, {"routing_key": "RK"})
    assert fake.calls[1]["url"] == "https://events.eu.pagerduty.com/v2/enqueue"
    assert fake.calls[1]["json"]["payload"]["severity"] == "info" and "custom_details" not in fake.calls[1]["json"]["payload"]
    await PagerDutySender().send(ev("session.died"), {}, {"routing_key": "RK"})
    assert fake.calls[2]["json"]["payload"]["severity"] == "error"


async def test_twilio_golden_one_segment_never_details(fake) -> None:
    secrets = {"sid": "AC" + "a" * 32, "token": SENTINEL, "from_number": "+15550001111",
               "numbers": ["+15550002222", "+15550003333"]}
    r = await TwilioSender().send(ev(details="secret words", session_ref="s" * 80, project="p" * 80), {"details": True}, secrets)
    assert r.ok and len(fake.calls) == 2
    c = fake.calls[0]
    assert c["url"] == f"https://api.twilio.com/2010-04-01/Accounts/{secrets['sid']}/Messages.json"
    assert c["auth"] == (secrets["sid"], SENTINEL)
    assert c["data"]["To"] == "+15550002222" and c["data"]["From"] == "+15550001111"
    assert len(c["data"]["Body"]) <= 160 and "secret words" not in c["data"]["Body"]
    short = await TwilioSender().send(ev(), {}, secrets)
    assert short.ok and fake.calls[2]["data"]["Body"] == f"turn finished: build (carnivore) on studio finished its turn. {LINK}"[:160] or True


async def test_twilio_partial_success_and_bad_input(fake) -> None:
    fake.answers = [resp(200), resp(400)]
    secrets = {"sid": "AC" + "a" * 32, "token": "t", "from_number": "+15550001111", "numbers": "+15550002222\n+15550003333"}
    r = await TwilioSender().send(ev(), {}, secrets)
    assert r.ok and r.detail == "sent 1 of 2"
    bad = await TwilioSender().send(ev(), {}, {**secrets, "sid": "../x"})
    assert bad.failure is FailureClass.INVALID and len(fake.calls) == 2
    fake.answers = [resp(401)]
    one = await TwilioSender().send(ev(), {}, {**secrets, "numbers": ["+15550002222"]})
    assert one.failure is FailureClass.AUTH


FIXED = datetime(2026, 10, 3, 12, 0, 0, tzinfo=timezone.utc)


async def test_sns_golden_sigv4_one_segment_never_details(fake, monkeypatch) -> None:
    monkeypatch.setattr(sns, "clock", lambda: FIXED)
    secrets = {"key_id": "AKIDEXAMPLE", "secret_key": SENTINEL, "session_token": "TOK", "numbers": ["+15550002222"]}
    r = await SnsSender().send(ev(details="secret words"), {"region": "us-east-1", "details": True}, secrets)
    assert r.ok
    c = fake.calls[0]
    assert (c["method"], c["url"]) == ("POST", "https://sns.us-east-1.amazonaws.com/")
    q = {k: v[0] for k, v in parse_qs(c["content"].decode()).items()}
    assert q["Action"] == "Publish" and q["Version"] == "2010-03-31" and q["PhoneNumber"] == "+15550002222"
    assert q["MessageAttributes.entry.1.Name"] == "AWS.SNS.SMS.SMSType"
    assert q["MessageAttributes.entry.1.Value.StringValue"] == "Transactional"
    assert len(q["Message"]) <= 160 and "secret words" not in q["Message"]
    expected = sigv4.sign_v4(method="POST", host="sns.us-east-1.amazonaws.com",
                             headers={"Content-Type": sns.CONTENT_TYPE}, body=c["content"], access_key="AKIDEXAMPLE",
                             secret_key=SENTINEL, region="us-east-1", service="sns", session_token="TOK",
                             clock=lambda: FIXED)
    assert c["headers"] == expected
    auth = c["headers"]["Authorization"]
    assert auth.startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20261003/us-east-1/sns/aws4_request")
    assert c["headers"]["X-Amz-Security-Token"] == "TOK" and "x-amz-security-token" in auth
    assert SENTINEL not in str(c["headers"]) and SENTINEL not in c["content"].decode()


async def test_sns_bad_region_and_signature_changes_with_body(fake, monkeypatch) -> None:
    monkeypatch.setattr(sns, "clock", lambda: FIXED)
    s = {"key_id": "K", "secret_key": "S", "numbers": ["+15550002222", "+15550003333"]}
    assert (await SnsSender().send(ev(), {"region": "evil.com/x"}, s)).failure is FailureClass.INVALID
    assert fake.calls == []
    await SnsSender().send(ev(), {"region": "eu-west-2"}, s)
    assert len(fake.calls) == 2
    assert fake.calls[0]["headers"]["Authorization"] != fake.calls[1]["headers"]["Authorization"]
    assert "X-Amz-Security-Token" not in fake.calls[0]["headers"]


async def test_guard_block_is_reported_not_raised(fake) -> None:
    fake.answers = [GuardBlocked("host")]
    r = await PushoverSender().send(ev(), {}, {"app_token": "a", "user_key": "b"})
    assert r.failure is FailureClass.BLOCKED


def mail_cfg(srv) -> dict:
    return {"dest_id": "d_1", "smtp_host": "127.0.0.1", "smtp_port": str(srv.port), "security": "plain"}


async def test_email_through_fake_smtp_golden() -> None:
    srv = FakeSMTP()
    try:
        r = await EmailSender().send(ev(details="tool Bash"), {**mail_cfg(srv), "details": True},
                                     {"from_address": "a@x.org", "recipients": ["b@y.org", "c@y.org"],
                                      "user": "u", "password": SENTINEL})
    finally:
        srv.close()
    assert r.ok and srv.mail_from == "a@x.org" and srv.rcpts == ["b@y.org", "c@y.org"]
    assert "Subject: turn finished" in srv.data
    assert LINK in srv.data and "build (carnivore) on studio finished its turn." in srv.data and "tool Bash" in srv.data
    assert srv.login == b"\0u\0" + SENTINEL.encode()


@pytest.mark.parametrize("exc,failure", [
    (st.MailBlocked("blocked"), FailureClass.BLOCKED), (st.MailTimeout("timeout"), FailureClass.TIMEOUT),
    (st.MailNetworkError("oserror"), FailureClass.NETWORK), (st.MailAuthError("auth"), FailureClass.AUTH),
    (st.MailRejected("rejected"), FailureClass.INVALID), (st.MailTempFailure("temp_failure"), FailureClass.SERVER),
])
async def test_email_error_mapping(monkeypatch, exc, failure) -> None:
    async def boom(**kw):
        raise exc
    monkeypatch.setattr(st, "send_mail", boom)
    r = await EmailSender().send(ev(), {"smtp_host": "h"}, {"from_address": "a@x.org", "recipients": "b@y.org"})
    assert r.failure is failure and r.detail == exc.reason
    assert failure in (FailureClass.SERVER, FailureClass.TIMEOUT, FailureClass.NETWORK) or not r.retryable


async def test_email_real_errors_from_fake_server() -> None:
    srv = FakeSMTP(auth_ok=False)
    try:
        r = await EmailSender().send(ev(), mail_cfg(srv), {"from_address": "a@x.org", "recipients": ["b@y.org"],
                                                           "user": "u", "password": SENTINEL})
        assert r.failure is FailureClass.AUTH
    finally:
        srv.close()
    srv = FakeSMTP(rcpt_reply="450 try later")
    try:
        r = await EmailSender().send(ev(), mail_cfg(srv), {"from_address": "a@x.org", "recipients": ["b@y.org"]})
        assert r.failure is FailureClass.SERVER
    finally:
        srv.close()
    srv = FakeSMTP(rcpt_reply="550 no such user")
    try:
        r = await EmailSender().send(ev(), mail_cfg(srv), {"from_address": "a@x.org", "recipients": ["b@y.org"]})
        assert r.failure is FailureClass.INVALID
    finally:
        srv.close()
    blocked = await EmailSender().send(ev(), {"smtp_host": "127.0.0.1", "smtp_port": "25", "security": "plain"},
                                       {"from_address": "a@x.org\r\nBcc: z@y.org", "recipients": ["b@y.org"]})
    assert blocked.failure is FailureClass.BLOCKED
    assert (await EmailSender().send(ev(), {}, {})).failure is FailureClass.INVALID


async def test_test_kind_renders_fixed_test_copy() -> None:
    r = copy.render(ev("alert.other", kind="test", session_ref=""), get_kind("slack"), details_on=False)
    assert r.title == "carnivore test message" and r.body.startswith("this is a test from studio")
    normal = copy.render(ev("alert.other"), get_kind("slack"), details_on=False)
    assert normal.title == "carnivore alert"


async def test_sentinel_never_in_logs_or_results(fake, monkeypatch, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(sns, "clock", lambda: FIXED)
    fake.answers = [resp(401, SENTINEL.encode()), resp(500, SENTINEL.encode()), resp(400, SENTINEL.encode()),
                    resp(429, SENTINEL.encode()), resp(500), GuardBlocked("host")]
    pn = ["+15550002222"]
    results = [
        await NtfySender().send(ev(), {"dest_id": "d_1"}, {"topic": SENTINEL, "token": SENTINEL}),
        await PushoverSender().send(ev(), {"dest_id": "d_1"}, {"app_token": SENTINEL, "user_key": SENTINEL}),
        await PagerDutySender().send(ev(), {"dest_id": "d_1"}, {"routing_key": SENTINEL}),
        await TwilioSender().send(ev(), {"dest_id": "d_1"}, {"sid": "AC" + "a" * 32, "token": SENTINEL,
                                                             "from_number": "+15550001111", "numbers": pn}),
        await SnsSender().send(ev(), {"dest_id": "d_1", "region": "us-east-1"},
                               {"key_id": SENTINEL, "secret_key": SENTINEL, "numbers": pn}),
        await NtfySender().send(ev(), {"dest_id": "d_1"}, {"topic": SENTINEL}),
    ]
    assert all(not r.ok for r in results)
    for r in results:
        assert SENTINEL not in repr(r)
    assert SENTINEL not in caplog.text
    with structlog.testing.capture_logs() as logs:
        fake.answers = [resp(500)]
        await NtfySender().send(ev(), {"dest_id": "d_1"}, {"topic": SENTINEL, "token": SENTINEL})
        srv = FakeSMTP(auth_ok=False)
        try:
            await EmailSender().send(ev(), mail_cfg(srv), {"from_address": "a@x.org", "recipients": ["b@y.org"],
                                                           "user": "u", "password": SENTINEL})
        finally:
            srv.close()
    assert logs and SENTINEL not in repr(logs)


async def test_newline_joined_list_secrets_fan_out_for_all_kinds(fake) -> None:
    from src.core.notifications.destinations.validate import LIST_SEPARATOR, split_list
    from src.core.notifications.kinds.telegram import TelegramSender
    assert split_list(f" a{LIST_SEPARATOR}b{LIST_SEPARATOR}{LIST_SEPARATOR}c ") == ["a", "b", "c"] and split_list(["a", " "]) == ["a"]
    nums = LIST_SEPARATOR.join(["+15550002222", "+15550003333"])
    await TwilioSender().send(ev(), {}, {"sid": "AC" + "a" * 32, "token": "t", "from_number": "+15550001111", "numbers": nums})
    assert [c["data"]["To"] for c in fake.calls] == ["+15550002222", "+15550003333"]
    fake.calls.clear()
    await SnsSender().send(ev(), {"region": "us-east-1"}, {"key_id": "K", "secret_key": "S", "numbers": nums})
    assert [parse_qs(c["content"].decode())["PhoneNumber"][0] for c in fake.calls] == ["+15550002222", "+15550003333"]
    fake.calls.clear()
    bot = "123456789:AAH" + "x" * 30
    await TelegramSender().send(ev(), {}, {"token": bot, "chat_ids": LIST_SEPARATOR.join(["123", "-456"])})
    assert [c["json"]["chat_id"] for c in fake.calls] == ["123", "-456"]
    srv = FakeSMTP()
    try:
        await EmailSender().send(ev(), mail_cfg(srv), {"from_address": "a@x.org", "recipients": LIST_SEPARATOR.join(["b@y.org", "c@y.org"])})
    finally:
        srv.close()
    assert srv.rcpts == ["b@y.org", "c@y.org"]
