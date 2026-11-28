from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from src.config.launch_profiles import LaunchProfile
from src.core.argent import health, mint, overlay as overlay_module, settings as argent_settings
from src.core.argent.overlay import SECRET_NAME, ArgentOverlay
from src.core.launch_profiles.resolve import LaunchRequest, resolve_launch
from src.core.sessions import launch_overlay

KEY = "FIXTURE-per-session-key-0123456789abcdef"
NOW = 1_000_000.0


@pytest.fixture
def on(monkeypatch, tmp_path):
    cfg = argent_settings.ArgentSettings(server_url="https://cp.argent.test", gateway_url="https://gw.argent.test", ca_path="/s/ca.pem", enabled=True)
    state = {"mints": []}
    monkeypatch.setattr(overlay_module.settings_module, "read", lambda path=None: cfg)
    monkeypatch.setattr(health._poller, "latest", health.HealthReport(state=health.UP, mints_accepted=True, upstream_chain=True, body_cap_bytes=None, checked_at=NOW))

    async def fake_mint(ref, name, kind, *, transport=None):
        state["mints"].append((ref, kind))
        return KEY

    monkeypatch.setattr(mint, "mint_session_key", fake_mint)
    launch_overlay.register(ArgentOverlay(clock=lambda: NOW + 1))
    yield state
    launch_overlay.register(None)


def copilot_profile(script: str = 'copilot "$@"') -> LaunchProfile:
    return LaunchProfile.model_validate({"id": "copilot-test", "label": "Copilot", "harness": "custom", "custom_command": {"script": script}})


def launch(tmp_path: Path, profile: LaunchProfile):
    return resolve_launch(LaunchRequest(profiles=(profile,), agent_type=profile.id, scripts_dir=tmp_path))


def materialize(plan):
    return asyncio.new_event_loop().run_until_complete(ArgentOverlay(clock=lambda: NOW + 1).materialize(
        plan.overlay, launch_overlay.OverlayContext(harness="custom", session_ref="carnivore_cp", display_name="cp")))




def materialize(plan):
    return asyncio.new_event_loop().run_until_complete(ArgentOverlay(clock=lambda: NOW + 1).materialize(
        plan.overlay, launch_overlay.OverlayContext(harness="custom", session_ref="carnivore_cp", display_name="cp")))


def test_plan_carries_the_gateway_preamble_and_no_key(on, tmp_path):
    plan = launch(tmp_path, copilot_profile())
    assert plan.overlay is not None and plan.overlay.tool == "copilot" and plan.overlay.env_names == overlay_module.COPILOT_ENV_NAMES
    assert "COPILOT_PROVIDER_BASE_URL=" in plan.command and "https://gw.argent.test" in plan.command and "COPILOT_PROVIDER_TYPE=anthropic" in plan.command
    assert KEY not in json.dumps([plan.command, plan.argv_tail, plan.overlay.preamble])
    delivery = materialize(plan)
    assert delivery.secrets == {SECRET_NAME: KEY} and on["mints"][0][1] == "copilot" and KEY not in json.dumps(delivery.note)


def run_preamble(secret: str, base: str = "") -> dict:
    text = overlay_module.copilot_preamble("https://gw.argent.test", "/s/ca.pem").replace(overlay_module._read_key(), f'_ak="${{{SECRET_NAME}-}}"; unset {SECRET_NAME}; ').replace(
        overlay_module._read_tool_base(overlay_module.COPILOT_BASE_NAME, "https://gw.argent.test"), f'_cb="${{{overlay_module.COPILOT_BASE_NAME}-}}"; unset {overlay_module.COPILOT_BASE_NAME}; [ -n "$_cb" ] || _cb=https://gw.argent.test; ')
    names = ("COPILOT_PROVIDER_BASE_URL", "COPILOT_PROVIDER_TYPE", "COPILOT_PROVIDER_API_KEY", "COPILOT_MODEL", "NODE_EXTRA_CA_CERTS", SECRET_NAME)
    out = subprocess.run(["sh", "-c", text + "; " + "; ".join(f'printf "%s|" "${{{n}-}}"' for n in names)],
                         env={"PATH": "/usr/bin:/bin", SECRET_NAME: secret, **({overlay_module.COPILOT_BASE_NAME: base} if base else {}), "COPILOT_PROVIDER_BASE_URL": "stale", "COPILOT_PROVIDER_API_KEY": "stale"},
                         capture_output=True, text=True, timeout=20).stdout.split("|")
    return dict(zip(names, out))


