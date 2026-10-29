
from __future__ import annotations

import hashlib
import hmac
import json
import logging

import pytest
import structlog

from src.core.notifications import contracts
from src.core.notifications.contracts import FailureClass, NotifyEvent
from src.core.notifications.http import GuardBlocked, GuardNetworkError, GuardResponse, GuardTimeout
from src.core.notifications.kind_specs import get_kind
from src.core.notifications.kinds import base, registry
from src.core.notifications.kinds.discord import DiscordSender
from src.core.notifications.kinds.slack import SlackSender
from src.core.notifications.kinds.teams import TeamsSender
from src.core.notifications.kinds.telegram import TelegramSender
from src.core.notifications.kinds.webhook import WebhookSender

pytestmark = pytest.mark.asyncio

SENTINEL = "SENTINEL-s3cr3t-9f8e7d"
BOT = "123456789:AAH" + "x" * 30 + SENTINEL[-4:]
LINK = "https://studio.local:5001/s/1"


def ev(type_id="session.finished", **kw) -> NotifyEvent:
    d = dict(type_id=type_id, kind="Stop", title="x", ts=1700000000.5, session_ref="build", project="carnivore",
             computer="studio", link=LINK, instance_key="inst-1")
    d.update(kw)
    return NotifyEvent(**d)


class Fake:

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    async def __call__(self, method, url, **kw):
        self.calls.append(dict(method=method, url=url, **kw))
        a = self.answers.pop(0) if self.answers else resp(200)
        if isinstance(a, Exception):
            raise a
        return a


def resp(status=200, body=b"", **headers) -> GuardResponse:
    return GuardResponse(status, {k.replace("_", "-"): v for k, v in headers.items()}, body, False)


@pytest.fixture
def fake(monkeypatch):
    f = Fake()
    monkeypatch.setattr(base, "guarded_request", f)
    return f


SLACK_URL = f"https://hooks.slack.com/services/T0/B0/{SENTINEL}"
DISCORD_URL = f"https://discord.com/api/webhooks/1/{SENTINEL}"
TEAMS_URL = f"https://prod-1.westus.logic.azure.com/workflows/w/triggers/manual/paths/invoke?sig={SENTINEL}"
HOOK_URL = f"https://hooks.example.com/in/{SENTINEL}"


async def test_slack_golden_and_escaping(fake) -> None:
    r = await SlackSender().send(ev(session_ref="a&b <c>", details="x < y & z"), {"details": True}, {"url": SLACK_URL})
    assert r.ok
    c = fake.calls[0]
    assert (c["method"], c["url"]) == ("POST", SLACK_URL) and c["json"] == {
        "text": "*turn finished*\na&amp;b &lt;c&gt; (carnivore) on studio finished its turn.\n"
                f"<{LINK}|open in carnivore>\nx &lt; y &amp; z",
        "unfurl_links": False, "unfurl_media": False}


async def test_discord_golden_mentions_and_embeds_off(fake) -> None:
    await DiscordSender().send(ev(session_ref="@everyone"), {}, {"url": DISCORD_URL})
    p = fake.calls[0]["json"]
    assert p == {"content": f"**turn finished**\n@everyone (carnivore) on studio finished its turn.\n{LINK}",
                 "allowed_mentions": {"parse": []}, "flags": 4}
    await DiscordSender().send(ev(details="d" * 190, session_ref="s" * 80), {"details": True}, {"url": DISCORD_URL})
    assert len(fake.calls[1]["json"]["content"]) <= 2000


async def test_teams_card_envelope(fake) -> None:
    await TeamsSender().send(ev(details="tool Bash"), {"details": True}, {"url": TEAMS_URL})
    p = fake.calls[0]["json"]
    assert p["type"] == "message" and len(p["attachments"]) == 1
    att = p["attachments"][0]
    assert att["contentType"] == "application/vnd.microsoft.card.adaptive" and att["contentUrl"] is None
    card = att["content"]
    assert card["type"] == "AdaptiveCard" and card["version"] == "1.2" and card["$schema"].endswith("adaptive-card.json")
    assert [b["type"] for b in card["body"]] == ["TextBlock"] * 3
    assert card["body"][0]["text"] == "turn finished" and card["body"][2]["text"] == "tool Bash"
    assert card["actions"] == [{"type": "Action.OpenUrl", "title": "open in carnivore", "url": LINK}]
    await TeamsSender().send(ev(link=None), {}, {"url": TEAMS_URL})
    assert "actions" not in fake.calls[1]["json"]["attachments"][0]["content"]


