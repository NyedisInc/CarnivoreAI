
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from structlog.testing import capture_logs

import pytest

from src.core.notifications import doc_model, http
from src.core.notifications.settings_doc import view
from src.core.notifications.destinations import migration, validate

SENTINEL = "SENTINEL-xyzzy-9f3a"
OLD = {
    "enabled": True, "ntfy_base_url": "https://ntfy.sh", "ntfy_topic": f"topic-{SENTINEL}",
    "public_base_url": "http://mac.lan:8000", "slack_webhook_url": f"https://hooks.slack.com/services/T/B/{SENTINEL}",
    "pushover_token": f"tok-{SENTINEL}", "pushover_user_key": f"usr-{SENTINEL}", "idle_threshold_seconds": 30.0,
}


def write_cfg(path: Path, **over) -> None:
    path.write_text(json.dumps({"notifications": {**OLD, **over}, "agents": {}}))


def files_text(path: Path) -> str:
    return path.read_text() + (path.with_suffix(".json.bak").read_text() if path.with_suffix(".json.bak").exists() else "")


def run(service, path, subs=()):
    return asyncio.run(migration.migrate(path, service.docs, service.destinations, list(subs), writer=service.routing))


def test_migrates_scrubs_config_and_bak_and_keeps_no_plaintext(service, config_path, keychain, caplog):
    write_cfg(config_path)
    caplog.set_level(logging.DEBUG)
    assert SENTINEL in config_path.read_text()
    with capture_logs() as logs:
        res = run(service, config_path)
    assert res.migrated == ["slack", "ntfy", "pushover"] and res.complete and not res.skipped
    assert SENTINEL not in files_text(config_path) + json.dumps(logs, default=str) + caplog.text
    cfg = json.loads(config_path.read_text())
    assert "public_base_url" not in cfg["notifications"] and cfg["notifications"]["ntfy_base_url"] == "https://ntfy.sh"
    assert cfg["notifications"]["idle_threshold_seconds"] == 30.0
    dests = asyncio.run(service.destinations.list())
    assert {d["kind"] for d in dests} == {"slack", "ntfy", "pushover"}
    assert all(d["enabled"] for d in dests) and len(keychain.items) == 3
    assert any(e["event"] == "notification_public_base_url_retired" for e in logs)


def test_failing_keychain_keeps_plaintext_untouched(service, config_path, keychain):
    write_cfg(config_path)
    before = config_path.read_text()
    keychain.fail_writes = True
    res = run(service, config_path)
    assert res.migrated == [] and set(res.skipped) == {"slack", "ntfy", "pushover"} and not res.complete
    cfg = json.loads(config_path.read_text())["notifications"]
    assert SENTINEL in cfg["slack_webhook_url"] and SENTINEL in cfg["ntfy_topic"] and SENTINEL in cfg["pushover_token"]
    assert asyncio.run(service.destinations.list()) == []
    keychain.fail_writes = False
    res = run(service, config_path)
    assert res.complete and len(res.migrated) == 3
    assert SENTINEL not in files_text(config_path)
    assert before != config_path.read_text()


def test_idempotent_second_run_changes_nothing(service, config_path, keychain):
    write_cfg(config_path)
    run(service, config_path)
    after_cfg, after_doc, items = config_path.read_text(), service.docs.snapshot(), dict(keychain.items)
    res = run(service, config_path)
    assert res.already_done and res.migrated == []
    assert config_path.read_text() == after_cfg and service.docs.snapshot() == after_doc and keychain.items == items


def test_rerun_before_marker_finds_existing_destination_not_a_twin(service, config_path, keychain):
    write_cfg(config_path)
    first = run(service, config_path)
    doc = service.docs.snapshot()
    doc = {**doc, "local": {k: v for k, v in doc["local"].items() if k != migration.MIGRATED_KEY}}
    service.docs.update(lambda d, me: doc)
    write_cfg(config_path)
    run(service, config_path)
    assert len(asyncio.run(service.destinations.list())) == len(first.migrated) == 3


def test_disabled_while_enabled_false_and_pause_unchanged(service, config_path):
    write_cfg(config_path, enabled=False)
    run(service, config_path)
    dests = asyncio.run(service.destinations.list())
    assert len(dests) == 3 and not any(d["enabled"] for d in dests)
    assert service.routing.view().paused is False


def test_half_configured_pushover_and_empty_config(service, config_path):
    write_cfg(config_path, slack_webhook_url="", ntfy_topic="", pushover_user_key="")
    res = run(service, config_path)
    assert res.migrated == [] and res.complete
    assert json.loads(config_path.read_text())["notifications"]["pushover_token"].endswith(SENTINEL)


def test_invalid_url_skips_only_that_channel(service, config_path):
    write_cfg(config_path, slack_webhook_url="https://evil.example/x")
    res = run(service, config_path)
    assert res.skipped == ["slack"] and res.migrated == ["ntfy", "pushover"] and not res.complete
    assert json.loads(config_path.read_text())["notifications"]["slack_webhook_url"] == "https://evil.example/x"


def test_push_devices_get_local_needs_you_ticks(service, config_path):
    write_cfg(config_path, slack_webhook_url="", ntfy_topic="", pushover_token="")
    res = run(service, config_path, subs=["a", "b"])
    assert res.push_devices == 2
    v = service.routing.view()
    for sub in ("webpush:a", "webpush:b"):
        assert v.is_ticked(sub, "session.permission") and v.is_ticked(sub, "approval.agent_action")
        assert not v.is_ticked(sub, "approval.folder_trust") and not v.is_ticked(sub, "session.finished")
    assert not any("webpush" in p for p in service.docs.snapshot()["global"])
    assert all(p.startswith("tick/webpush:") or p.startswith("local/") for p in service.docs.snapshot()["local"])


