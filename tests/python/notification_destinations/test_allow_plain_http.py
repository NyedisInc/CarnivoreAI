
from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")

from src.core import config_writer  # noqa: E402
from src.core.config_bundle import bundle  # noqa: E402
from src.core.notifications import kind_specs  # noqa: E402
from src.core.notifications.contracts import FailureClass  # noqa: E402
from src.core.notifications.destinations import validate  # noqa: E402
from src.core.notifications.http import GuardLocalPolicy  # noqa: E402
from src.core.notifications.kinds import base  # noqa: E402
from src.core.notifications.settings_doc import view  # noqa: E402

from .conftest import slack_body  # noqa: E402
from .test_allow_private import fields_of, webhook  # noqa: E402
from .test_settings_and_destinations import BASE, make_client  # noqa: E402

BOTH = {"allow_private": True, "allow_plain_http": True}


def test_http_is_accepted_for_webhook_and_ntfy_with_both_switches_on(service):
    client = make_client(service)
    made = client.post(f"{BASE}/destinations", json=webhook("http://203.0.113.13:5678/hook", **BOTH))
    assert made.status_code == 201, made.text
    got = made.json()["destination"]
    assert got["allow_private"] is True and got["allow_plain_http"] is True
    ntfy = {"kind": "ntfy", "name": "n", "config": {"base_url": "http://ntfy.lan:8080"}, "secrets": {"topic": "t"}, **BOTH}
    assert client.post(f"{BASE}/destinations", json=ntfy).status_code == 201


@pytest.mark.parametrize("over", [{}, {"allow_private": True}, {"allow_plain_http": True}])
def test_http_is_refused_unless_both_switches_are_on(service, over):
    got = fields_of(make_client(service).post(f"{BASE}/destinations", json=webhook("http://203.0.113.13/x", **over)))
    expected = {"allow_plain_http": validate.REQUIRES_PRIVATE} if over == {"allow_plain_http": True} else {"url": validate.HTTPS_REQUIRED}
    assert got == expected


def test_plain_switch_without_private_switch_is_refused_with_its_own_code(service):
    got = fields_of(make_client(service).post(f"{BASE}/destinations", json=webhook("https://example.com/x", allow_plain_http=True)))
    assert got == {"allow_plain_http": validate.REQUIRES_PRIVATE}


def test_literal_public_ip_over_http_is_refused_at_save_but_a_name_is_left_to_send_time(service):
    client = make_client(service)
    assert fields_of(client.post(f"{BASE}/destinations", json=webhook("http://93.184.216.34/x", **BOTH))) == {"url": validate.PLAIN_HTTP_PUBLIC}
    assert client.post(f"{BASE}/destinations", json=webhook("http://example.com/x", **BOTH)).status_code == 201


def test_link_local_over_http_stays_refused(service):
    got = fields_of(make_client(service).post(f"{BASE}/destinations", json=webhook("http://169.254.169.254/x", **BOTH)))
    assert got == {"url": validate.BAD_VALUE}


def test_other_kinds_refuse_http_and_the_field(service):
    client = make_client(service)
    got = fields_of(client.post(f"{BASE}/destinations", json=slack_body("http://hooks.slack.com/services/T0/B0/abc")))
    assert validate.HTTPS_REQUIRED in got.values()
    got = fields_of(client.post(f"{BASE}/destinations", json={**slack_body(), "allow_plain_http": True}))
    assert got == {"allow_plain_http": validate.NOT_SUPPORTED}


def test_patch_round_trip_and_turning_private_off_turns_plain_off(service):
    client = make_client(service)
    dest = client.post(f"{BASE}/destinations", json=webhook("http://203.0.113.13/x", **BOTH)).json()["destination"]["id"]
    assert client.patch(f"{BASE}/destinations/{dest}", json={"secrets": {"url": "http://192.0.2.19/y"}}).status_code == 200
    bad = client.patch(f"{BASE}/destinations/{dest}", json={"allow_private": False, "allow_plain_http": True})
    assert fields_of(bad) == {"allow_plain_http": validate.REQUIRES_PRIVATE}
    off = client.patch(f"{BASE}/destinations/{dest}", json={"allow_private": False}).json()["destination"]
    assert off["allow_private"] is False and off["allow_plain_http"] is False
    assert view.allow_plain_http_key(dest) not in service.docs.snapshot()["local"]


def test_the_policy_honors_the_switch_through_the_view(service):
    client = make_client(service)
    client.post(f"{BASE}/destinations", json=webhook("http://203.0.113.13/x", **BOTH))
    client.post(f"{BASE}/destinations", json=webhook("https://203.0.113.13/x", allow_private=True))
    spec = kind_specs.get_kind("webhook")
    views = view.DocRoutingView(service.docs.snapshot()).destinations()
    on = [v for v in views if v.config.get("allow_plain_http")]
    assert len(on) == 1 and len(views) == 2
    assert base.policy_for(spec, on[0].config, "http://203.0.113.13/x").allow_plain_http is True
    other = [v for v in views if v is not on[0]][0]
    assert base.policy_for(spec, other.config, "https://203.0.113.13/x").allow_plain_http is False
    assert base.policy_for(spec, {"allow_plain_http": True}, "http://203.0.113.13/x").allow_plain_http is False


def test_local_policy_refusals_classify_as_uncounted_classes():
    assert base.classify_error(GuardLocalPolicy("scheme", "plain_http")).failure is FailureClass.PLAIN_HTTP_OFF
    assert base.classify_error(GuardLocalPolicy("address", "private")).failure is FailureClass.PRIVATE_OFF
    assert {FailureClass.PLAIN_HTTP_OFF, FailureClass.PRIVATE_OFF} <= set(__import__("src.core.notifications.contracts", fromlist=["x"]).NOT_COUNTED)


def test_the_switch_is_local_only_never_exported_and_delete_removes_it(service, config_path):
    client = make_client(service)
    dest = client.post(f"{BASE}/destinations", json=webhook("http://203.0.113.13/x", **BOTH)).json()["destination"]["id"]
    doc = service.docs.snapshot()
    key = view.allow_plain_http_key(dest)
    assert doc["local"][key] == "http://203.0.113.13:80" and key.startswith("local/") and "allow_plain_http" not in json.dumps(doc["global"])
    cfg = config_writer.read_config(config_path)
    assert "allow_plain_http" in json.dumps(cfg["notification_routing"])
    projected = bundle.project(cfg, {})
    assert "allow_plain_http" not in json.dumps(projected)
    client.delete(f"{BASE}/destinations/{dest}")
    assert key not in service.docs.snapshot()["local"]


def test_a_synced_http_destination_is_accepted_without_the_switch(service):
    spec = kind_specs.get_kind("webhook")
    assert validate.validate_fields(spec.secret_fields, {"url": "http://203.0.113.13/x"}, spec)["url"].startswith("http://")
    slack = kind_specs.get_kind("slack")
    with pytest.raises(validate.InvalidDestination):
        validate.validate_fields(slack.secret_fields, {"url": "http://hooks.slack.com/services/T0/B0/abc"}, slack)