async def test_telegram_one_request_per_chat_golden(fake) -> None:
    r = await TelegramSender().send(ev(), {}, {"token": BOT, "chat_ids": ["111", "-100222", "@room_one"]})
    assert r.ok and len(fake.calls) == 3
    assert [c["json"]["chat_id"] for c in fake.calls] == ["111", "-100222", "@room_one"]
    c = fake.calls[0]
    assert c["url"] == f"https://api.telegram.org/bot{BOT}/sendMessage"
    assert c["json"] == {"chat_id": "111", "link_preview_options": {"is_disabled": True},
                         "text": f"turn finished\nbuild (carnivore) on studio finished its turn.\n{LINK}"}
    assert "parse_mode" not in c["json"]


async def test_telegram_text_capped_and_bad_inputs_never_reach_network(fake) -> None:
    await TelegramSender().send(ev(details="d" * 500), {"details": True}, {"token": BOT, "chat_ids": "5"})
    assert len(fake.calls[0]["json"]["text"]) <= 4096
    for secrets in ({"token": "bad/../token", "chat_ids": ["1"]}, {"token": BOT, "chat_ids": []},
                    {"token": BOT + "?x=1", "chat_ids": ["1"]}):
        assert (await TelegramSender().send(ev(), {}, secrets)).failure is FailureClass.INVALID
    assert len(fake.calls) == 1


async def test_telegram_partial_and_total_failure(fake) -> None:
    fake.answers = [resp(200), resp(403)]
    r = await TelegramSender().send(ev(), {}, {"token": BOT, "chat_ids": ["1", "2"]})
    assert r.ok and r.detail == "sent 1 of 2"
    fake.answers = [resp(403), resp(403)]
    r = await TelegramSender().send(ev(), {}, {"token": BOT, "chat_ids": ["1", "2"]})
    assert not r.ok and r.failure is FailureClass.GONE


async def test_webhook_signature_verified_over_sent_bytes_and_delivery_id_stable(fake) -> None:
    secrets = {"url": HOOK_URL, "signing_secret": "k3y", "header_value": "Bearer tok"}
    cfg = {"header_name": "Authorization", "dest_id": "d_0123456789ab", "details": True}
    event = ev("agent.message", details="deploy done")

    await WebhookSender().send(event, cfg, secrets)
    await WebhookSender().send(event, cfg, secrets)
    a, b = fake.calls
    sent = a["content"]
    assert a["headers"]["X-Carnivore-Signature"] == "sha256=" + hmac.new(b"k3y", sent, hashlib.sha256).hexdigest()
    assert json.loads(sent) == {"v": 1, "type": "agent.message", "title": "message from an agent",
                                "session": {"name": "build", "project": "carnivore"}, "computer": "studio",
                                "link": LINK, "ts": 1700000000.5, "details": "deploy done"}
    assert a["headers"]["X-Carnivore-Delivery"] == b["headers"]["X-Carnivore-Delivery"]
    assert len(a["headers"]["X-Carnivore-Delivery"]) == 32
    assert a["headers"]["Authorization"] == "Bearer tok" and a["json"] is None
    other = base.delivery_id(event, "d_ffffffffffff")
    assert other != a["headers"]["X-Carnivore-Delivery"] and base.delivery_id(ev(instance_key="inst-2"), "d_0123456789ab") != a["headers"]["X-Carnivore-Delivery"]


async def test_webhook_without_details_or_signing_and_bad_headers(fake) -> None:
    await WebhookSender().send(ev("agent.message", details="secret text"), {}, {"url": HOOK_URL})
    h = fake.calls[0]["headers"]
    assert "details" not in json.loads(fake.calls[0]["content"]) and "X-Carnivore-Signature" not in h
    for name in ("Content-Type", "X-Carnivore-Signature", "bad name"):
        r = await WebhookSender().send(ev(), {"header_name": name}, {"url": HOOK_URL, "header_value": "v"})
        assert r.failure is FailureClass.INVALID
    assert len(fake.calls) == 1


