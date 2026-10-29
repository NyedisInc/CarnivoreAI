
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pytest

from src.core import relay_keychain
from src.core.notifications.destinations.secrets import DestinationSecrets
from src.core.notifications.destinations.service import NotificationService


class FakeKeychain:

    def __init__(self) -> None:
        self.items: dict = {}
        self.fail_writes = False

    def read_state(self, service, account):
        v = self.items.get((service, account))
        return (relay_keychain.READ_OK, v) if v else (relay_keychain.READ_ABSENT, None)

    def write(self, service, account, secret):
        if self.fail_writes:
            raise relay_keychain.KeychainWriteError("locked")
        self.items[(service, account)] = secret

    def delete(self, service, account):
        return self.items.pop((service, account), None) is not None


@pytest.fixture
def keychain() -> FakeKeychain:
    return FakeKeychain()


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"agents": {}}))
    return path


@pytest.fixture
def service(config_path: Path, keychain: FakeKeychain) -> NotificationService:
    svc = NotificationService(config_path)
    svc.destinations._secrets = DestinationSecrets(backend=keychain)
    return svc


@pytest.fixture
def notified(monkeypatch) -> list:
    seen: list = []
    from src.core.notifications.settings_doc import store as store_mod

    monkeypatch.setattr(store_mod.resource_push, "notify", lambda topic, *a, **k: seen.append(topic))
    return seen


def slack_body(url: Optional[str] = None, name: str = "team") -> dict:
    return {"kind": "slack", "name": name, "secrets": {"url": url or "https://hooks.slack.com/services/T0/B0/abc"}}
