
from __future__ import annotations

import json
import os
import subprocess
import stat
from pathlib import Path
from typing import Any, List

import pytest
import structlog

from src.config import mcp_launch
from src.config.launch_profiles import LaunchProfile
from src.core.argent import health, mint, overlay as overlay_module, settings as argent_settings
from src.core.argent.overlay import ArgentOverlay, SECRET_NAME
from src.core.launch_profiles import create_seam
from src.core.launch_profiles.resolve import LaunchRequest, resolve_launch
from src.core.provider_ledger import refresh_poke
from src.core.sessions import launch_overlay
from src.core.sessions.launch_overlay import OverlayRefused
from src.core.tmux_backend import TmuxBackend

KEY = "FIXTURE-per-session-key-0123456789abcdef"
GATEWAY, CA = "https://gw.argent.test:8443", "/etc/argent/dataplane-ca.pem"
NOW = 1_000_000.0


def report(**kw: Any) -> health.HealthReport:
    base = dict(state=health.UP, mints_accepted=True, upstream_chain=True, body_cap_bytes=None, checked_at=NOW)
    return health.HealthReport(**{**base, **kw})


@pytest.fixture
def on(monkeypatch, tmp_path):
    cfg = argent_settings.ArgentSettings(server_url="https://cp.argent.test", gateway_url=GATEWAY, ca_path=CA, enabled=True)
    state = {"cfg": cfg, "mints": []}
    monkeypatch.setattr(argent_settings, "read", lambda path=None: state["cfg"])
    monkeypatch.setattr(overlay_module.settings_module, "read", lambda path=None: state["cfg"])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(health._poller, "latest", report())

    async def fake_mint(ref, name, kind, *, transport=None):
        state["mints"].append(ref)
        return KEY

    monkeypatch.setattr(mint, "mint_session_key", fake_mint)
    launch_overlay.register(ArgentOverlay(clock=lambda: NOW + 1))
    yield state
    launch_overlay.register(None)


def launch(tmp_path: Path, purpose: str = "pane"):
    profile = LaunchProfile.model_validate({"id": "claude-test", "label": "Claude", "harness": "claude"})
    return resolve_launch(LaunchRequest(profiles=(profile,), agent_type="claude-test", model="sonnet", scripts_dir=tmp_path,
                                        app_args=tuple(mcp_launch.codex_args("http://127.0.0.1:5001/mcp")[:0])), purpose)


def ctx(tmp_path: Path, wd: str = "") -> launch_overlay.OverlayContext:
    return launch_overlay.OverlayContext(harness="claude", session_ref="carnivore_api", working_dir=wd or str(tmp_path / "proj"), display_name="api")


def assert_no_key(*haystacks: Any) -> None:
    for hay in haystacks:
        assert KEY not in json.dumps(hay, default=str), "the per-launch key leaked"


def run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


def test_overlay_by_reference_key_nowhere_it_must_not_be(on, tmp_path):
    plan = launch(tmp_path)
    assert plan.overlay and SECRET_NAME in plan.command and GATEWAY in plan.command and CA in plan.command
    with structlog.testing.capture_logs() as logs:
        prepared = run(create_seam.prepare(plan, overlay_ctx=ctx(tmp_path)))
    assert prepared.late == {SECRET_NAME: KEY} and KEY not in prepared.staged.values()
    assert json.loads(prepared.record)["argent"] == {"tethered": True, "reason": "", "mint_epoch": int(NOW + 1)}
    assert on["mints"] == ["carnivore_api"]
    assert_no_key(plan.command, plan.argv_tail, plan.env_set, plan.secret_refs, prepared.record, prepared.staged, logs)
    leaky = plan.command.replace('"x-api-key: $_ak"', f'"x-api-key: {KEY}"')
    with pytest.raises(AssertionError):
        assert_no_key(leaky)


