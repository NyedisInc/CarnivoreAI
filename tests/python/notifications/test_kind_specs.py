
from __future__ import annotations

import re

from src.core.notifications import kind_specs as K


def test_thirteen_kinds_with_the_plan_flags() -> None:
    ids = [k.id for k in K.KINDS]
    assert ids == ["slack", "discord", "teams", "telegram", "ntfy", "pushover", "webhook", "email", "sns",
                   "twilio", "pagerduty", "webpush", "apns"]
    assert {k.id for k in K.KINDS if k.allow_private} == {"webhook", "ntfy"}
    assert {k.id for k in K.KINDS if k.sms_like} == {"sns", "twilio"}
    assert {k.id for k in K.KINDS if not k.details_allowed} == {"sns", "twilio", "webpush", "apns"}
    assert [k.id for k in K.KINDS if k.virtual] == ["webpush", "apns"]
    assert K.get_kind("slack").label_key == "notify.kind.slack" and K.get_kind("zzz") is None


def test_recipients_and_credentials_are_secret_fields() -> None:
    secret = {k.id: {f.name for f in k.secret_fields} for k in K.KINDS}
    assert secret["telegram"] == {"token", "chat_ids"}
    assert {"recipients", "password"} <= secret["email"]
    assert {"numbers"} <= secret["sns"] and {"numbers", "from_number", "token"} <= secret["twilio"]
    assert secret["webhook"] >= {"url", "signing_secret", "header_value"}
    for kind in K.KINDS:
        assert all(f.secret for f in kind.secret_fields) and not any(f.secret for f in kind.public_fields)
        assert not {f.name for f in kind.public_fields} & {f.name for f in kind.secret_fields}


def test_host_rules_are_plain_data() -> None:
    assert K.get_kind("slack").hosts.exact_hosts == ("hooks.slack.com", "hooks.slack-gov.com")
    assert K.get_kind("teams").hosts.suffixes == (".logic.azure.com", ".api.powerplatform.com")
    assert re.fullmatch(K.get_kind("sns").hosts.regex, "sns.us-east-1.amazonaws.com")
    assert not re.fullmatch(K.get_kind("sns").hosts.regex, "sns.us-east-1.amazonaws.com.evil.test")
    assert K.get_kind("webhook").hosts.any_host and K.get_kind("ntfy").hosts.any_host
    assert not K.get_kind("pushover").hosts.any_host


def test_destination_ids() -> None:
    new = K.new_destination_id()
    assert K.DEST_ID_RE.match(new) and K.is_destination_id(new) and new != K.new_destination_id()
    assert K.is_destination_id("d_0123456789ab")
    for bad in ("d_0123456789AB", "d_0123456789a", "d_0123456789abc", "x_0123456789ab", "webpush:1", None, 5):
        assert not K.is_destination_id(bad), bad
    assert K.webpush_destination_id("42") == "webpush:42"
    assert K.is_webpush_destination_id("webpush:42") and not K.is_webpush_destination_id("webpush:")
    assert K.apns_destination_id("d_0123456789ab") == "apns:d_0123456789ab"
    assert K.is_apns_destination_id("apns:d_0123456789ab") and not K.is_apns_destination_id("apns:")
    assert K.is_push_destination_id("apns:x") and K.is_push_destination_id("webpush:x") and not K.is_push_destination_id("d_0123456789ab")
    assert K.virtual_kind_of("apns:x") == "apns" and K.virtual_kind_of("webpush:x") == "webpush" and K.virtual_kind_of("x") is None


def test_destination_id_rejects_a_trailing_newline():
    assert K.is_destination_id("d_0123456789ab") and K.DEST_ID_RE.match("d_0123456789ab")
    assert not K.is_destination_id("d_0123456789ab\n") and not K.DEST_ID_RE.match("d_0123456789ab\n")
