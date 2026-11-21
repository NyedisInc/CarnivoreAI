
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest

from src.config import settings as app_settings
from src.core.argent import detector, health, mint, notices, row_state, settings as argent_settings
from src.core.argent import overlay as overlay_module
from src.core.argent.device_login import DeviceLogin
from src.core.argent.lifecycle import PORT_NAME
from src.core.argent.overlay import ArgentOverlay
from src.core.argent.runtime import Runtime, set_runtime
from src.core.argent.store import ArgentStore
from src.core.argent.token_store import TokenStore
from src.core.sessions import launch_overlay
from src.core.sessions.launch_overlay import OverlayContext
from src.plugins.sdk import ports

NOW = 1_000_000.0
TOKEN = "FIXTURE-asicli-not-a-secret"
KEY_1, KEY_2 = "FIXTURE-per-session-key-one-0123456789abcdef", "FIXTURE-per-session-key-two-0123456789abcdef"
REF = "carnivore_api"


class Keychain:
    def __init__(self) -> None:
        self.items: Dict[Any, str] = {}

    def write_password(self, service: str, account: str, secret: str, replace: bool = True) -> None:
        self.items[(service, account)] = secret

    def read_password(self, service: str, account: str) -> Any:
        return self.items.get((service, account))

    def delete_password(self, service: str, account: str) -> bool:
        return self.items.pop((service, account), None) is not None


def run(coro: Any) -> Any:
    return asyncio.new_event_loop().run_until_complete(coro)


def minted(key: str, key_id: str) -> mint.MintedKey:
    value = mint.MintedKey(key)
    value.key_id = key_id
    return value


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(app_settings, "state_dir_override", state)
    cfg = argent_settings.ArgentSettings(server_url="https://cp.argent.test", gateway_url="https://gw.argent.test", ca_path="", enabled=True)
    box: Dict[str, Any] = {"cfg": cfg, "mints": [], "revokes": [], "revoke_status": 200, "alerts": [], "state": state, "tmp": tmp_path}
    monkeypatch.setattr(argent_settings, "read", lambda path=None: box["cfg"])
    monkeypatch.setattr(overlay_module.settings_module, "read", lambda path=None: box["cfg"])
    monkeypatch.setattr(mint.settings_module, "read", lambda path=None: box["cfg"])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(health._poller, "latest", health.HealthReport(state=health.UP, mints_accepted=True, upstream_chain=True, body_cap_bytes=None, checked_at=NOW))
    store, tokens = ArgentStore(state), TokenStore(Keychain())
    store.set_login("ten_1", "id_1", "Fixture Person", 3600)
    tokens.write("ten_1", TOKEN)
    set_runtime(Runtime(store=store, tokens=tokens, login=DeviceLogin(store, tokens)))
    keys = iter([minted(KEY_1, "k1"), minted(KEY_2, "k2"), minted("FIXTURE-key-three", "k3")])

    async def fake_mint(ref, name, kind, *, transport=None):
        box["mints"].append(ref)
        return next(keys)

    monkeypatch.setattr(mint, "mint_session_key", fake_mint)
    monkeypatch.setattr(notices.service, "raise_alert", lambda key, **kw: box["alerts"].append(key))

    def handler(request: httpx.Request) -> httpx.Response:
        box["revokes"].append(request.url.path)
        return httpx.Response(box["revoke_status"], json={})

    box["overlay"] = ArgentOverlay(clock=lambda: NOW + 1, transport=httpx.MockTransport(handler))
    launch_overlay.register(box["overlay"])
    yield box
    launch_overlay.register(None)
    set_runtime(None)
    ports.unregister(PORT_NAME)


def launch(box: Dict[str, Any], wd: str = "") -> OverlayContext:
    ctx = OverlayContext(harness="claude", session_ref=REF, working_dir=wd or str(box["tmp"] / "proj"), display_name="api")
    plan = box["overlay"].plan("claude", "pane")
    run(box["overlay"].materialize(plan, ctx))
    return ctx


def test_restart_mints_fresh_and_revokes_the_old_key_only_after_confirmation(env):
    launch(env)
    run(launch_overlay.confirm(REF))
    assert env["revokes"] == []
    launch(env)
    assert env["mints"] == [REF, REF] and env["revokes"] == []
    run(launch_overlay.confirm(REF))
    assert env["revokes"] == ["/v1/my/agent-sessions/k1/revoke"]
    run(launch_overlay.confirm(REF))
    assert env["revokes"] == ["/v1/my/agent-sessions/k1/revoke"]
    with pytest.raises(AssertionError):
        assert env["revokes"] == ["/v1/my/agent-sessions/k1/revoke", "/v1/my/agent-sessions/k2/revoke"]


