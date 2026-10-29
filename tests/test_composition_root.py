
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

import os
import sys
import tempfile

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import session_manager as session_manager_module
from src.core.composition import AppServices, build_services
from src.core.live_install_roots import LiveInstallRoots
from src.core.live_ports import (
    LiveSessionRecordStore,
    LiveSettings,
    SystemClock,
)
from src.core.session_manager import SessionManager
from src.core.sessions.probe_health import ProbeHealthRecorder
from src.core.sessions.registry import SessionRegistry
from src.core.sessions.sidecars import AttachmentSidecars
from src.core.sessions.theme_store import ThemeStore
from src.core.sessions.toast_inbox import ToastInbox

REQUIRED_FIELDS = {
    "session_manager",
    "probe_health",
    "themes",
    "toasts",
    "registry",
    "sidecars",
    "owned_tmux",
    "clock",
    "settings_reader",
    "records",
    "install_roots",
    "catalog",
    "ui_preferences",
}


class _StubSettings:

    def __init__(self, real: object, pin_path: Path, cap: int) -> None:
        self._real = real
        self._pin_path = pin_path
        self._cap = cap

    def __getattr__(self, name: str) -> object:
        return getattr(self._real, name)

    def get_pinned_themes_path(self) -> Path:
        return self._pin_path

    @property
    def log_buffer_size(self) -> int:
        return self._cap


def test_app_services_carries_every_required_field():
    present = {f.name for f in dataclasses.fields(AppServices)}

    assert present == REQUIRED_FIELDS, (
        "AppServices fields drifted; a missing one leaves a later slice "
        "with nowhere to inject a collaborator from"
    )


def test_app_services_is_frozen():
    services = build_services()

    with pytest.raises(dataclasses.FrozenInstanceError):
        services.toasts = ToastInbox()  # type: ignore[misc]


def test_the_five_collaborators_are_the_manager_s_own_objects():
    services = build_services()
    manager = services.session_manager

    assert services.probe_health is manager._probe_health
    assert services.themes is manager._theme_store
    assert services.toasts is manager._toast_inbox
    assert services.registry is manager._registry
    assert services.sidecars is manager._sidecars
    assert services.owned_tmux is manager._owned


def test_a_write_through_the_services_side_is_visible_on_the_facade():
    services = build_services()
    manager = services.session_manager

    services.themes.pinned_themes["cloude_from_services"] = "matrix"
    services.toasts.pending["ses_from_services"] = []
    services.registry.log_buffers["ses_from_services"] = []
    services.registry.command_counts["ses_from_services"] = 3
    services.sidecars.adopt_fifo_offsets["ses_from_services"] = 41
    services.owned_tmux.names.add("cloude_from_services")

    assert manager._theme_store.pinned_themes["cloude_from_services"] == "matrix"
    assert "ses_from_services" in manager._toast_inbox.pending
    assert manager._registry.log_buffers["ses_from_services"] == []
    assert manager._registry.command_counts["ses_from_services"] == 3
    assert manager._sidecars.adopt_fifo_offsets["ses_from_services"] == 41
    assert "cloude_from_services" in manager._owned.names


def test_a_write_through_the_facade_is_visible_on_the_services_side():
    services = build_services()
    manager = services.session_manager

    manager._theme_store.pinned_themes["cloude_from_facade"] = "amber"
    manager._registry.log_buffers["ses_from_facade"] = []
    manager._sidecars.adopt_fifo_offsets["ses_from_facade"] = 4096
    manager._owned.names.add("cloude_from_facade")

    assert services.themes.pinned_themes["cloude_from_facade"] == "amber"
    assert "ses_from_facade" in services.registry.log_buffers
    assert services.sidecars.adopt_fifo_offsets["ses_from_facade"] == 4096
    assert "cloude_from_facade" in services.owned_tmux.names


def test_probe_health_records_once_and_both_sides_read_it():
    services = build_services()

    services.probe_health.record_failure(reason="socket_missing", detail="x")

    health = services.session_manager._probe_health.health
    assert health.ok is False
    assert health.reason == "socket_missing"