def bak_text(path: Path) -> str:
    return path.with_suffix(".json.bak").read_text()


def test_private_ntfy_base_comes_over_with_allow_private_local_only(service, config_path, keychain):
    write_cfg(config_path, ntfy_base_url="https://ntfy.example.lan:8443", slack_webhook_url="", pushover_token="", pushover_user_key="")
    res = run(service, config_path)
    assert res.migrated == ["ntfy"] and res.complete
    (dest,) = asyncio.run(service.destinations.list())
    assert dest["enabled"] and dest["allow_private"] and dest["config"]["base_url"] == "https://ntfy.example.lan:8443"
    doc = service.docs.snapshot()
    assert any(k.startswith("local/allow_private") for k in doc["local"])
    assert not any("allow_private" in k for k in doc["global"])
    assert SENTINEL not in files_text(config_path)


def test_public_ntfy_base_does_not_get_allow_private(service, config_path):
    write_cfg(config_path, ntfy_base_url="https://ntfy.example.org", slack_webhook_url="", pushover_token="", pushover_user_key="")
    run(service, config_path)
    (dest,) = asyncio.run(service.destinations.list())
    assert dest["enabled"] and not dest["allow_private"]


def test_http_ntfy_base_on_a_public_host_comes_over_disabled_with_a_reason_and_scrubbed(service, config_path, keychain):
    write_cfg(config_path, ntfy_base_url="http://ntfy.example.org:8080", slack_webhook_url="", pushover_token="", pushover_user_key="")
    res = run(service, config_path)
    assert res.migrated == ["ntfy"] and res.complete
    (dest,) = asyncio.run(service.destinations.list())
    assert not dest["enabled"] and not dest["allow_private"] and not dest["allow_plain_http"]
    assert dest["config"]["base_url"].startswith("https://ntfy.example.org")
    assert dest["disabled_reason"] == migration.HTTP_BASE_REASON
    assert view.status_json(dest, None)["disabled_reason"] == migration.HTTP_BASE_REASON
    assert SENTINEL not in files_text(config_path) and len(keychain.items) == 1
    assert not any(d.enabled for d in service.routing.view().destinations())


@pytest.mark.parametrize("base", ["http://203.0.113.13:8080", "http://homeassistant.local:8123"])
def test_http_ntfy_base_on_a_private_host_keeps_http_enabled_with_both_switches(service, config_path, keychain, base):
    write_cfg(config_path, ntfy_base_url=base, slack_webhook_url="", pushover_token="", pushover_user_key="")
    res = run(service, config_path)
    assert res.migrated == ["ntfy"] and res.complete
    (dest,) = asyncio.run(service.destinations.list())
    assert dest["enabled"] and dest["allow_private"] and dest["allow_plain_http"]
    assert dest["config"]["base_url"] == base and not dest["disabled_reason"]
    doc = service.docs.snapshot()
    assert any(k.startswith("local/allow_plain_http") for k in doc["local"])
    assert not any("allow_plain_http" in k for k in doc["global"])
    origin = http.origin_of(base)
    assert origin and [v for k, v in doc["local"].items() if k.startswith(("local/allow_plain_http", "local/allow_private"))] == [origin, origin]
    assert SENTINEL not in files_text(config_path)


def test_no_route_can_create_an_http_destination(service):
    with pytest.raises(validate.InvalidDestination) as exc:
        asyncio.run(service.destinations.create("ntfy", "n", {"base_url": "http://ntfy.example.org"}, {"topic": "abcdef"}))
    assert exc.value.fields["base_url"] == validate.HTTPS_REQUIRED


def test_partial_migration_scrubs_bak_too_then_caps_retries_and_alerts_once(service, config_path, keychain, monkeypatch):
    alerts: list = []
    monkeypatch.setattr(migration.alert_service, "raise_alert", lambda key, **kw: alerts.append((key, kw)))
    bad = f"https://evil.example/{SENTINEL}"
    write_cfg(config_path, slack_webhook_url=bad, pushover_token="")
    first = run(service, config_path)
    assert first.skipped == ["slack"] and first.migrated == ["ntfy"] and not first.complete
    assert f"topic-{SENTINEL}" not in config_path.read_text() and f"topic-{SENTINEL}" not in bak_text(config_path)
    assert bad in config_path.read_text()
    assert alerts == []
    run(service, config_path)
    assert alerts == []
    third = run(service, config_path)
    assert third.skipped == ["slack"] and third.complete
    assert len(alerts) == 1 and alerts[0][0] == migration.ALERT_KEY and alerts[0][1]["params"] == {"kinds": "slack"}
    fourth = run(service, config_path)
    assert fourth.already_done and len(alerts) == 1
    assert bad in config_path.read_text() and asyncio.run(service.destinations.list())[0]["kind"] == "ntfy"
    doc = service.docs.snapshot()
    service.docs.update(lambda d, me: {**doc, "local": {k: v for k, v in doc["local"].items() if k != migration.MIGRATED_KEY}})
    again = run(service, config_path)
    assert again.abandoned == ["slack"] and again.skipped == [] and len(alerts) == 1
