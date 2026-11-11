
from __future__ import annotations

import asyncio
import json
import stat
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
import structlog

from src.config import settings as app_settings
from src.config.launch_profiles import LaunchProfile
from src.core.argent import health, mint, upstream, upstream_registry, overlay as overlay_module, overlay_chain, overlay_codex, settings as argent_settings
from src.core.argent.overlay import SECRET_NAME, ArgentOverlay
from src.core.argent.runtime import Runtime, set_runtime
from src.core.argent.store import ArgentStore
from src.core.byoai.contracts import Connection
from src.core.launch_profiles import create_seam
from src.core.launch_profiles.render import STAGING_PREFIX
from src.core.launch_profiles.resolve import LaunchRequest, resolve_launch
from src.core.sessions import codex_update, launch_overlay

KEY = "FIXTURE-per-session-key-0123456789abcdef"
PROVIDER_KEY = "sk-or-PROVIDER-key-9876543210zyxwvutsrq"
GATEWAY, CA = "https://gw.argent.test:8443", "/etc/argent/dataplane-ca.pem"
NOW = 1_000_000.0
OPENROUTER = Connection(id="or", preset="openrouter", label="or", base_url="https://openrouter.ai/api/v1", key_host="https://openrouter.ai", key_hint="tsrq")
LOCAL = Connection(id="lm", preset="lmstudio", label="lm", base_url="http://127.0.0.1:1234/v1")


def fixture(name: str) -> Any:
    return json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "argent" / name).read_text())


def report(**kw: Any) -> health.HealthReport:
    base = dict(state=health.UP, mints_accepted=True, upstream_chain=True, body_cap_bytes=None, checked_at=NOW)
    return health.HealthReport(**{**base, **kw})


@pytest.fixture
def on(monkeypatch, tmp_path):
    state = {"cfg": argent_settings.ArgentSettings(server_url="https://cp.argent.test", gateway_url=GATEWAY, ca_path=CA, enabled=True), "mints": [], "calls": [], "status": 200}
    sd = tmp_path / "state"
    sd.mkdir()
    monkeypatch.setattr(app_settings, "state_dir_override", sd)
    store = ArgentStore(sd)
    store.set_login("ten_1", "id_1", "Fixture Person", 3600)
    set_runtime(Runtime(store=store, tokens=type("T", (), {"read": staticmethod(lambda tenant: "cli-token")})(), login=None))
    monkeypatch.setattr(upstream_registry.settings_module, "read", lambda path=None: state["cfg"])

    def serve(request: httpx.Request) -> httpx.Response:
        state["calls"].append(request)
        return httpx.Response(state["status"], json=fixture("upstreams_list.json") if state["status"] == 200 else {"error": {"code": "not_found", "message": "x"}})

    state["transport"] = httpx.MockTransport(serve)
    monkeypatch.setattr(overlay_module.settings_module, "read", lambda path=None: state["cfg"])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(health._poller, "latest", report())
    monkeypatch.setattr(codex_update, "installed_codex_version", lambda finder=None: "0.165.0")

    async def fake_mint(ref, name, kind, *, transport=None):
        state["mints"].append(ref)
        return KEY

    async def fake_materialize(plan):
        return {f"{STAGING_PREFIX}{i}": PROVIDER_KEY for i, _ in enumerate(plan.secret_refs)}

    monkeypatch.setattr(mint, "mint_session_key", fake_mint)
    monkeypatch.setattr(create_seam, "materialize", fake_materialize)
    monkeypatch.setattr(codex_update, "installed_codex_version", lambda finder=None: "0.165.0")
    launch_overlay.register(ArgentOverlay(clock=lambda: NOW + 1, transport=state["transport"]))
    yield state
    launch_overlay.register(None)
    set_runtime(None)


def profile(harness: str, conn: Connection, **kw: Any) -> LaunchProfile:
    return LaunchProfile.model_validate({"id": f"{harness}-ep", "harness": harness, "label": "ep", "model": {"mode": "fixed", "value": "m-1"},
                                         "endpoint": {"mode": "connection", "connection_id": conn.id}, **kw})


def launch(tmp_path: Path, conn: Connection = OPENROUTER, harness: str = "claude"):
    return resolve_launch(LaunchRequest(profiles=(profile(harness, conn),), agent_type=f"{harness}-ep", connections=(conn,), scripts_dir=tmp_path), "pane")