def test_create_delivers_by_stdin_after_start_never_in_start_env(on, tmp_path, monkeypatch):
    plan = launch(tmp_path)
    prepared = run(create_seam.prepare(plan, overlay_ctx=ctx(tmp_path)))
    backend = TmuxBackend.for_external(session_name="carnivore_api", working_dir=tmp_path, on_output=None, socket_name="cloude-test-p4a")
    sent: List[Any] = []

    async def fake_set(self, target, values, *, note):
        sent.append((target, dict(values), note))
        from src.core.tmux_command_batch import BatchOutcome
        return BatchOutcome(True, [])

    monkeypatch.setattr(TmuxBackend, "set_session_environment", fake_set)
    run(create_seam.deliver_late(backend, prepared))
    assert sent == [("=carnivore_api", {SECRET_NAME: KEY}, "launch_overlay_deliver")]
    assert SECRET_NAME not in {**prepared.staged}


def test_restart_replay_carries_the_key_in_the_stdin_staged_env(on, tmp_path):
    from src.core.launch_profiles import restart_seam

    class FakeSettings:
        def pane_launch_command(self, agent_type, *, model, extra_args, plan_sink, working_dir=None):
            plan = launch(tmp_path)
            plan_sink.append(plan)
            return plan.command

    replayed = run(restart_seam.resolve_replay(FakeSettings(), "claude-test", model="sonnet", extra_args=[], session_ref="carnivore_api",
                                               working_dir=str(tmp_path / "proj")))
    assert replayed.staged == {SECRET_NAME: KEY}
    assert_no_key(replayed.command, replayed.record)
    no_ref = run(restart_seam.resolve_replay(FakeSettings(), "claude-test", model="sonnet", extra_args=[]))
    assert no_ref.staged == {SECRET_NAME: "-"}


def fake_bin(tmp_path: Path, tmux_prints: str = "") -> Path:
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    (d / "claude").write_text('#!/bin/sh\necho "BASE=${ANTHROPIC_BASE_URL-unset}"\necho "HDR=${ANTHROPIC_CUSTOM_HEADERS-unset}"\n'
                              'echo "CA=${NODE_EXTRA_CA_CERTS-unset}"\necho "KEYVAR=${CARNIVORE_ARGENT_KEY-unset}"\n')
    (d / "tmux").write_text(f'#!/bin/sh\n[ "$1" = show-environment ] && {{ echo "{tmux_prints}"; exit 0; }}\nexit 0\n')
    for f in ("claude", "tmux"):
        (d / f).chmod((d / f).stat().st_mode | stat.S_IXUSR)
    return d


def shell(command: str, tmp_path: Path, **env: str) -> dict:
    base = {"PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin", "HOME": str(tmp_path), "ZDOTDIR": str(tmp_path)}
    script = tmp_path / "launch.sh"
    script.write_text(command + "\n")
    out = subprocess.run(["/bin/sh", str(script)], env={**base, **env}, capture_output=True, text=True, timeout=30).stdout
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def test_rendered_preamble_in_a_real_shell(on, tmp_path):
    command = launch(tmp_path).command
    fake_bin(tmp_path, tmux_prints=f"{SECRET_NAME}={KEY}")
    seen = shell(command, tmp_path, **{SECRET_NAME: KEY})
    assert seen == {"BASE": GATEWAY, "HDR": f"x-api-key: {KEY}", "CA": CA, "KEYVAR": "unset"}
    seen = shell(command, tmp_path)
    assert seen["HDR"] == f"x-api-key: {KEY}" and seen["KEYVAR"] == "unset"
    seen = shell(command, tmp_path, **{SECRET_NAME: "-", "ANTHROPIC_BASE_URL": "https://rc-set.example"})
    assert seen["BASE"] == "unset" and seen["HDR"] == "unset" and seen["KEYVAR"] == "unset"
    bad = command.replace('x-api-key: $_ak', "x-api-key: WRONG")
    assert shell(bad, tmp_path, **{SECRET_NAME: KEY})["HDR"] != f"x-api-key: {KEY}"


