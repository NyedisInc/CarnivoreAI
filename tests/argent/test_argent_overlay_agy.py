
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from src.config.launch_profiles import LaunchProfile
from src.core.argent import health, mint, overlay as overlay_module, overlay_agy, settings as argent_settings
from src.core.argent.overlay import SECRET_NAME, ArgentOverlay
from src.core.launch_profiles.resolve import LaunchRequest, resolve_launch
from src.core.sessions import launch_overlay

KEY = "FIXTURE-per-session-key-0123456789abcdef"
NOW = 1_000_000.0
GATEWAY = "https://gw.argent.test/t1"


@pytest.fixture
def on(monkeypatch):
    cfg = argent_settings.ArgentSettings(server_url="https://cp.argent.test", gateway_url=GATEWAY, enabled=True)
    state = {"mints": []}
    monkeypatch.setattr(overlay_module.settings_module, "read", lambda path=None: cfg)
    monkeypatch.setattr(health._poller, "latest", health.HealthReport(state=health.UP, mints_accepted=True, upstream_chain=True, body_cap_bytes=None, checked_at=NOW))

    async def fake_mint(ref, name, kind, *, transport=None):
        state["mints"].append((ref, kind))
        minted = mint.MintedKey(KEY)
        minted.agy_base = state.get("agy_base", "")
        return minted

    monkeypatch.setattr(mint, "mint_session_key", fake_mint)
    launch_overlay.register(ArgentOverlay(clock=lambda: NOW + 1))
    yield state
    launch_overlay.register(None)


def profile(script: str = 'agy "$@"', agent=True) -> LaunchProfile:
    body = {"id": "agy-test", "label": "agy", "harness": "custom", "custom_command": {"script": script}}
    if agent:
        body["agent"] = {"process": "agy", "rules": "agy"}
    return LaunchProfile.model_validate(body)


def launch(tmp_path: Path, prof: LaunchProfile):
    return resolve_launch(LaunchRequest(profiles=(prof,), agent_type=prof.id, scripts_dir=tmp_path))


def test_plan_tethers_and_materialize_mints_agy(on, tmp_path):
    plan = launch(tmp_path, profile())
    assert plan.overlay is not None and plan.overlay.tool == "agy" and plan.overlay.env_names == overlay_agy.ENV_NAMES
    assert "GEMINI_API_KEY" in plan.command and "GOOGLE_GEMINI_BASE_URL" in plan.command
    assert KEY not in json.dumps([plan.command, plan.argv_tail, plan.overlay.preamble])
    delivery = asyncio.new_event_loop().run_until_complete(ArgentOverlay(clock=lambda: NOW + 1).materialize(
        plan.overlay, launch_overlay.OverlayContext(harness="custom", session_ref="carnivore_agy", display_name="agy")))
    assert delivery.secrets == {SECRET_NAME: KEY} and on["mints"][0][1] == "agy" and KEY not in json.dumps(delivery.note)


def run_preamble(secret: str, base: str = "") -> list:
    n = overlay_module.AGY_BASE_NAME
    text = overlay_agy.preamble(f'_ak="${{{SECRET_NAME}-}}"; unset {SECRET_NAME}; _cb="${{{n}-}}"; unset {n}; ', GATEWAY + "/")
    out = subprocess.run(["sh", "-c", text + '; printf "%s|%s|%s" "${GEMINI_API_KEY-}" "${GOOGLE_GEMINI_BASE_URL-}" "$*"', "_", "-c", "abc"],
                         env={"PATH": "/usr/bin:/bin", SECRET_NAME: secret, **({overlay_module.AGY_BASE_NAME: base} if base else {})}, capture_output=True, text=True, timeout=20).stdout.split("|")
    return out


def test_preamble_exports_key_url_and_flag_only_when_tethered():
    assert run_preamble(KEY) == [KEY, GATEWAY, '--settings {"modelProvider":"gemini"} -c abc']
    assert run_preamble("-") == ["", "", "-c abc"]


def test_routed_base_is_delivered_as_a_tmux_env_beside_the_key(on, tmp_path):
    on["agy_base"] = "https://gw.argent.test/nyedis/gemini"
    plan = launch(tmp_path, profile())
    delivery = asyncio.new_event_loop().run_until_complete(ArgentOverlay(clock=lambda: NOW + 1).materialize(
        plan.overlay, launch_overlay.OverlayContext(harness="custom", session_ref="carnivore_cp", display_name="cp")))
    assert delivery.secrets == {SECRET_NAME: KEY, overlay_module.AGY_BASE_NAME: on["agy_base"]}


def test_routed_base_is_exported_and_vetted():
    routed = GATEWAY.rsplit("/", 1)[0] + "/nyedis/gemini"
    assert run_preamble(KEY, routed)[1] == routed
    assert run_preamble("-", routed)[1] == ""
    gw = "https://gw.argent.test"
    body = lambda url: {"launch_profile": {"tools": {"agy": {"base_url": url}}}}
    assert mint.routed_tool_base(body(gw + "/nyedis/gemini/"), gw, "agy") == gw + "/nyedis/gemini"
    for bad in ("https://evil.test/nyedis/gemini", "http://gw.argent.test/x", "https://gw.argent.test:1/x", "https://u:p@gw.argent.test/x", ""):
        assert mint.routed_tool_base(body(bad), gw, "agy") == "", bad


def test_direct_plan_and_other_profiles_are_untouched(on, tmp_path, monkeypatch):
    monkeypatch.setattr(health._poller, "latest", health.HealthReport(state=health.DOWN, mints_accepted=False, checked_at=NOW))
    down = launch(tmp_path, profile())
    assert down.overlay.preamble == "" and "GEMINI_API_KEY" not in down.command
    other = launch(tmp_path, profile('gemini "$@"', agent=False))
    assert other.overlay is None and "GEMINI_API_KEY" not in other.command
    launch_overlay.register(None)
    assert launch(tmp_path, profile()).overlay is None


def test_ca_bundle_adds_the_ca_to_system_roots_and_is_exported_only_when_tethered(tmp_path, monkeypatch):
    ca = tmp_path / "ca.pem"
    ca.write_text("-----BEGIN CERTIFICATE-----\nCA1\n-----END CERTIFICATE-----\n")
    roots = b"-----BEGIN CERTIFICATE-----\nROOT\n-----END CERTIFICATE-----\n"
    real_run = subprocess.run
    monkeypatch.setattr(overlay_agy.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=roots))
    state = tmp_path / "state"
    first = Path(overlay_agy.ca_bundle(str(ca), state))
    assert b"ROOT" in first.read_bytes() and b"CA1" in first.read_bytes()
    assert overlay_agy.ca_bundle(str(ca), state) == str(first)
    ca.write_text("-----BEGIN CERTIFICATE-----\nCA2\n-----END CERTIFICATE-----\n")
    second = Path(overlay_agy.ca_bundle(str(ca), state))
    assert second != first and not first.exists() and b"CA2" in second.read_bytes()
    assert overlay_agy.ca_bundle("", state) == "" and overlay_agy.ca_bundle(str(tmp_path / "missing.pem"), state) == ""
    tether = overlay_agy.preamble("_ak=k; ", "https://g.example", "", str(second))
    assert f"export SSL_CERT_FILE={second}" in tether
    assert "SSL_CERT_FILE" not in overlay_agy.preamble("_ak=k; ", "https://g.example")
    direct = real_run(["sh", "-c", overlay_agy.preamble("_ak=-; ", "https://g.example", "", str(second)) + '; echo "[${SSL_CERT_FILE:-none}]"'], capture_output=True, text=True).stdout
    assert "[none]" in direct