def test_an_injected_collaborator_is_the_one_the_manager_gets():
    inbox = ToastInbox()

    services = build_services(toasts=inbox)

    assert services.toasts is inbox
    assert services.session_manager._toast_inbox is inbox
    inbox.pending["ses_injected"] = []
    assert "ses_injected" in services.session_manager._toast_inbox.pending
    assert isinstance(services.themes, ThemeStore)
    assert isinstance(services.registry, SessionRegistry)
    assert isinstance(services.sidecars, AttachmentSidecars)
    assert isinstance(services.probe_health, ProbeHealthRecorder)


def test_two_calls_build_two_independent_applications():
    first = build_services()
    second = build_services()

    assert first.toasts is not second.toasts
    first.toasts.pending["ses_leak"] = []
    assert "ses_leak" not in second.toasts.pending


def test_passing_a_manager_and_a_collaborator_is_refused():
    manager = SessionManager()

    with pytest.raises(ValueError) as excinfo:
        build_services(session_manager=manager, toasts=ToastInbox())

    assert "two objects holding one state" in str(excinfo.value)


def test_install_roots_is_a_port_and_not_a_collaborator(tmp_path):

    class StubRoots:
        def targets_for(self, kind, scope, project_path):
            return ()

        def required_manifest(self, kind):
            return "SKILL.md"

        def trash_dir(self, harness, scope, project_path):
            return tmp_path / "trash"

        def staging_dir(self):
            return tmp_path / "staging"

        def pending_dir(self):
            return tmp_path / "pending"

        def root_listing(self, harness):
            return ()

        def read_only_listing(self, harness):
            return ()

        def present_harnesses(self):
            return ()

        def legacy_targets_for(self, kind, scope, project_path):
            return ()

    stub = StubRoots()
    manager = build_services().session_manager

    services = build_services(session_manager=manager, install_roots=stub)

    assert services.install_roots is stub


def test_wrapping_an_existing_manager_mints_no_sixth_object():
    manager = SessionManager()

    services = build_services(session_manager=manager)

    assert services.session_manager is manager
    assert services.themes is manager._theme_store
    assert services.owned_tmux is manager._owned
    manager._registry.command_counts["ses_wrapped"] = 9
    assert services.registry.command_counts["ses_wrapped"] == 9
    manager._owned.names.add("cloude_wrapped")
    assert "cloude_wrapped" in services.owned_tmux.names


def test_the_theme_store_writes_where_the_patched_settings_say(
    tmp_path, monkeypatch
):
    pin_file = tmp_path / "pinned_themes.json"
    stub = _StubSettings(session_manager_module.settings, pin_file, 5)
    monkeypatch.setattr(session_manager_module, "settings", stub)

    services = build_services()
    services.themes.set_pin("cloude_isolated", "matrix")
    services.themes.save()

    assert pin_file.exists(), (
        "the pin file did not land in the patched location; a settings "
        "reader that bypassed the patch would have written the real home"
    )
    assert "cloude_isolated" in pin_file.read_text(encoding="utf-8")


def test_the_registry_line_cap_honours_the_patched_settings(
    tmp_path, monkeypatch
):
    stub = _StubSettings(session_manager_module.settings, tmp_path / "p.json", 2)
    monkeypatch.setattr(session_manager_module, "settings", stub)

    services = build_services()
    services.registry.ensure("ses_capped")
    for i in range(5):
        services.registry.append_log("ses_capped", f"line {i}")

    assert len(services.registry.log_buffers["ses_capped"]) == 2, (
        "the cap under test was the real one, so the settings reader is "
        "not resolving through the name the suite patches"
    )


def test_the_settings_reader_is_read_late_not_captured(tmp_path, monkeypatch):
    services = build_services()
    stub = _StubSettings(session_manager_module.settings, tmp_path / "late.json", 9)
    monkeypatch.setattr(session_manager_module, "settings", stub)

    assert services.settings_reader.pinned_themes_path() == tmp_path / "late.json"
    assert services.settings_reader.log_buffer_size() == 9


def test_the_production_defaults_are_the_live_implementations():
    services = build_services()

    assert isinstance(services.clock, SystemClock)
    assert isinstance(services.settings_reader, LiveSettings)
    assert isinstance(services.records, LiveSessionRecordStore)
    assert isinstance(services.install_roots, LiveInstallRoots)


def test_the_conftest_fixture_hands_back_a_real_application(app_services):
    assert isinstance(app_services, AppServices)
    assert app_services.themes is app_services.session_manager._theme_store
    app_services.registry.command_counts["ses_fixture"] = 1
    assert app_services.session_manager._registry.command_counts["ses_fixture"] == 1