def test_untethered_launches_go_direct_with_a_named_reason(on, tmp_path, monkeypatch):
    cases = [
        (report(state=health.DOWN), "argent down at launch"),
        (report(checked_at=NOW - 500), "argent down at launch"),
        (report(mints_accepted=False), "argent down at launch"),
        (report(state=health.CAP_TOO_LOW, body_cap_bytes=1048576), "too large for gateway cap"),
    ]
    for rep, reason in cases:
        monkeypatch.setattr(health._poller, "latest", rep)
        plan = launch(tmp_path)
        assert plan.overlay is not None and plan.overlay.preamble == "" and SECRET_NAME not in plan.command
        prepared = run(create_seam.prepare(plan, overlay_ctx=ctx(tmp_path)))
        assert prepared.late == {} and json.loads(prepared.record)["argent"] == {"tethered": False, "reason": reason, "mint_epoch": 0}
    assert on["mints"] == []
    monkeypatch.setattr(health._poller, "latest", report())

    async def broken(*a, **k):
        raise mint.MintFailed("argent refused the mint (500)")

    monkeypatch.setattr(mint, "mint_session_key", broken)
    prepared = run(create_seam.prepare(launch(tmp_path), overlay_ctx=ctx(tmp_path)))
    assert prepared.late == {SECRET_NAME: "-"} and json.loads(prepared.record)["argent"]["reason"] == "argent down at launch"


def test_settings_override_is_not_tethered_and_refuse_direct_launch_refuses(on, tmp_path):
    proj = tmp_path / "proj" / ".claude"
    proj.mkdir(parents=True)
    (proj / "settings.json").write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:1"}}))
    prepared = run(create_seam.prepare(launch(tmp_path), overlay_ctx=ctx(tmp_path)))
    assert prepared.late == {SECRET_NAME: "-"} and json.loads(prepared.record)["argent"]["reason"] == "settings override"
    assert on["mints"] == []
    (proj / "settings.json").write_text(json.dumps({"env": {"FOO": "1"}}))
    assert run(create_seam.prepare(launch(tmp_path), overlay_ctx=ctx(tmp_path))).late == {SECRET_NAME: KEY}
    on["cfg"] = argent_settings.ArgentSettings(server_url="https://cp.argent.test", gateway_url=GATEWAY, enabled=True, refuse_direct_launch=True)
    (proj / "settings.json").write_text(json.dumps({"env": {"ANTHROPIC_CUSTOM_HEADERS": "x: y"}}))
    with pytest.raises(OverlayRefused) as refused:
        run(create_seam.prepare(launch(tmp_path), overlay_ctx=ctx(tmp_path)))
    assert refused.value.reason == "settings override"


def test_off_changes_nothing(on, tmp_path):
    with_overlay_off_switch = launch(tmp_path)
    on["cfg"] = argent_settings.ArgentSettings(server_url="https://cp.argent.test", gateway_url=GATEWAY, enabled=False)
    switch_off = launch(tmp_path)
    launch_overlay.register(None)
    feature_off = launch(tmp_path)
    assert with_overlay_off_switch.overlay is not None
    assert switch_off.overlay is None and feature_off.overlay is None and switch_off.command == feature_off.command
    assert SECRET_NAME not in feature_off.command and "ANTHROPIC_CUSTOM_HEADERS" not in feature_off.command
    prepared = run(create_seam.prepare(feature_off))
    assert prepared.late == {} and "argent" not in json.loads(prepared.record) and on["mints"] == []
    codex = resolve_launch(LaunchRequest(profiles=(LaunchProfile.model_validate({"id": "c", "label": "C", "harness": "codex"}),),
                                         agent_type="c", scripts_dir=tmp_path))
    assert codex.overlay is None


def test_poke_child_env_carries_no_gateway_env(monkeypatch):
    for name, value in {"ANTHROPIC_BASE_URL": GATEWAY, "ANTHROPIC_CUSTOM_HEADERS": f"x-api-key: {KEY}", SECRET_NAME: KEY}.items():
        monkeypatch.setenv(name, value)
    _, env = refresh_poke.build_claude_command(None, "/bin/true", "--version")
    assert not {"ANTHROPIC_BASE_URL", "ANTHROPIC_CUSTOM_HEADERS", SECRET_NAME} & set(env) and KEY not in json.dumps(env)
    assert {"ANTHROPIC_BASE_URL", "ANTHROPIC_CUSTOM_HEADERS", SECRET_NAME} <= set(refresh_poke.SUPPRESSING_ENV_VARS)
