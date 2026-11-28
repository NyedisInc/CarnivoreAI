
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import List, Sequence, Tuple

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.argent import status as status_routes
from src.api.auth import require_auth
from src.core.argent import cleanup, lifecycle, settings as argent_settings


def test_url_matches_gateway_matches_subpaths_and_rejects_other_hosts() -> None:
    gw = "https://gw.example.com:10443"
    assert cleanup.url_matches_gateway("https://gw.example.com:10443/nyedis/anthropic", gw) is True
    assert cleanup.url_matches_gateway("https://GW.EXAMPLE.COM:10443/", gw) is True
    assert cleanup.url_matches_gateway("https://api.anthropic.com", gw) is False
    assert cleanup.url_matches_gateway("https://gw.example.com:443/nyedis/anthropic", gw) is False
    assert cleanup.url_matches_gateway("https://gw.example.com:10443", "") is False


def test_scrub_settings_file_strips_argent_env_and_preserves_other_keys_and_non_argent_urls(tmp_path: Path) -> None:
    gw = "https://gw.example.com:10443"
    ca = str(tmp_path / "dataplane-ca.pem")

    shopify = tmp_path / "shopify_settings.local.json"
    shopify.write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": f"{gw}/nyedis/anthropic"}}), encoding="utf-8")
    assert cleanup.scrub_settings_file(shopify, gateway_url=gw, ca_path=ca) is True
    assert json.loads(shopify.read_text(encoding="utf-8")) == {}
    assert cleanup.scrub_settings_file(shopify, gateway_url=gw, ca_path=ca) is False

    mixed = tmp_path / "mixed.json"
    mixed.write_text(
        json.dumps({
            "permissions": {"allow": ["Bash(ls)"]},
            "env": {
                "ANTHROPIC_BASE_URL": f"{gw}/nyedis/anthropic",
                "ANTHROPIC_CUSTOM_HEADERS": "x-api-key: stale-placeholder",
                "NODE_EXTRA_CA_CERTS": ca,
                "MY_CUSTOM_FLAG": "keep-me",
            },
        }),
        encoding="utf-8",
    )
    assert cleanup.scrub_settings_file(mixed, gateway_url=gw, ca_path=ca) is True
    parsed = json.loads(mixed.read_text(encoding="utf-8"))
    assert parsed == {
        "permissions": {"allow": ["Bash(ls)"]},
        "env": {"MY_CUSTOM_FLAG": "keep-me"},
    }

    custom = tmp_path / "custom.json"
    original = json.dumps({
        "env": {
            "ANTHROPIC_BASE_URL": "https://my-local-litellm.example:4000",
            "ANTHROPIC_CUSTOM_HEADERS": "x-api-key: keep-mine",
        }
    })
    custom.write_text(original, encoding="utf-8")
    assert cleanup.scrub_settings_file(custom, gateway_url=gw, ca_path=ca) is False
    assert custom.read_text(encoding="utf-8") == original


def test_scrub_tmux_sessions_unsets_argent_vars_and_keeps_unrelated_urls() -> None:
    gw = "https://gw.example.com:10443"
    ca = "/Users/test/.config/argent/dataplane-ca.pem"
    unset_calls: List[Tuple[str, str]] = []

    def fake_tmux(args: Sequence[str]) -> Tuple[int, str]:
        if "list-sessions" in args:
            return 0, "carnivore_Shopify\ncarnivore_Custom\n"
        if "show-environment" in args:
            sess = args[args.index("-t") + 1]
            if sess == "carnivore_Shopify":
                return 0, (
                    "CARNIVORE_ARGENT_KEY=stale\n"
                    f"ANTHROPIC_BASE_URL={gw}/nyedis/anthropic\n"
                    "ANTHROPIC_CUSTOM_HEADERS=x-api-key: stale\n"
                    f"NODE_EXTRA_CA_CERTS={ca}\n"
                    "CLAUDE_CONFIG_DIR=/Users/test/.carnivore/accounts/a\n"
                )
            return 0, (
                "ANTHROPIC_BASE_URL=https://other-proxy.example:8443\n"
                "ANTHROPIC_CUSTOM_HEADERS=x-api-key: keep\n"
            )
        if "set-environment" in args:
            sess = args[args.index("-t") + 1]
            var = args[args.index("-u") + 1]
            unset_calls.append((sess, var))
            return 0, ""
        return 1, ""

    cleaned = cleanup.scrub_tmux_sessions(gateway_url=gw, ca_path=ca, socket_name="cloude", run_tmux=fake_tmux)
    assert cleaned == 1
    assert set(unset_calls) == {
        ("carnivore_Shopify", "CARNIVORE_ARGENT_KEY"),
        ("carnivore_Shopify", "ANTHROPIC_BASE_URL"),
        ("carnivore_Shopify", "ANTHROPIC_CUSTOM_HEADERS"),
        ("carnivore_Shopify", "NODE_EXTRA_CA_CERTS"),
    }


