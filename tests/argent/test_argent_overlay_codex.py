
from __future__ import annotations

import json
import shlex
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
import structlog

from src.config.launch_profiles import LaunchProfile
from src.core.argent import codex_words, health, mint, overlay as overlay_module, overlay_codex, settings as argent_settings
from src.core.argent.overlay import SECRET_NAME, ArgentOverlay, codex_preamble
from src.core.launch_profiles import create_seam
from src.core.launch_profiles.resolve import LaunchRequest, resolve_launch
from src.core.sessions import codex_update, launch_overlay

KEY = "FIXTURE-per-session-key-0123456789abcdef"
GATEWAY, CA = "https://gw.argent.test:8443", "/etc/argent/dataplane-ca.pem"
NOW = 1_000_000.0


@pytest.fixture
def on(monkeypatch):
    cfg = argent_settings.ArgentSettings(server_url="https://cp.argent.test", gateway_url=GATEWAY, ca_path=CA, enabled=True)
    state = {"cfg": cfg, "mints": [], "version": "0.165.0"}
    monkeypatch.setattr(overlay_module.settings_module, "read", lambda path=None: state["cfg"])
    monkeypatch.setattr(health._poller, "latest", health.HealthReport(state=health.UP, mints_accepted=True, upstream_chain=True, body_cap_bytes=None, checked_at=NOW))
    monkeypatch.setattr(codex_update, "installed_codex_version", lambda finder=None: state["version"])

    async def fake_mint(ref, name, kind, *, transport=None):
        state["mints"].append((ref, kind))
        return KEY

    monkeypatch.setattr(mint, "mint_session_key", fake_mint)
    launch_overlay.register(ArgentOverlay(clock=lambda: NOW + 1))
    yield state
    launch_overlay.register(None)


def launch(tmp_path: Path):
    profile = LaunchProfile.model_validate({"id": "codex-test", "label": "Codex", "harness": "codex"})
    return resolve_launch(LaunchRequest(profiles=(profile,), agent_type="codex-test", model="gpt-5", scripts_dir=tmp_path))


def ctx(tmp_path: Path) -> launch_overlay.OverlayContext:
    return launch_overlay.OverlayContext(harness="codex", session_ref="carnivore_cx", working_dir=str(tmp_path), display_name="cx")


def run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


def assert_no_key(*haystacks: Any) -> None:
    for hay in haystacks:
        assert KEY not in json.dumps(hay, default=str), "the per-launch key leaked"


def test_flags_present_key_nowhere(on, tmp_path):
    plan = launch(tmp_path)
    assert plan.overlay is not None and plan.overlay.flags
    want = ['model_provider="argent"', 'model_providers.argent.base_url="${CARNIVORE_GATEWAY_CODEX_BASE}"',
            "model_providers.argent.requires_openai_auth=${CARNIVORE_GATEWAY_CODEX_AUTH}", 'model_providers.argent.wire_api="responses"',
            'model_providers.argent.env_http_headers={"x-api-key" = "CARNIVORE_GATEWAY_CODEX_KEY"}']
    for flag in want:
        assert flag in plan.overlay.flags and codex_words.quote_word(flag).replace("'", "'\"'\"'") in plan.command, flag
    assert SECRET_NAME in plan.command and overlay_codex.HEADER_ENV in plan.command
    with structlog.testing.capture_logs() as logs:
        prepared = run(create_seam.prepare(plan, overlay_ctx=ctx(tmp_path)))
    assert prepared.late == {SECRET_NAME: KEY, overlay_codex.AUTH_DELIVERY: "false"} and on["mints"] == [("carnivore_cx", "codex")]
    assert json.loads(prepared.record)["argent"] == {"tethered": True, "reason": "", "mint_epoch": int(NOW + 1)}
    assert_no_key(plan.command, plan.argv_tail, plan.overlay.flags, plan.env_set, plan.secret_refs, prepared.record, prepared.staged, logs)
    leaky = plan.command.replace(overlay_codex.HEADER_ENV, KEY)
    with pytest.raises(AssertionError):
        assert_no_key(leaky)


@pytest.mark.parametrize("mode,chatgpt,base,auth", [("token", True, "/nyedis/openai/v1", "false"), ("passthrough", True, "/nyedis/chatgpt/backend-api/codex", "true"),
                                                      ("passthrough", False, "/nyedis/openai/v1", "false")])