def test_preamble_exports_the_gateway_and_clears_on_direct():
    assert run_preamble(KEY) == {"COPILOT_PROVIDER_BASE_URL": "https://gw.argent.test", "COPILOT_PROVIDER_TYPE": "anthropic", "COPILOT_PROVIDER_API_KEY": KEY,
                                 "COPILOT_MODEL": overlay_module.COPILOT_DEFAULT_MODEL,
                                 "NODE_EXTRA_CA_CERTS": "/s/ca.pem", SECRET_NAME: ""}
    assert set(run_preamble("-").values()) == {""}


def test_routed_base_is_exported_and_a_foreign_host_is_refused():
    routed = "https://gw.argent.test/nyedis/anthropic"
    assert run_preamble(KEY, routed)["COPILOT_PROVIDER_BASE_URL"] == routed
    assert run_preamble("-", routed)["COPILOT_PROVIDER_BASE_URL"] == ""
    body = lambda url: {"launch_profile": {"tools": {"copilot-cli": {"base_url": url}}}}
    gw = "https://gw.argent.test"
    assert mint.routed_tool_base(body(routed + "/"), gw, "copilot-cli") == routed
    for bad in ("https://evil.test/nyedis/anthropic", "http://gw.argent.test/x", "https://gw.argent.test:1/x", "https://u:p@gw.argent.test/x", "https://gw.argent.test/x?a=1", "https://gw.argent.test/x y", ""):
        assert mint.routed_tool_base(body(bad), gw, "copilot-cli") == "", bad
    assert mint.routed_tool_base({}, gw, "copilot-cli") == ""


def test_tether_off_goes_direct_without_a_preamble(on, tmp_path, monkeypatch):
    monkeypatch.setattr(health._poller, "latest", health.HealthReport(state=health.DOWN, mints_accepted=False, checked_at=NOW))
    plan = launch(tmp_path, copilot_profile())
    assert not plan.overlay.preamble and "COPILOT_PROVIDER" not in plan.command
    assert not materialize(plan).secrets and on["mints"] == []


def test_other_custom_profiles_and_switch_off_are_untouched(on, tmp_path):
    other = launch(tmp_path, copilot_profile('gemini "$@"'))
    assert other.overlay is None and "COPILOT_PROVIDER" not in other.command
    launch_overlay.register(None)
    off = launch(tmp_path, copilot_profile())
    assert off.overlay is None and "COPILOT_PROVIDER" not in off.command


def test_registration_tool_kind_for_a_copilot_custom_row(monkeypatch, tmp_path):
    from src.config import settings as app_settings
    from src.core.argent import registration

    gem = copilot_profile('gemini "$@"').model_copy(update={"id": "gem"})
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"launch_profiles": {"profiles": [copilot_profile().model_dump(mode="json"), gem.model_dump(mode="json")]}}))
    monkeypatch.setattr(app_settings, "auth_config_file", str(cfg))
    assert registration.tool_kind("custom", "copilot-test") == "copilot"
    assert registration.tool_kind("custom", "gem") == "other" and registration.tool_kind("custom", "") == "other" and registration.tool_kind("claude", "x") == "claude"


def test_claude_routed_base_is_exported_and_mint_picks_claude_code():
    gw, routed = "https://gw.argent.test", "https://gw.argent.test/nyedis/anthropic"

    def run(base: str) -> str:
        text = overlay_module.preamble(gw, "").replace(overlay_module._read_key(), f'_ak="${{{SECRET_NAME}-}}"; unset {SECRET_NAME}; ').replace(
            overlay_module._read_tool_base(overlay_module.CLAUDE_BASE_NAME, gw), f'_cb="${{{overlay_module.CLAUDE_BASE_NAME}-}}"; unset {overlay_module.CLAUDE_BASE_NAME}; [ -n "$_cb" ] || _cb={gw}; ')
        env = {"PATH": "/usr/bin:/bin", SECRET_NAME: KEY, **({overlay_module.CLAUDE_BASE_NAME: base} if base else {})}
        return subprocess.run(["sh", "-c", text + '; printf "%s" "$ANTHROPIC_BASE_URL"'], env=env, capture_output=True, text=True, timeout=20).stdout

    assert run(routed) == routed and run("") == gw
    body = {"launch_profile": {"tools": {"claude-code": {"base_url": routed + "/"}, "copilot-cli": {"base_url": "https://evil.test/x"}}}}
    assert mint.routed_tool_base(body, gw, "claude-code") == routed