def test_scrub_argent_injections_cleans_projects_accounts_and_ca_bundles(tmp_path: Path) -> None:
    gw = "https://gw.example.com:10443"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    bundle = state_dir / "agy-ca-bundle-deadbeef12345678.pem"
    bundle.write_text("PEM", encoding="utf-8")
    keep_file = state_dir / "other.pem"
    keep_file.write_text("KEEP", encoding="utf-8")

    home = tmp_path / "home"
    acct_settings = home / ".carnivore" / "accounts" / "claude-a" / "settings.json"
    acct_settings.parent.mkdir(parents=True)
    acct_settings.write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": gw}}), encoding="utf-8")

    proj = tmp_path / "proj"
    proj_local = proj / ".claude" / "settings.local.json"
    proj_local.parent.mkdir(parents=True)
    proj_local.write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": f"{gw}/nyedis/anthropic"}}), encoding="utf-8")

    counts = cleanup.scrub_argent_injections(
        gateway_url=gw,
        state_dir=state_dir,
        socket_name=None,
        project_dirs=[proj],
        home=home,
    )
    assert counts == {"settings_files": 2, "tmux_sessions": 0, "ca_bundles": 1}
    assert json.loads(proj_local.read_text(encoding="utf-8")) == {}
    assert json.loads(acct_settings.read_text(encoding="utf-8")) == {}
    assert not bundle.exists()
    assert keep_file.exists()


def test_lifecycle_shutdown_and_switch_off_invoke_scrub(monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(cleanup, "scrub_live_install", lambda cfg=None: calls.append(cfg) or {"settings_files": 0, "tmux_sessions": 0, "ca_bundles": 0})

    async def noop(*_a, **_kw):
        return None

    class _FakeLogin:
        cancel = staticmethod(noop)

    class _FakeRuntime:
        login = _FakeLogin()

    monkeypatch.setattr(lifecycle, "get_runtime", lambda: _FakeRuntime())
    monkeypatch.setattr(lifecycle.fallback_spend, "stop", noop)
    monkeypatch.setattr(lifecycle.rollout, "stop", noop)
    monkeypatch.setattr(lifecycle.work_items, "stop", noop)
    monkeypatch.setattr(lifecycle.timeline, "stop", noop)
    monkeypatch.setattr(lifecycle.commits, "stop", lambda: None)
    monkeypatch.setattr(lifecycle.writeback, "stop", noop)
    monkeypatch.setattr(lifecycle.cards_sync, "stop", noop)
    monkeypatch.setattr(lifecycle.outage, "stop", lambda: None)
    monkeypatch.setattr(lifecycle.cost_poller, "stop", noop)
    monkeypatch.setattr(lifecycle.refresh, "stop", noop)
    monkeypatch.setattr(lifecycle.gateway_reach, "get", lambda: None)
    monkeypatch.setattr(lifecycle.poll_relay, "forget", lambda: None)
    monkeypatch.setattr(lifecycle.health, "stop", noop)

    asyncio.run(lifecycle._shutdown())
    assert len(calls) == 1

    before = argent_settings.ArgentSettings(server_url="https://s:18443", gateway_url="https://g:10443", enabled=True)
    after = argent_settings.ArgentSettings(server_url="https://s:18443", gateway_url="https://g:10443", enabled=False)
    state = {"cfg": before}
    monkeypatch.setattr(argent_settings, "read", lambda *_a, **_kw: state["cfg"])

    def fake_update(mutate_fn, *_a, **_kw):
        block = {"serverUrl": before.server_url, "gatewayUrl": before.gateway_url, "caPath": "", "enabled": before.enabled}
        mutate_fn(block)
        state["cfg"] = argent_settings.parse(block)
        return state["cfg"]

    monkeypatch.setattr(argent_settings, "update", fake_update)
    monkeypatch.setattr(status_routes.health, "poke", lambda: None)
    monkeypatch.setattr(status_routes, "_status_sync", lambda: {"enabled": state["cfg"].enabled})

    app = FastAPI()
    app.include_router(status_routes.router, prefix="/api/v1/argent")
    app.dependency_overrides[require_auth] = lambda: None
    res = TestClient(app).put("/api/v1/argent/settings", json={"enabled": False})
    assert res.status_code == 200
    assert len(calls) == 2
    assert calls[1] == before
