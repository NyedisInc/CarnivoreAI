
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict

from src.plugins.host import plugin_fold, runtime, state as owner_state
from tests.python.cplugs.reviewboard.harness import make_env


def store_old(state_dir: Path, enabled: bool, saved: Dict[str, Any]) -> None:
    path = owner_state.state_path(state_dir)
    document = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"cplugs": {}}
    document.setdefault("cplugs", {})["publicboard"] = {"enabled": enabled, "grants": ["agent_writes", "notify"], "settings": saved, "revision": 4}
    path.write_text(json.dumps(document), encoding="utf-8")


def saved_settings(env: Any) -> Dict[str, Any]:
    return dict(owner_state.get(env.host.state_dir, runtime.find("reviewboard").manifest).settings)


def test_an_enabled_old_plugin_turns_public_links_on_with_its_settings(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    store_old(env.host.state_dir, True, {"port": 8190, "hostnames": "review.example.com", "trustedProxies": "10.0.0.2", "bindAddress": "127.0.0.1"})
    written = plugin_fold.migrate(env.host.state_dir)
    assert written["reviewboard"]["publicLinksEnabled"] is True
    after = saved_settings(env)
    assert after["publicLinksEnabled"] is True and after["port"] == 8190 and after["hostnames"] == "review.example.com"
    assert after["trustedProxies"] == "10.0.0.2" and after["boardsRoot"]


def test_an_off_old_plugin_stays_off_and_a_second_run_changes_nothing(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    store_old(env.host.state_dir, False, {"port": 8191})
    plugin_fold.migrate(env.host.state_dir)
    first = saved_settings(env)
    assert first["publicLinksEnabled"] is False and first["port"] == 8191
    assert plugin_fold.migrate(env.host.state_dir) == {} and saved_settings(env) == first


def test_the_notify_grant_is_never_carried(tmp_path: Path) -> None:
    env = make_env(tmp_path)
    manifest = runtime.find("reviewboard").manifest
    owner_state.update(env.host.state_dir, manifest, None, lambda st: replace(st, grants=("agent_writes",)))
    before = owner_state.get(env.host.state_dir, manifest).grants
    assert "notify" not in before, "the fixture must not pre-grant the permission the test is about"
    store_old(env.host.state_dir, True, {})
    plugin_fold.migrate(env.host.state_dir)
    after = owner_state.get(env.host.state_dir, manifest).grants
    assert "notify" not in after and after == before
