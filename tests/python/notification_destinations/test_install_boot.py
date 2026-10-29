
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.config import settings
from src.core.notifications import contracts, engine as engine_mod, install, routing_view
from src.core.notifications.destinations.secrets import DestinationSecrets
from src.core.notifications.destinations.service import NotificationService

SENTINEL = "SENTINEL-boot-77c1"
LEGACY = {
    "enabled": False, "ntfy_base_url": "https://ntfy.sh", "ntfy_topic": f"topic-{SENTINEL}",
    "public_base_url": "http://mac.lan:8000", "slack_webhook_url": f"https://hooks.slack.com/services/T/B/{SENTINEL}",
    "pushover_token": f"tok-{SENTINEL}", "pushover_user_key": f"usr-{SENTINEL}",
}


class FailableKeychain:

    def __init__(self) -> None:
        from src.core import relay_keychain

        self._rk, self.items, self.fail = relay_keychain, {}, False

    def read_state(self, service, account):
        v = self.items.get((service, account))
        return (self._rk.READ_OK, v) if v else (self._rk.READ_ABSENT, None)

    def write(self, service, account, secret):
        if self.fail:
            raise self._rk.KeychainWriteError("locked")
        self.items[(service, account)] = secret

    def delete(self, service, account):
        return self.items.pop((service, account), None) is not None


def _manager() -> SimpleNamespace:
    return SimpleNamespace(notification_policy_for=lambda sid: SimpleNamespace(suppresses=False))


@pytest.fixture()
def boot(tmp_path: Path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"config_version": 1, "notifications": LEGACY}))
    monkeypatch.setattr(settings, "auth_config_file", str(config))
    monkeypatch.setenv("CLOUDE_STATE_DIR", str(tmp_path / "state"))
    keychain = FailableKeychain()
    service = NotificationService(config)
    service.destinations._secrets = DestinationSecrets(backend=keychain)
    service.secrets = service.destinations._secrets
    return SimpleNamespace(notification_service=service), config, keychain


def _files_text(config: Path) -> str:
    bak = config.with_suffix(".json.bak")
    return config.read_text() + (bak.read_text() if bak.exists() else "")


def test_a_legacy_plaintext_config_migrates_at_boot_to_disabled_keychain_destinations(boot) -> None:
    app_state, config, keychain = boot
    assert SENTINEL in config.read_text()

    async def run():
        handle = await install.install(app_state, _manager())
        try:
            svc = app_state.notification_service
            dests = await svc.destinations.list()
            return handle, dests, [await svc.secrets.get(d["id"]) for d in dests]
        finally:
            await install.uninstall(handle)

    handle, dests, read_back = asyncio.run(run())
    assert handle.engine is not None and handle.migration.complete
    assert {d["kind"] for d in dests} == {"slack", "ntfy", "pushover"}
    assert not any(d["enabled"] for d in dests)
    assert len(keychain.items) == 3 and all(SENTINEL in json.dumps(r) for r in read_back)
    assert SENTINEL not in _files_text(config)
    assert "public_base_url" not in json.loads(config.read_text())["notifications"]


def test_a_failing_keychain_at_boot_keeps_the_plaintext_and_still_serves(boot) -> None:
    app_state, config, keychain = boot
    keychain.fail = True

    async def run():
        handle = await install.install(app_state, _manager())
        try:
            return handle, contracts.sink_installed()
        finally:
            await install.uninstall(handle)

    handle, sink_up = asyncio.run(run())
    assert SENTINEL in config.read_text()
    assert not handle.migration.complete and sink_up


def test_install_wires_the_sink_and_uninstall_removes_everything(boot) -> None:
    app_state, _config, _keychain = boot

    async def run():
        before = set(asyncio.all_tasks())
        handle = await install.install(app_state, _manager())
        wired = (contracts.sink_installed(), engine_mod.current_engine() is handle.engine,
                 routing_view.current_view() is not None)
        await install.uninstall(handle)
        await asyncio.sleep(0)
        return wired, (contracts.sink_installed(), engine_mod.current_engine(), routing_view.current_view()), \
            [t for t in asyncio.all_tasks() if t not in before and not t.done()]

    wired, after, left = asyncio.run(run())
    assert wired == (True, True, True)
    assert after == (False, None, None) and left == []