def ctx(tmp_path: Path, harness: str = "claude") -> launch_overlay.OverlayContext:
    return launch_overlay.OverlayContext(harness=harness, session_ref="carnivore_api", working_dir=str(tmp_path / "proj"), display_name="api")


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def assert_no_key(*haystacks: Any) -> None:
    for hay in haystacks:
        text = json.dumps(hay, default=str)
        assert KEY not in text and PROVIDER_KEY not in text, "a key leaked"


def fake_bin(tmp_path: Path) -> None:
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    (d / "claude").write_text('#!/bin/sh\necho "BASE=${ANTHROPIC_BASE_URL-unset}"\nprintf "HDR=%s\\n" "$(printf %s "${ANTHROPIC_CUSTOM_HEADERS-unset}" | tr "\\n" "|")"\n'
                              'echo "TOKEN=${ANTHROPIC_AUTH_TOKEN-unset}"\necho "APIKEY=[${ANTHROPIC_API_KEY-unset}]"\n')
    (d / "tmux").write_text('#!/bin/sh\nexit 0\n')
    for f in ("claude", "tmux"):
        (d / f).chmod((d / f).stat().st_mode | stat.S_IXUSR)


def shell(command: str, tmp_path: Path, **env: str) -> dict:
    script = tmp_path / "launch.sh"
    script.write_text(command + "\n")
    base = {"PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin", "HOME": str(tmp_path), "ZDOTDIR": str(tmp_path)}
    out = subprocess.run(["/bin/sh", str(script)], env={**base, **env}, capture_output=True, text=True, timeout=30).stdout
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def test_claude_connection_is_chained_key_only_in_the_header_of_a_real_shell(on, tmp_path):
    plan = launch(tmp_path)
    assert plan.overlay and plan.overlay.chained and not plan.overlay.replaces_flags
    with structlog.testing.capture_logs() as logs:
        prepared = run(create_seam.prepare(plan, overlay_ctx=ctx(tmp_path)))
    assert prepared.late == {SECRET_NAME: KEY} and json.loads(prepared.record)["argent"] == {"tethered": True, "reason": "", "mint_epoch": int(NOW + 1), "chained": True}
    assert_no_key(plan.command, plan.argv_tail, plan.env_set, plan.secret_refs, prepared.record, logs)
    leaky = plan.command.replace('$_pk', PROVIDER_KEY)
    with pytest.raises(AssertionError):
        assert_no_key(leaky)
    fake_bin(tmp_path)
    seen = shell(plan.command, tmp_path, **{SECRET_NAME: KEY, f"{STAGING_PREFIX}0": PROVIDER_KEY})
    assert seen["BASE"] == GATEWAY and seen["TOKEN"] == "carnivore" and seen["APIKEY"] == "[]"
    assert seen["HDR"] == f"x-api-key: {KEY}|x-argent-upstream-url: https://openrouter.ai/api|x-argent-upstream-key: {PROVIDER_KEY}"
    direct = shell(plan.command, tmp_path, **{SECRET_NAME: "-", f"{STAGING_PREFIX}0": PROVIDER_KEY})
    assert direct["BASE"] == "https://openrouter.ai/api" and direct["TOKEN"] == PROVIDER_KEY and "argent" not in direct["HDR"]


def test_env_row_profile_is_chained_and_a_keyless_one_sends_no_key_header(on, tmp_path):
    p = LaunchProfile.model_validate({"id": "claude-env", "harness": "claude", "label": "e", "env": [{"name": "ANTHROPIC_BASE_URL", "value": "https://api.example.com/x"}]})
    plan = resolve_launch(LaunchRequest(profiles=(p,), agent_type="claude-env", model="sonnet", scripts_dir=tmp_path), "pane")
    assert plan.overlay and plan.overlay.chained
    fake_bin(tmp_path)
    seen = shell(plan.command, tmp_path, **{SECRET_NAME: KEY})
    assert seen["BASE"] == GATEWAY and seen["HDR"] == f"x-api-key: {KEY}|x-argent-upstream-url: https://api.example.com/x"


