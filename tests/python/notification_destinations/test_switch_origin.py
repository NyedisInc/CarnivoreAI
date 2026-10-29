
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("fastapi")

from src.core.notifications import doc_model, kind_specs  # noqa: E402
from src.core.notifications.contracts import FailureClass  # noqa: E402
from src.core.notifications.destinations import switch_origin, validate  # noqa: E402
from src.core.notifications.http import GuardLocalPolicy  # noqa: E402
from src.core.notifications.kinds import base  # noqa: E402
from src.core.notifications.settings_doc import view  # noqa: E402

from .test_allow_plain_http import BOTH  # noqa: E402
from .test_allow_private import fields_of, webhook  # noqa: E402
from .test_settings_and_destinations import BASE, make_client  # noqa: E402

SPEC = kind_specs.get_kind("webhook")
A, B = "http://203.0.113.13:8123/hook", "http://203.0.113.19:8123/hook"


def _config(service, dest_id):
    return next(v for v in view.DocRoutingView(service.docs.snapshot()).destinations() if v.id == dest_id).config


def _create(service) -> tuple:
    client = make_client(service)
    return client, client.post(f"{BASE}/destinations", json=webhook(A, **BOTH)).json()["destination"]["id"]


def test_the_switch_is_void_after_the_url_changes_and_returns_after_reapproval(service):
    client, dest = _create(service)
    cfg = _config(service, dest)
    assert base.policy_for(SPEC, cfg, A).allow_plain_http is True
    moved = base.policy_for(SPEC, cfg, B)
    assert moved.allow_private is False and moved.allow_plain_http is False and moved.origin_changed is True
    assert base.classify_error(GuardLocalPolicy("scheme", "origin")).failure is FailureClass.ORIGIN_CHANGED
    assert client.patch(f"{BASE}/destinations/{dest}", json={"secrets": {"url": B}, **BOTH}).status_code == 200
    cfg = _config(service, dest)
    assert base.policy_for(SPEC, cfg, B).allow_plain_http is True and base.policy_for(SPEC, cfg, A).allow_private is False


def test_a_save_that_does_not_touch_the_switch_or_url_keeps_the_old_origin(service):
    client, dest = _create(service)
    key = view.allow_private_key(dest)
    before = service.docs.snapshot()["local"][key]
    assert client.patch(f"{BASE}/destinations/{dest}", json={"name": "renamed"}).status_code == 200
    assert service.docs.snapshot()["local"][key] == before == "http://203.0.113.13:8123"


def test_backfill_records_the_current_origin_for_a_bare_true_switch(service):
    _, dest = _create(service)
    k_priv, k_plain = switch_origin.keys_of(dest)

    def legacy(d, me):
        return doc_model.set_local(doc_model.set_local(d, k_priv, True), k_plain, True)

    service.docs.update(legacy)
    assert base.policy_for(SPEC, _config(service, dest), A).allow_private is False
    assert asyncio.run(switch_origin.backfill(service.docs, service.destinations._secrets)) == 2
    local = service.docs.snapshot()["local"]
    assert local[k_priv] == local[k_plain] == "http://203.0.113.13:8123"
    assert base.policy_for(SPEC, _config(service, dest), A).allow_plain_http is True
    assert asyncio.run(switch_origin.backfill(service.docs, service.destinations._secrets)) == 0


def test_backfill_reads_the_ntfy_base_from_the_public_config(service):
    client = make_client(service)
    body = {"kind": "ntfy", "name": "n", "config": {"base_url": "http://ntfy.lan:8080"}, "secrets": {"topic": "t"}, **BOTH}
    dest = client.post(f"{BASE}/destinations", json=body).json()["destination"]["id"]
    service.docs.update(lambda d, me: doc_model.set_local(d, view.allow_private_key(dest), True))
    assert asyncio.run(switch_origin.backfill(service.docs, service.destinations._secrets)) == 1
    assert service.docs.snapshot()["local"][view.allow_private_key(dest)] == "http://ntfy.lan:8080"