def test_auth_modes_route_and_expand_in_a_real_shell(on, tmp_path, monkeypatch, mode, chatgpt, base, auth):
    assert argent_settings.parse({}).codex_auth_mode == "token"
    on["cfg"] = argent_settings.ArgentSettings(server_url="https://cp.argent.test", gateway_url=GATEWAY, ca_path=CA, enabled=True, codex_auth_mode=mode)

    async def fake_mint(ref, name, kind, *, transport=None):
        minted = mint.MintedKey(KEY)
        minted.codex_base = f"{GATEWAY}/nyedis/openai/v1"
        minted.codex_chatgpt_base = f"{GATEWAY}/nyedis/chatgpt/backend-api/codex" if chatgpt else ""
        return minted

    monkeypatch.setattr(mint, "mint_session_key", fake_mint)
    plan = launch(tmp_path)
    prepared = run(create_seam.prepare(plan, overlay_ctx=ctx(tmp_path)))
    script = tmp_path / "w.sh"
    script.write_text(plan.overlay.preamble + "\nprintf '%s\\n' " + " ".join(codex_words.quote_word(w) for w in plan.overlay.flags) + "\n")
    out = subprocess.run(["/bin/sh", str(script)], env={"PATH": "/usr/bin:/bin", **prepared.late}, capture_output=True, text=True, timeout=30).stdout.splitlines()
    assert f'model_providers.argent.base_url="{GATEWAY}{base}"' in out and f"model_providers.argent.requires_openai_auth={auth}" in out
    assert codex_words.expand_words(plan.overlay.flags, {codex_words.BASE_ENV: GATEWAY + base, codex_words.AUTH_ENV: auth}) == [w for w in out]
    assert_no_key(plan.command, plan.overlay.flags, {k: v for k, v in prepared.late.items() if k != SECRET_NAME}, prepared.record)


def test_preamble_exports_the_header_variable_in_a_real_shell(tmp_path):
    d = tmp_path / "bin"
    d.mkdir()
    (d / "tmux").write_text(f'#!/bin/sh\n[ "$1" = show-environment ] && {{ echo "{SECRET_NAME}={KEY}"; exit 0; }}\nexit 0\n')
    (d / "tmux").chmod((d / "tmux").stat().st_mode | stat.S_IXUSR)

    def seen(preamble: str, **env: str) -> dict:
        script = tmp_path / "p.sh"
        script.write_text(preamble + f'\necho "HDR=${{{overlay_codex.HEADER_ENV}-unset}}"; echo "KEYVAR=${{{SECRET_NAME}-unset}}"; echo "CA=${{CODEX_CA_CERTIFICATE-unset}}"\n')
        out = subprocess.run(["/bin/sh", str(script)], env={"PATH": f"{d}:/usr/bin:/bin", **env}, capture_output=True, text=True, timeout=30).stdout
        return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)

    assert seen(codex_preamble(CA), **{SECRET_NAME: KEY}) == {"HDR": KEY, "KEYVAR": "unset", "CA": CA}
    assert seen(codex_preamble(""))["HDR"] == KEY
    direct = seen(codex_preamble(""), **{SECRET_NAME: "-", overlay_codex.HEADER_ENV: "stale"})
    assert direct["HDR"] == "unset" and direct["KEYVAR"] == "unset"
    bad = codex_preamble("").replace(f'export {overlay_codex.HEADER_ENV}="$_ak"', f'export {overlay_codex.HEADER_ENV}=WRONG')
    assert seen(bad, **{SECRET_NAME: KEY})["HDR"] != KEY


@pytest.mark.parametrize("version", ["0.164.9", "0.100.0", None, "garbage"])
def test_version_gate_goes_direct_with_the_named_reason(on, tmp_path, version):
    on["version"] = version
    plan = launch(tmp_path)
    assert plan.overlay is not None and not plan.overlay.flags and plan.overlay.preamble == ""
    assert "model_providers.argent" not in plan.command and SECRET_NAME not in plan.command
    prepared = run(create_seam.prepare(plan, overlay_ctx=ctx(tmp_path)))
    assert prepared.late == {} and json.loads(prepared.record)["argent"] == {"tethered": False, "reason": "codex headers unsupported", "mint_epoch": 0}
    assert on["mints"] == []


@pytest.mark.parametrize("version", ["0.165.0", "0.165.1-alpha.2", "1.0.0"])
def test_version_gate_accepts_the_floor_and_newer(on, tmp_path, version):
    on["version"] = version
    assert launch(tmp_path).overlay.flags


def test_down_gateway_codex_goes_direct(on, tmp_path, monkeypatch):
    monkeypatch.setattr(health._poller, "latest", health.HealthReport(state=health.DOWN, mints_accepted=True, upstream_chain=True, body_cap_bytes=None, checked_at=NOW))
    plan = launch(tmp_path)
    assert not plan.overlay.flags and "model_providers.argent" not in plan.command
    prepared = run(create_seam.prepare(plan, overlay_ctx=ctx(tmp_path)))
    assert json.loads(prepared.record)["argent"]["reason"] == "argent down at launch" and on["mints"] == []


def test_off_changes_nothing(on, tmp_path):
    with_flags = launch(tmp_path)
    on["cfg"] = argent_settings.ArgentSettings(server_url="https://cp.argent.test", gateway_url=GATEWAY, enabled=False)
    switch_off = launch(tmp_path)
    launch_overlay.register(None)
    feature_off = launch(tmp_path)
    assert with_flags.overlay is not None
    assert switch_off.overlay is None and feature_off.overlay is None and switch_off.command == feature_off.command
    assert "argent" not in feature_off.command.lower() and "ARGENT" not in feature_off.command
    prepared = run(create_seam.prepare(feature_off))
    assert prepared.late == {} and "argent" not in json.loads(prepared.record) and on["mints"] == []