def test_only_a_registered_public_upstream_chains_and_the_check_precedes_the_mint(on, tmp_path):
    unlisted = Connection(id="x", preset="openrouter", label="x", base_url="https://unlisted.example.org/v1", key_host="https://unlisted.example.org", key_hint="abcd")
    plan = launch(tmp_path, unlisted)
    assert plan.overlay.chained and plan.overlay.upstream_url == "https://unlisted.example.org"
    prepared = run(create_seam.prepare(plan, overlay_ctx=ctx(tmp_path)))
    assert prepared.late.get(SECRET_NAME, "-") == "-" and on["mints"] == [], "an unlisted host must not chain or mint"
    assert json.loads(prepared.record)["argent"] == {"tethered": False, "reason": "upstream not registered in argent", "mint_epoch": 0}
    assert [c.url.path for c in on["calls"]] == ["/v1/my/upstreams"] and on["calls"][0].headers["authorization"] == "Bearer cli-token"
    again = launch(tmp_path, unlisted)
    assert not again.overlay.chained and again.overlay.reason == "upstream not registered in argent" and GATEWAY not in again.command and len(on["calls"]) == 1
    assert launch(tmp_path).overlay.chained
    assert json.loads(run(create_seam.prepare(launch(tmp_path), overlay_ctx=ctx(tmp_path))).record)["argent"]["tethered"] is True and on["mints"]
    for private in ("http://127.0.0.1:1234/v1", "http://192.168.1.20:11434/v1", "http://studio.home.lan:1234/v1"):
        conn = Connection(id="lm", preset="lmstudio", label="lm", base_url=private)
        plan = launch(tmp_path, conn)
        assert not plan.overlay.chained and plan.overlay.reason == "upstream on a private network" and GATEWAY not in plan.command
    assert upstream.is_private_network("http://10.0.0.5") and not upstream.is_private_network("https://openrouter.ai/api")


def test_missing_route_means_chaining_unavailable_and_a_denial_code_maps_to_its_reason(on, tmp_path):
    on["status"] = 404
    prepared = run(create_seam.prepare(launch(tmp_path), overlay_ctx=ctx(tmp_path)))
    assert prepared.late.get(SECRET_NAME, "-") == "-" and on["mints"] == [] and json.loads(prepared.record)["argent"]["reason"] == "chaining not ready"
    denied = fixture("upstream_denied_403.json")["error"]["code"]
    assert upstream.reason_for_denial(denied) == "upstream not registered in argent"
    assert upstream.reason_for_denial("argent_upstream_private_network") == "upstream on a private network" and upstream.reason_for_denial("conflict") == ""


def test_gateway_without_chaining_launches_direct_with_a_named_reason(on, tmp_path, monkeypatch):
    monkeypatch.setattr(health._poller, "latest", report(upstream_chain=False))
    plan = launch(tmp_path)
    assert plan.overlay.reason == "chaining not ready" and not plan.overlay.chained and GATEWAY not in plan.command and SECRET_NAME not in plan.command
    assert json.loads(run(create_seam.prepare(plan, overlay_ctx=ctx(tmp_path))).record)["argent"]["reason"] == "chaining not ready"
    monkeypatch.setattr(health._poller, "latest", report(state=health.DOWN))
    assert json.loads(run(create_seam.prepare(launch(tmp_path), overlay_ctx=ctx(tmp_path))).record)["argent"]["reason"] == "argent down at launch"


def test_codex_connection_chain_flags_hold_names_only(on, tmp_path):
    conn = Connection(id="or", preset="openrouter", label="or", base_url="https://openrouter.ai/api/v1", key_host="https://openrouter.ai", key_hint="tsrq")
    plan = launch(tmp_path, conn, "codex")
    assert plan.overlay and plan.overlay.chained and plan.overlay.replaces_flags
    words = list(plan.overlay.flags)
    assert f'model_providers.carnivore-or.base_url="{GATEWAY}"' in words and not any("openrouter.ai" in w for w in words)
    headers = next(w for w in words if "env_http_headers" in w)
    assert overlay_codex.HEADER_ENV in headers and overlay_chain.UPSTREAM_URL_ENV in headers and "CARNIVORE_OR_API_KEY" in headers
    assert plan.command.count("base_url") == 1
    assert_no_key(plan.command, plan.argv_tail, words)
    assert f"export {overlay_chain.UPSTREAM_URL_ENV}=https://openrouter.ai/api/v1;" in plan.overlay.preamble


def test_off_changes_nothing(on, tmp_path):
    chained = launch(tmp_path)
    on["cfg"] = argent_settings.ArgentSettings(server_url="https://cp.argent.test", gateway_url=GATEWAY, enabled=False)
    switch_off = launch(tmp_path)
    launch_overlay.register(None)
    feature_off = launch(tmp_path)
    assert chained.overlay is not None and switch_off.overlay is None and feature_off.overlay is None and switch_off.command == feature_off.command
    assert GATEWAY not in feature_off.command and "x-argent-upstream" not in feature_off.command
    assert "argent" not in json.loads(run(create_seam.prepare(feature_off)).record)


def test_the_upstream_key_header_is_a_detected_secret_shape():
    from src.core import message_model_secrets as secrets
    hits = secrets.scan_text(f"x-argent-upstream-key: {PROVIDER_KEY}")
    assert hits, "the upstream key header line must be detected"
