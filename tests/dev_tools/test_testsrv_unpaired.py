
from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import json
from pathlib import Path
from typing import List

import pytest

from scripts.features_media import validate_capture_spec

REPO = Path(__file__).resolve().parents[2]


def _testsrv():
    loader = importlib.machinery.SourceFileLoader("testsrv_unpaired", str(REPO / "scripts" / "testsrv"))
    spec = importlib.util.spec_from_loader("testsrv_unpaired", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


@pytest.fixture
def ts(tmp_path, monkeypatch):
    mod = _testsrv()
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    mod.calls = []

    def no_signal(*_a, **_k):
        raise AssertionError("a real signal escaped the stub")

    monkeypatch.setattr(mod.os, "kill", no_signal)
    monkeypatch.setattr(mod, "stop", lambda slot: mod.calls.append("stop"))
    return mod


def _slot(ts):
    slot = ts.Slot(2)
    slot.dir.mkdir(parents=True)
    return slot


def test_a_default_slot_is_provisioned_paired(ts) -> None:
    slot = _slot(ts)
    ts.provision(slot)
    assert (slot.dir / ".totp_paired").exists()


def test_unpaired_marker_stops_the_sentinel_being_written(ts) -> None:
    slot = _slot(ts)
    slot.unpaired_marker.write_text("")
    ts.provision(slot)
    assert not (slot.dir / ".totp_paired").exists()
    assert slot.config.exists()


def test_unpaired_slot_needs_no_login(ts, monkeypatch) -> None:
    slot = _slot(ts)
    slot.unpaired_marker.write_text("")
    monkeypatch.setattr(ts, "auth_valid", lambda _s: False)
    monkeypatch.setattr(ts, "env_value", lambda *_a: (_ for _ in ()).throw(AssertionError("login tried")))
    ts.login(slot)


def test_unpair_restarts_without_the_sentinel_or_stale_login(ts, monkeypatch) -> None:
    slot = _slot(ts)
    ts.provision(slot)
    slot.auth.write_text("{}")
    seen: List[tuple] = []

    def fake_start(s, worktree, timeout):
        seen.append((slot.unpaired_marker.exists(), (slot.dir / ".totp_paired").exists(), slot.auth.exists()))
        return 0.1

    monkeypatch.setattr(ts, "require_lease", lambda _s: None)
    monkeypatch.setattr(ts, "pointed", lambda _s: REPO)
    monkeypatch.setattr(ts, "start", fake_start)
    assert ts.cmd_unpair(argparse.Namespace(slot=2, timeout=1.0)) == 0
    assert seen == [(True, False, False)]
    assert ts.calls == ["stop"]


def test_reset_and_release_undo_unpaired_mode(ts, monkeypatch) -> None:
    slot = _slot(ts)
    assert "unpaired-mode" in ts.WIPED
    slot.unpaired_marker.write_text("")
    monkeypatch.setattr(ts, "lease_info", lambda _s: {"pid": 1, "stale": False})
    ts.cmd_release(argparse.Namespace(slot=2))
    assert not slot.unpaired_marker.exists()
    assert ts.calls == ["stop"]


def test_release_of_a_paired_slot_stops_nothing(ts, monkeypatch) -> None:
    _slot(ts)
    monkeypatch.setattr(ts, "lease_info", lambda _s: {"pid": 1, "stale": False})
    ts.cmd_release(argparse.Namespace(slot=2))
    assert ts.calls == []


def test_unpaired_spec_rules() -> None:
    ok, _ = validate_capture_spec({"feature": "f", "unpaired": True, "shots": [
        {"name": "a", "kind": "screenshot", "steps": [{"goto": "/"}]}]}, "f", "f.json")
    assert ok == []
    shots = [{"name": "a", "kind": "screenshot"}]
    seeded, _ = validate_capture_spec({"feature": "f", "unpaired": True, "seed": {"preferences": {"x": 1}},
                                       "shots": shots}, "f", "f.json")
    assert any("cannot carry" in e for e in seeded)
    mocked, _ = validate_capture_spec({"feature": "f", "unpaired": True, "shots": shots,
                                       "mocks": [{"url": "**/api/v1/x", "json": {}}]}, "f", "f.json")
    assert mocked == []
    escape, _ = validate_capture_spec({"feature": "f", "shots": shots,
                                       "mocks": [{"url": "**/api/v1/x", "json_file": "../x.json"}]}, "f", "f.json")
    assert any("fixtures/<name>.json" in e for e in escape)
    typed, _ = validate_capture_spec({"feature": "f", "unpaired": "yes", "shots": shots}, "f", "f.json")
    assert any("true or false" in e for e in typed)


def test_first_run_setup_spec_is_unpaired_and_valid() -> None:
    path = REPO / "features" / "capture" / "first-run-setup.json"
    spec = json.loads(path.read_text(encoding="utf-8"))
    errors, produced = validate_capture_spec(spec, "first-run-setup", path.name)
    assert errors == [] and spec["unpaired"] is True
    assert produced == {"choose.png", "scan.png", "confirm.png"}



def _secret(slot) -> str:
    return next(ln.split("=", 1)[1] for ln in slot.env_file.read_text().splitlines() if ln.startswith("TOTP_SECRET="))


def test_clearing_unpaired_mode_rotates_the_secret_it_exposed(ts) -> None:
    slot = _slot(ts)
    ts.provision(slot)
    slot.unpaired_marker.write_text("")
    shown = _secret(slot)
    assert ts.clear_unpaired_mode(slot) is True
    assert _secret(slot) != shown
    assert oct(slot.env_file.stat().st_mode & 0o777) == "0o600"
    assert "JWT_SECRET=" in slot.env_file.read_text()


def test_clearing_a_paired_slot_keeps_its_secret(ts) -> None:
    slot = _slot(ts)
    ts.provision(slot)
    kept = _secret(slot)
    assert ts.clear_unpaired_mode(slot) is False
    assert _secret(slot) == kept


def test_reset_rotates_an_unpaired_slots_secret(ts, monkeypatch) -> None:
    slot = _slot(ts)
    ts.provision(slot)
    slot.unpaired_marker.write_text("")
    shown = _secret(slot)
    monkeypatch.setattr(ts, "require_lease", lambda _s: None)
    monkeypatch.setattr(ts, "pointed", lambda _s: REPO)
    monkeypatch.setattr(ts, "tmux", lambda *_a: None)
    monkeypatch.setattr(ts, "start", lambda *_a: 0.1)
    monkeypatch.setattr(ts, "login", lambda _s: None)
    ts.cmd_reset(argparse.Namespace(slot=2, timeout=1.0))
    assert _secret(slot) != shown and not slot.unpaired_marker.exists()


def test_release_rotates_an_unpaired_slots_secret(ts, monkeypatch) -> None:
    slot = _slot(ts)
    ts.provision(slot)
    slot.unpaired_marker.write_text("")
    shown = _secret(slot)
    monkeypatch.setattr(ts, "lease_info", lambda _s: {"pid": 1, "stale": False})
    ts.cmd_release(argparse.Namespace(slot=2))
    assert _secret(slot) != shown


def test_lease_drops_a_leftover_marker_rotates_and_stops_the_server(ts, monkeypatch) -> None:
    slot = _slot(ts)
    ts.provision(slot)
    slot.unpaired_marker.write_text("")
    shown = _secret(slot)
    monkeypatch.setattr(ts, "try_acquire", lambda s, _h: s.n == 2)
    monkeypatch.setattr(ts, "ensure_up", lambda *_a: None)
    monkeypatch.setattr(ts, "login", lambda _s: None)
    args = argparse.Namespace(pid=1, link=False, bonjour=False, timeout=1.0)
    assert ts.cmd_lease(args) == 0
    assert not slot.unpaired_marker.exists()
    assert ts.calls == ["stop"]
    assert _secret(slot) != shown



def _capture():
    from scripts import feature_capture
    return feature_capture


class FakeBrowser:

    def __init__(self) -> None:
        self.contexts: List[dict] = []

    def new_context(self, **kwargs):
        self.contexts.append(kwargs)
        page = type("Page", (), {})()
        return type("Ctx", (), {"new_page": lambda _s: page, "close": lambda _s: None})()


def _run(fc, tmp_path, spec, owned=True):
    slot = fc.Slot("http://127.0.0.1:8102", str(tmp_path / "auth-state.json"), "cloude-test2", 2, owned)
    calls: List[str] = []
    slot.unpair = lambda: calls.append("unpair")
    slot.api = lambda *a, **k: calls.append("api") or {"values": {}, "revision": 1}
    slot.set_preferences = lambda *a, **k: calls.append("prefs")
    slot.configure = lambda *a, **k: calls.append("configure")
    return fc.Run(slot, "f", spec), slot, calls


def test_unpaired_seed_unpairs_and_returns_before_any_signed_in_call(tmp_path) -> None:
    fc = _capture()
    run, _slot_, calls = _run(fc, tmp_path, {"unpaired": True, "shots": []})
    run.seed()
    assert calls == ["unpair"]


def test_paired_seed_does_not_unpair(tmp_path) -> None:
    fc = _capture()
    run, _slot_, calls = _run(fc, tmp_path, {"shots": []})
    run.seed()
    assert "unpair" not in calls and "api" in calls


def test_unpaired_capture_carries_no_storage_state(tmp_path, monkeypatch) -> None:
    fc = _capture()
    monkeypatch.setattr(fc, "MEDIA_DIR", tmp_path / "media")
    browser = FakeBrowser()
    run, _slot_, _calls = _run(fc, tmp_path, {"unpaired": True, "shots": []})
    run.capture(browser)
    assert "storage_state" not in browser.contexts[0]


def test_paired_capture_carries_the_slots_storage_state(tmp_path, monkeypatch) -> None:
    fc = _capture()
    monkeypatch.setattr(fc, "MEDIA_DIR", tmp_path / "media")
    browser = FakeBrowser()
    run, slot, _calls = _run(fc, tmp_path, {"shots": []})
    run.capture(browser)
    assert browser.contexts[0]["storage_state"] == slot.auth


def test_a_held_slot_refuses_an_unpaired_spec(tmp_path) -> None:
    fc = _capture()
    _run_, held, _c = _run(fc, tmp_path, {}, owned=False)
    specs = {"first-run-setup": {"unpaired": True}, "plugins-page": {}}
    with pytest.raises(fc.CaptureError, match="first-run-setup"):
        fc.refuse_unpaired_on_held_slot(held, specs)
    with pytest.raises(fc.CaptureError, match="lease its own"):
        held.__class__.unpair(held)
    owned = _run(fc, tmp_path, {})[1]
    fc.refuse_unpaired_on_held_slot(owned, specs)
    fc.refuse_unpaired_on_held_slot(held, {"plugins-page": {}})


def test_rotation_refuses_an_env_without_a_totp_line(ts) -> None:
    slot = _slot(ts)
    slot.env_file.write_text("JWT_SECRET=x\n")
    slot.unpaired_marker.write_text("")
    with pytest.raises(ts.Refused, match="no TOTP_SECRET"):
        ts.clear_unpaired_mode(slot)
    assert slot.env_file.read_text() == "JWT_SECRET=x\n"


def test_the_enrollment_mock_is_a_fixed_demo_answer() -> None:
    from src.api.enrollment_routes import _render_qr
    from src.core.owner_identity.otpauth import build_otpauth_uri

    spec = json.loads((REPO / "features" / "capture" / "first-run-setup.json").read_text(encoding="utf-8"))
    mock = next(m for m in spec["mocks"] if m["url"].endswith("/api/v1/auth/enrollment"))
    answer = json.loads((REPO / "features" / "capture" / mock["json_file"]).read_text(encoding="utf-8"))
    assert answer["account"] == "demo" and answer["secret"] == "A" * 32
    assert answer["otpauth_uri"] == build_otpauth_uri("A" * 32, "demo")
    assert answer["qr_image"] == _render_qr(answer["otpauth_uri"])


def test_a_mock_json_file_is_served_to_the_page(tmp_path) -> None:
    fc = _capture()
    routed: List[tuple] = []
    ctx = type("Ctx", (), {"route": lambda _s, url, fn: routed.append(url),
                           "add_init_script": lambda *_a: None})()
    browser = type("B", (), {"new_context": lambda _s, **_k: ctx})()
    spec = json.loads((REPO / "features" / "capture" / "first-run-setup.json").read_text(encoding="utf-8"))
    run, _slot_, _calls = _run(fc, tmp_path, spec)
    run.context(browser, {})
    assert routed == ["**/api/v1/auth/enrollment"]