@pytest.mark.parametrize("sender,url", [(SlackSender, SLACK_URL), (DiscordSender, DISCORD_URL),
                                        (TeamsSender, TEAMS_URL), (WebhookSender, HOOK_URL)])
@pytest.mark.parametrize("answer,failure,retry", [
    (resp(200), None, None), (resp(204), None, None), (resp(202), None, None),
    (resp(429, retry_after="3"), FailureClass.RATE_LIMITED, 3.0),
    (resp(429, retry_after="999"), FailureClass.RATE_LIMITED, 20.0),
    (resp(429, b'{"retry_after": 1.5}'), FailureClass.RATE_LIMITED, 1.5),
    (resp(500), FailureClass.SERVER, None), (resp(503), FailureClass.SERVER, None),
    (resp(401), FailureClass.AUTH, None), (resp(403), FailureClass.AUTH, None),
    (resp(404), FailureClass.GONE, None), (resp(410), FailureClass.GONE, None),
    (resp(400), FailureClass.INVALID, None), (resp(422), FailureClass.INVALID, None),
    (GuardBlocked("redirect"), FailureClass.BLOCKED, None),
    (GuardTimeout("timeout"), FailureClass.TIMEOUT, None),
    (GuardNetworkError("dns"), FailureClass.NETWORK, None),
])
async def test_classification_table(fake, sender, url, answer, failure, retry) -> None:
    fake.answers = [answer]
    r = await sender().send(ev(), {}, {"url": url})
    assert r.ok is (failure is None) and r.failure is failure and r.retry_after == retry


async def test_telegram_classification_overrides(fake) -> None:
    for status, failure in ((403, FailureClass.GONE), (404, FailureClass.AUTH), (401, FailureClass.AUTH),
                            (400, FailureClass.INVALID)):
        fake.answers = [resp(status)]
        assert (await TelegramSender().send(ev(), {}, {"token": BOT, "chat_ids": ["1"]})).failure is failure
    fake.answers = [resp(429, b'{"ok":false,"parameters":{"retry_after":7}}')]
    r = await TelegramSender().send(ev(), {}, {"token": BOT, "chat_ids": ["1"]})
    assert r.failure is FailureClass.RATE_LIMITED and r.retry_after == 7.0


async def test_missing_url_is_invalid_not_raised(fake) -> None:
    for cls in (SlackSender, DiscordSender, TeamsSender, WebhookSender):
        assert (await cls().send(ev(), {}, {})).failure is FailureClass.INVALID
    assert fake.calls == []


async def test_discord_path_prefix_enforced_before_request(fake) -> None:
    r = await DiscordSender().send(ev(), {}, {"url": f"https://discord.com/evil/{SENTINEL}"})
    assert r.failure is FailureClass.BLOCKED and r.detail == "path" and fake.calls == []
    assert (await DiscordSender().send(ev(), {}, {"url": DISCORD_URL})).ok


async def test_policy_for_joins_host_rules_and_gates_allow_private() -> None:
    u = "https://hooks.example.com/x"
    ok = {"allow_private": True, "allow_private_origin": "https://hooks.example.com:443"}
    p = base.policy_for(get_kind("discord"), {}, u)
    assert "discord.com" in p.exact and not p.any_host and not p.allow_private and not p.switchable
    t = base.policy_for(get_kind("teams"), {}, u)
    assert ".logic.azure.com" in t.suffixes
    assert base.policy_for(get_kind("sns"), {}, u).pattern
    assert not base.policy_for(get_kind("webhook"), {}, u).allow_private
    assert not base.policy_for(get_kind("webhook"), {"allow_private": "yes"}, u).allow_private
    assert base.policy_for(get_kind("webhook"), ok, u).allow_private
    assert base.policy_for(get_kind("webhook"), {}, u).any_host and base.policy_for(get_kind("webhook"), {}, u).switchable
    assert not base.policy_for(get_kind("slack"), ok, u).allow_private
    assert not base.policy_for(get_kind("telegram"), ok, u).allow_private
    moved = base.policy_for(get_kind("webhook"), ok, "https://other.example.com/x")
    assert not moved.allow_private and moved.origin_changed
    assert not base.policy_for(get_kind("webhook"), {"allow_private": True}, u).allow_private