@pytest.mark.parametrize("host", ["8.8.8.8", "134744072", "0x8.0x8.0x8.0x8", "0x08080808", "8.8.2056"])
def test_a_public_literal_over_http_is_refused_at_save_in_every_notation(service, host):
    got = fields_of(make_client(service).post(f"{BASE}/destinations", json=webhook(f"http://{host}/x", **BOTH)))
    assert got == {"url": validate.PLAIN_HTTP_PUBLIC}


def test_the_sync_path_refuses_a_public_literal_over_http_like_any_invalid_record(service):
    with pytest.raises(validate.InvalidDestination) as ei:
        validate.validate_fields(SPEC.secret_fields, {"url": "http://93.184.216.34/x"}, SPEC)
    assert ei.value.fields == {"url": validate.PLAIN_HTTP_PUBLIC}
    from src.core.notifications.sync import secrets_sync

    assert secrets_sync._checked_fields(SPEC, {"url": "http://134744072/x"}) is None
    assert secrets_sync._checked_fields(SPEC, {"url": "http://203.0.113.13/x"}) is not None


def _retarget(service, dest_id: str, url: str) -> None:
    fields = asyncio.run(service.destinations._secrets.get(dest_id))
    asyncio.run(service.destinations._secrets.put(dest_id, {**fields, "url": url}))


def _switches(client, dest_id: str) -> tuple:
    item = next(d for d in client.get(f"{BASE}/destinations").json()["destinations"] if d["id"] == dest_id)
    listed = next(d for d in client.get(f"{BASE}/settings").json()["destinations"] if d["id"] == dest_id)
    assert (listed["allow_private"], listed["allow_plain_http"]) == (item["allow_private"], item["allow_plain_http"])
    return item["allow_private"], item["allow_plain_http"]


def test_after_a_retarget_the_api_reports_both_switches_off_and_the_card_class_is_origin_changed(service):
    client, dest = _create(service)
    assert _switches(client, dest) == (True, True)
    _retarget(service, dest, B)
    assert _switches(client, dest) == (False, False)
    moved = base.policy_for(SPEC, _config(service, dest), B)
    assert moved.origin_changed is True and moved.allow_private is False


def test_a_form_style_patch_that_resends_the_shown_values_does_not_re_approve(service):
    client, dest = _create(service)
    _retarget(service, dest, B)
    shown = _switches(client, dest)
    resend = {"name": "renamed", "allow_private": shown[0], "allow_plain_http": shown[1]}
    assert client.patch(f"{BASE}/destinations/{dest}", json=resend).status_code == 200
    assert _switches(client, dest) == (False, False)
    cfg = _config(service, dest)
    assert base.policy_for(SPEC, cfg, B).allow_private is False and base.policy_for(SPEC, cfg, B).allow_plain_http is False
    assert view.allow_private_key(dest) not in service.docs.snapshot()["local"]


def test_an_explicit_patch_with_the_switch_on_re_approves_the_new_origin(service):
    client, dest = _create(service)
    _retarget(service, dest, B)
    assert client.patch(f"{BASE}/destinations/{dest}", json=BOTH).status_code == 200
    assert _switches(client, dest) == (True, True)
    assert base.policy_for(SPEC, _config(service, dest), B).allow_plain_http is True


def test_resending_on_for_an_origin_that_still_matches_changes_nothing(service):
    client, dest = _create(service)
    keys = switch_origin.keys_of(dest)
    before = [service.docs.snapshot()["local"][k] for k in keys]
    assert client.patch(f"{BASE}/destinations/{dest}", json=BOTH).status_code == 200
    assert [service.docs.snapshot()["local"][k] for k in keys] == before == ["http://203.0.113.13:8123"] * 2
    assert _switches(client, dest) == (True, True)