def test_a_failed_revoke_is_kept_and_retried_and_no_key_value_is_stored(env):
    launch(env)
    run(launch_overlay.confirm(REF))
    launch(env)
    env["revoke_status"] = 500
    run(launch_overlay.confirm(REF))
    assert env["revokes"] == ["/v1/my/agent-sessions/k1/revoke"]
    env["revoke_status"] = 200
    launch(env)
    run(launch_overlay.confirm(REF))
    assert sorted(env["revokes"][1:]) == ["/v1/my/agent-sessions/k1/revoke", "/v1/my/agent-sessions/k2/revoke"]
    run(launch_overlay.confirm(REF))
    assert len(env["revokes"]) == 3
    raw = sqlite3.connect(env["state"] / "argent.db").execute("SELECT group_concat(key_id) FROM row_keys").fetchone()[0]
    dump = json.dumps([list(r) for r in sqlite3.connect(env["state"] / "argent.db").execute("SELECT * FROM row_state")]) + str(raw)
    assert KEY_1 not in dump and KEY_2 not in dump
    assert "k3" in str(sqlite3.connect(env["state"] / "argent.db").execute("SELECT key_id FROM row_keys").fetchall())


def test_untethered_notice_once_per_row_until_it_tethers_again(env, monkeypatch):
    monkeypatch.setattr(health._poller, "latest", health.HealthReport(state=health.DOWN, mints_accepted=False, upstream_chain=False, body_cap_bytes=None, checked_at=NOW))
    launch(env)
    launch(env)
    assert env["alerts"] == [notices.UNTETHERED_PREFIX + REF]
    assert env["mints"] == []
    run(launch_overlay.confirm(REF))
    assert row_state.rows("ten_1")[0]["state"] == row_state.NOT_TETHERED and row_state.rows("ten_1")[0]["reason"] == "argent down at launch"
    monkeypatch.setattr(health._poller, "latest", health.HealthReport(state=health.UP, mints_accepted=True, upstream_chain=True, body_cap_bytes=None, checked_at=NOW))
    launch(env)
    run(launch_overlay.confirm(REF))
    monkeypatch.setattr(health._poller, "latest", health.HealthReport(state=health.DOWN, mints_accepted=False, upstream_chain=False, body_cap_bytes=None, checked_at=NOW))
    launch(env)
    assert env["alerts"] == [notices.UNTETHERED_PREFIX + REF] * 2


def test_detector_flags_overrides_and_a_row_tethered_while_off_and_writes_nothing(env):
    proj = env["tmp"] / "proj"
    (proj / ".claude").mkdir(parents=True)
    ctx = launch(env)
    run(launch_overlay.confirm(REF))
    ports.register(PORT_NAME, {"on": True})
    clean = detector.detect("ten_1", feature_on=True)
    assert clean == {"shared_gateway_env": False, "findings": []}
    settings_file = proj / ".claude" / "settings.json"
    settings_file.write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": "https://gw.example"}}))
    user_file = env["tmp"] / "cfg" / "settings.json"
    user_file.parent.mkdir()
    user_file.write_text(json.dumps({"env": {"ANTHROPIC_CUSTOM_HEADERS": "x-api-key: shared"}}))
    before = (settings_file.read_bytes(), user_file.read_bytes())
    found = detector.detect("ten_1", feature_on=True)
    assert found["shared_gateway_env"] is True
    assert found["findings"] == [{"session_ref": REF, "kind": "settings_override", "reason": "settings override"}]
    env["cfg"] = argent_settings.ArgentSettings(server_url="https://cp.argent.test", gateway_url="https://gw.argent.test", ca_path="", enabled=False)
    assert detector.detect("ten_1", feature_on=True)["findings"][0]["kind"] == "tethered_while_off"
    assert (settings_file.read_bytes(), user_file.read_bytes()) == before and ctx
    row_state.record_launch("ten_1", "other", working_dir=str(proj), tethered=False, reason="settings override", key_id="")
    run(launch_overlay.confirm("other"))
    assert all(f["session_ref"] != "other" for f in detector.detect("ten_1", feature_on=True)["findings"])


def test_feature_off_records_nothing_and_makes_no_call(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(app_settings, "state_dir_override", state)
    launch_overlay.register(None)
    run(launch_overlay.confirm(REF))
    assert not (state / "argent.db").exists()
    assert launch_overlay.plan_for("claude", "pane") is None