async def test_private_destination_reaches_the_real_guard_only_when_allowed(monkeypatch) -> None:
    from src.core.notifications import http

    async def resolver(host, port):
        return ["10.0.0.5"]

    seen = {}

    async def via_guard(method, url, **kw):
        seen["policy"] = kw["policy"]
        return await http.guarded_request(method, url, resolver=resolver, **kw)

    monkeypatch.setattr(base, "guarded_request", via_guard)
    r = await WebhookSender().send(ev(), {}, {"url": HOOK_URL})
    assert r.failure is FailureClass.PRIVATE_OFF and r.detail == "address" and not seen["policy"].allow_private


async def test_a_kind_without_the_switch_resolving_private_is_a_counted_refusal(monkeypatch) -> None:
    from src.core.notifications import http
    from src.core.notifications.contracts import NOT_COUNTED

    async def resolver(host, port):
        return ["10.1.1.1"]

    async def via_guard(method, url, **kw):
        return await http.guarded_request(method, url, resolver=resolver, **kw)

    monkeypatch.setattr(base, "guarded_request", via_guard)
    r = await base.post(get_kind("slack"), {}, "https://hooks.slack.com/services/T0/B0/abc", json_body={"text": "x"})
    assert r.failure is FailureClass.BLOCKED and r.failure not in NOT_COUNTED


async def test_a_moved_url_reaches_the_guard_as_origin_changed(monkeypatch) -> None:
    from src.core.notifications import http

    async def resolver(host, port):
        return ["10.0.0.5"]

    async def via_guard(method, url, **kw):
        return await http.guarded_request(method, url, resolver=resolver, **kw)

    monkeypatch.setattr(base, "guarded_request", via_guard)
    cfg = {"allow_private": True, "allow_private_origin": "https://old.lan:443"}
    r = await base.post(get_kind("webhook"), cfg, "https://new.lan/x", json_body={})
    assert r.failure is FailureClass.ORIGIN_CHANGED


async def test_no_secret_in_logs_results_or_exceptions(fake, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    secrets_by_sender = [
        (SlackSender, {"url": SLACK_URL}), (DiscordSender, {"url": DISCORD_URL}), (TeamsSender, {"url": TEAMS_URL}),
        (TelegramSender, {"token": BOT, "chat_ids": ["1"]}),
        (WebhookSender, {"url": HOOK_URL, "signing_secret": SENTINEL, "header_value": SENTINEL}),
    ]
    answers = [resp(200), resp(500, SENTINEL.encode()), resp(401, SENTINEL.encode()), resp(404),
               GuardBlocked("redirect"), GuardTimeout("timeout"), GuardNetworkError("dns")]
    out = []
    with structlog.testing.capture_logs() as logs:
        for cls, sec in secrets_by_sender:
            cfg = {"header_name": "X-Key"} if cls is WebhookSender else {}
            for a in answers:
                fake.answers = [a]
                r = await cls().send(ev(), cfg, sec)
                out.append(repr(r))
        r = await DiscordSender().send(ev(), {}, {"url": f"https://discord.com/x/{SENTINEL}"})
        out.append(repr(r))
    blob = "\n".join(out + [repr(logs), caplog.text])
    assert SENTINEL not in blob and BOT not in blob and "AAH" not in blob
    assert len(out) >= 36


async def test_registry_has_the_five_kinds_and_replaces() -> None:
    for kind, cls in (("slack", SlackSender), ("discord", DiscordSender), ("teams", TeamsSender),
                      ("telegram", TelegramSender), ("webhook", WebhookSender)):
        assert isinstance(registry.sender_for(kind), cls) and isinstance(registry.sender_for(kind), contracts.Sender)
    assert registry.sender_for("nope") is None
