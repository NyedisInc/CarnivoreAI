
import subprocess
from types import SimpleNamespace

import pytest

from src.core import message_host_identity
from src.core.hosts import machine_identity

UUID = "0A1B2C3D-0000-1111-2222-333344445555"


def _run_returning(stdout: str):
    return lambda *a, **k: SimpleNamespace(stdout=stdout)


def test_ioreg_uuid_parsed_on_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(machine_identity.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(machine_identity.subprocess, "run", _run_returning(f'  "IOPlatformUUID" = "{UUID}"\n'))
    assert machine_identity.ioreg_platform_uuid() == UUID


def test_ioreg_failure_is_none_not_a_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a, **k):
        raise subprocess.TimeoutExpired("ioreg", 20)

    monkeypatch.setattr(machine_identity.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(machine_identity.subprocess, "run", boom)
    assert machine_identity.ioreg_platform_uuid() is None


def test_display_name_falls_back_to_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(machine_identity.platform, "system", lambda: "Linux")
    monkeypatch.setattr(machine_identity.platform, "node", lambda: "studio")
    assert machine_identity.computer_display_name() == "studio"


def test_capture_identity_uses_the_public_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(message_host_identity, "ioreg_platform_uuid", lambda: UUID)
    assert message_host_identity.capture_identity().machine_id == UUID
