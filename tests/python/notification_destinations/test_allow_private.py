
from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("fastapi")

from src.core import config_writer  # noqa: E402
from src.core.config_bundle import bundle  # noqa: E402
from src.core.notifications import kind_specs  # noqa: E402
from src.core.notifications.destinations import validate  # noqa: E402
from src.core.notifications.kinds import base  # noqa: E402
from src.core.notifications.settings_doc import view  # noqa: E402

from .conftest import slack_body  # noqa: E402
from .test_settings_and_destinations import BASE, make_client  # noqa: E402

PRIVATE_URLS = ["https://203.0.113.13/hook", "https://192.0.2.13/x", "https://127.0.0.1:9000/x", "https://[fd00::1]/x",
                "https://ntfy.lan/x", "https://box.local/x", "https://router.home.arpa/x", "https://localhost/x"]


def webhook(url: str, **over) -> dict:
    return {"kind": "webhook", "name": "hook", "secrets": {"url": url}, **over}


def fields_of(response) -> dict:
    assert response.status_code == 422, response.text
    return response.json()["detail"]["fields"]


def test_http_is_refused_for_every_kind_with_a_plain_code(service):
    client = make_client(service)
    for body in (slack_body("http://hooks.slack.com/services/T0/B0/abc"), webhook("http://example.com/x", allow_private=True),
                 {"kind": "ntfy", "name": "n", "config": {"base_url": "http://ntfy.sh"}, "secrets": {"topic": "t"}}):
        got = fields_of(client.post(f"{BASE}/destinations", json=body))
        assert validate.HTTPS_REQUIRED in got.values()


@pytest.mark.parametrize("url", PRIVATE_URLS)
def test_private_host_refused_while_off_and_accepted_when_on(service, url):
    client = make_client(service)
    assert fields_of(client.post(f"{BASE}/destinations", json=webhook(url))) == {"url": validate.PRIVATE_ADDRESS}
    made = client.post(f"{BASE}/destinations", json=webhook(url, allow_private=True))
    assert made.status_code == 201, made.text
    assert made.json()["destination"]["allow_private"] is True


def test_ntfy_private_base_follows_the_switch(service):
    client = make_client(service)
    body = {"kind": "ntfy", "name": "n", "config": {"base_url": "https://203.0.113.13"}, "secrets": {"topic": "t"}}
    assert fields_of(client.post(f"{BASE}/destinations", json=body)) == {"base_url": validate.PRIVATE_ADDRESS}
    assert client.post(f"{BASE}/destinations", json={**body, "allow_private": True}).status_code == 201


def test_link_local_stays_refused_even_with_the_switch(service):
    got = fields_of(make_client(service).post(f"{BASE}/destinations", json=webhook("https://169.254.169.254/x", allow_private=True)))
    assert got == {"url": validate.BAD_VALUE}


def test_a_public_host_needs_no_switch(service):
    r = make_client(service).post(f"{BASE}/destinations", json=webhook("https://example.com/x"))
    assert r.status_code == 201 and r.json()["destination"]["allow_private"] is False


def test_other_kinds_refuse_the_field(service):
    client = make_client(service)
    got = fields_of(client.post(f"{BASE}/destinations", json={**slack_body(), "allow_private": True}))
    assert got == {"allow_private": validate.NOT_SUPPORTED}
    dest = client.post(f"{BASE}/destinations", json=slack_body()).json()["destination"]["id"]
    assert fields_of(client.patch(f"{BASE}/destinations/{dest}", json={"allow_private": True})) == {"allow_private": validate.NOT_SUPPORTED}
    assert client.get(f"{BASE}/destinations").json()["destinations"][0]["allow_private"] is False


def test_patch_round_trips_and_the_url_check_uses_the_value_in_force(service):
    client = make_client(service)
    dest = client.post(f"{BASE}/destinations", json=webhook("https://203.0.113.13/x", allow_private=True)).json()["destination"]["id"]
    assert client.get(f"{BASE}/destinations").json()["destinations"][0]["allow_private"] is True
    ok = client.patch(f"{BASE}/destinations/{dest}", json={"secrets": {"url": "https://192.0.2.19/y"}})
    assert ok.status_code == 200
    bad = client.patch(f"{BASE}/destinations/{dest}", json={"allow_private": False, "secrets": {"url": "https://198.51.100.19/z"}})
    assert fields_of(bad) == {"url": validate.PRIVATE_ADDRESS}
    off = client.patch(f"{BASE}/destinations/{dest}", json={"allow_private": False})
    assert off.status_code == 200 and off.json()["destination"]["allow_private"] is False


def test_the_guard_honors_the_switch_through_the_view(service):
    client = make_client(service)
    client.post(f"{BASE}/destinations", json=webhook("https://203.0.113.13/x", allow_private=True))
    client.post(f"{BASE}/destinations", json=webhook("https://example.com/x"))
    spec = kind_specs.get_kind("webhook")
    on = [v for v in view.DocRoutingView(service.docs.snapshot()).destinations() if v.config.get("allow_private")]
    off = [v for v in view.DocRoutingView(service.docs.snapshot()).destinations() if not v.config.get("allow_private")]
    assert len(on) == 1 and len(off) == 1
    assert base.policy_for(spec, on[0].config, "https://203.0.113.13/x").allow_private is True
    assert base.policy_for(spec, off[0].config, "https://example.com/x").allow_private is False


def test_the_switch_is_a_local_key_only_and_delete_removes_it(service, config_path):
    client = make_client(service)
    dest = client.post(f"{BASE}/destinations", json=webhook("https://203.0.113.13/x", allow_private=True)).json()["destination"]["id"]
    doc = service.docs.snapshot()
    key = view.allow_private_key(dest)
    assert doc["local"][key] == "https://203.0.113.13:443" and key.startswith("local/")
    assert "allow_private" not in json.dumps(doc["global"])
    client.delete(f"{BASE}/destinations/{dest}")
    assert key not in service.docs.snapshot()["local"]


def test_a_global_record_claiming_the_switch_is_ignored(service):
    from src.core.notifications.sync import sanitize

    record = {"kind": "webhook", "name": "x", "enabled": True, "config": {"allow_private": True}, "secret_fields": [], "secret_rev": 0}
    assert sanitize._clean_record(record) is None
    client = make_client(service)
    dest = client.post(f"{BASE}/destinations", json=webhook("https://example.com/x")).json()["destination"]["id"]
    doc = service.docs.snapshot()
    assert view.allow_private(doc, dest) is False


def test_the_bundle_export_never_carries_the_switch(service, config_path):
    client = make_client(service)
    client.post(f"{BASE}/destinations", json=webhook("https://203.0.113.13/x", allow_private=True))
    doc = config_writer.read_config(config_path)
    assert "notification_routing" in doc and "allow_private" in json.dumps(doc["notification_routing"])
    projected = bundle.project(doc, {})
    assert "allow_private" not in json.dumps(projected) and "notification_routing" not in projected["config"]
