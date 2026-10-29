
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")

from src.api.auth import require_auth  # noqa: E402
from src.api.peer_auth import require_peer_sessions  # noqa: E402
from src.api.restart_routes import router as restart_router  # noqa: E402
from src.config import settings  # noqa: E402
from src.config.provider_accounts import ProviderAccount, managed_dir_for  # noqa: E402
from src.core import config_writer  # noqa: E402
from src.core.account_switch import launch_env, restart_account, session_pin, store  # noqa: E402
from src.core.account_switch.session_pin import PinError  # noqa: E402
from src.core.provider_ledger import accounts_store, managed_profiles  # noqa: E402
from tests.helpers.claude_profile import write_claude_profile  # noqa: E402
from tests.socket_guard import derive_test_socket  # noqa: E402


@pytest.fixture()
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    projects = tmp_path / ".claude" / "projects"
    projects.mkdir(parents=True)
    (tmp_path / ".claude" / "settings.json").write_text("{}")
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"agents": {}, "other_block": {"keep": 1}}))
    for account_id in ("work", "play"):
        managed_profiles.ensure_managed_dir(account_id)
        write_claude_profile(managed_dir_for(account_id))
        accounts_store.upsert_account(path, ProviderAccount(
            id=account_id, name=account_id, provider="claude",
            claude_config_dir=managed_dir_for(account_id), managed=True))
    managed_profiles.ensure_managed_dir("cx")
    accounts_store.upsert_account(path, ProviderAccount(
        id="cx", name="cx", provider="codex", codex_home=managed_dir_for("cx"), managed=True))
    accounts_store.upsert_account(path, ProviderAccount(
        id="handmade", name="handmade", provider="claude",
        claude_config_dir=str(tmp_path / "handmade"), managed=False))
    monkeypatch.setattr(settings, "auth_config_file", str(path), raising=False)
    settings._auth_config_cache = None
    return path




def test_ticked_saves_a_different_account_moves_it_and_unticked_clears(config):
    assert session_pin.pin_for(config, "u1") is None
    assert session_pin.apply_choice(config, "u1", "work", pinned=True) == "pinned"
    assert session_pin.pin_for(config, "u1") == "work"
    assert session_pin.apply_choice(config, "u1", "work", pinned=True) == "unchanged"
    assert session_pin.apply_choice(config, "u1", "play", pinned=True) == "pinned"
    assert session_pin.pin_for(config, "u1") == "play"
    assert session_pin.apply_choice(config, "u1", "work", pinned=False) == "cleared"
    assert session_pin.pin_for(config, "u1") is None
    assert session_pin.apply_choice(config, "u1", "work", pinned=False) == "unchanged"


def test_a_pin_is_per_session_and_leaves_the_rest_of_config_alone(config):
    session_pin.apply_choice(config, "u1", "work", pinned=True)
    session_pin.apply_choice(config, "u2", "play", pinned=True)
    document = config_writer.read_config(config)
    assert document["other_block"] == {"keep": 1}
    assert document[session_pin.PINS_KEY] == {"u1": "work", "u2": "play"}


def test_a_malformed_pin_block_reads_as_no_pins(config):
    document = json.loads(config.read_text())
    document[session_pin.PINS_KEY] = ["nope"]
    config.write_text(json.dumps(document))
    assert session_pin.pin_for(config, "u1") is None


def test_only_accounts_that_can_resume_are_offered(config):
    offered = {a.id for a in session_pin.launchable_accounts(config)}
    assert {"work", "play"} <= offered
    assert "cx" not in offered
    assert "handmade" not in offered
    (Path(managed_dir_for("play")) / "settings.json").unlink()
    (Path(managed_dir_for("play")) / "settings.json").write_text("{}")
    assert "play" not in {a.id for a in session_pin.launchable_accounts(config)}




def test_the_session_account_beats_the_global_pointer(config):
    store.set_active(config, "claude", "work")
    assert launch_env.account_env(config, claude_account="play") == {"CLAUDE_CONFIG_DIR": managed_dir_for("play")}
    assert launch_env.account_env(config) == {"CLAUDE_CONFIG_DIR": managed_dir_for("work")}


def test_the_built_in_login_removes_the_variable_even_when_another_is_active(config):
    store.set_active(config, "claude", "work")
    from src.core.provider_ledger.poller_scan import AUTO_DEFAULT_ACCOUNT_ID

    assert launch_env.account_env(config, claude_account=AUTO_DEFAULT_ACCOUNT_ID) == {"CLAUDE_CONFIG_DIR": None}


def test_a_gone_session_account_falls_back_to_the_global_pointer(config):
    store.set_active(config, "claude", "work")
    assert launch_env.account_env(config, claude_account="removed") == {"CLAUDE_CONFIG_DIR": managed_dir_for("work")}


def test_a_restart_is_refused_when_the_session_account_cannot_be_used(config):
    elsewhere = _profile("/somewhere/else")
    assert asyncio.run(launch_env.restart_refusal(
        "s", "n", config_path=config, read_profile=elsewhere, claude_account="handmade")) == launch_env.UNUSABLE_DETAIL
    assert asyncio.run(launch_env.restart_refusal(
        "s", "n", config_path=config, read_profile=elsewhere, claude_account="work")) is None


def _profile(value):
    from src.core.account_switch.pane_account import PaneProfile

    async def read(socket, name, variable):
        return PaneProfile(readable=True, value=value)

    return read




def test_requested_wins_then_the_pin_then_nothing(config):
    plan = asyncio.run(restart_account.resolve(config, session_uuid="u1", family="claude"))
    assert plan.account_id is None and not plan.chosen
    session_pin.apply_choice(config, "u1", "work", pinned=True)
    plan = asyncio.run(restart_account.resolve(config, session_uuid="u1", family="claude"))
    assert (plan.account_id, plan.chosen) == ("work", False)
    plan = asyncio.run(restart_account.resolve(
        config, session_uuid="u1", family="claude", requested="play", pinned_box=False))
    assert (plan.account_id, plan.chosen, plan.pinned_box) == ("play", True, False)
    assert asyncio.run(restart_account.persist(config, "u1", plan)) == "cleared"
    assert session_pin.pin_for(config, "u1") is None


def test_codex_and_unresumable_choices_are_refused(config):
    with pytest.raises(PinError):
        asyncio.run(restart_account.resolve(config, session_uuid="u1", family="codex", requested="work"))
    with pytest.raises(PinError):
        asyncio.run(restart_account.resolve(config, session_uuid="u1", family="claude", requested="cx"))
    with pytest.raises(PinError):
        asyncio.run(restart_account.resolve(config, session_uuid="u1", family="claude", requested="handmade"))
    session_pin.apply_choice(config, "u1", "work", pinned=True)
    assert asyncio.run(restart_account.resolve(config, session_uuid="u1", family="codex")).account_id is None


def test_a_request_with_no_account_never_touches_the_pin(config):
    session_pin.apply_choice(config, "u1", "work", pinned=True)
    plan = asyncio.run(restart_account.resolve(config, session_uuid="u1", family="claude"))
    assert asyncio.run(restart_account.persist(config, "u1", plan)) is None
    assert session_pin.pin_for(config, "u1") == "work"




@pytest.fixture()
def client(config):
    app = FastAPI()
    app.include_router(restart_router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    app.dependency_overrides[require_peer_sessions] = lambda: None
    with TestClient(app) as test_client:
        yield test_client


def _row(agent_type="claude"):
    return {"tmux_name": "cloude_x", "socket": "cloude", "agent_type": agent_type}


def test_the_dropdown_preselects_the_pin_else_the_active_account(client, config):
    url = "/api/v1/sessions/u1/restart/accounts"
    store.set_active(config, "claude", "work")

    async def running_on_play(*args, **kwargs):
        return "play"

    with patch("src.api.restart_account_routes._read_row", return_value=_row()), \
            patch("src.core.account_switch.pane_account.resolve_pane_account", running_on_play):
        reply = client.get(url)
        assert reply.status_code == 200, reply.text
        body = reply.json()
        assert {o["id"] for o in body["options"]} >= {"work", "play"}
        assert "cx" not in {o["id"] for o in body["options"]}
        assert (body["selected_id"], body["current_id"], body["pinned"]) == ("work", "play", False)
        assert [o["is_current"] for o in body["options"] if o["id"] == "play"] == [True]
        session_pin.apply_choice(config, "u1", "work", pinned=True)
        body = client.get(url).json()
        assert (body["selected_id"], body["current_id"], body["pinned"]) == ("work", "play", True)


def test_an_unlaunchable_active_account_falls_back_to_current_but_is_not_called_active(client, config):
    url = "/api/v1/sessions/u1/restart/accounts"
    store.set_active(config, "claude", "work")

    async def running_on_play(*args, **kwargs):
        return "play"

    with patch("src.api.restart_account_routes._read_row", return_value=_row()), \
            patch("src.core.account_switch.pane_account.resolve_pane_account", running_on_play):
        assert client.get(url).json()["active_id"] == "work"
        with patch.object(session_pin, "launchable_accounts", return_value=[a for a in session_pin.launchable_accounts(config) if a.id != "work"]):
            body = client.get(url).json()
    assert (body["selected_id"], body["active_id"], body["pinned"]) == ("play", None, False)


def test_the_dropdown_is_empty_for_codex_and_unknown_rows(client):
    url = "/api/v1/sessions/u1/restart/accounts"
    with patch("src.api.restart_account_routes._read_row", return_value=_row("codex")):
        assert client.get(url).json()["options"] == []
    with patch("src.api.restart_account_routes._read_row", return_value=None):
        assert client.get(url).json()["options"] == []




@pytest.mark.skipif(shutil.which("tmux") is None, reason="real tmux binary not available")
@pytest.mark.asyncio
async def test_respawn_launches_on_the_chosen_account_and_saves_the_box(config, tmp_path):
    from src.core.session_manager import SessionManager

    socket = derive_test_socket("acctpin")
    run = lambda *a: subprocess.run(["tmux", "-L", socket, *a], capture_output=True, text=True, timeout=15)  # noqa: E731
    run("new-session", "-d", "-s", "keeper", "-x", "80", "-y", "24")
    run("set-option", "-wg", "remain-on-exit", "on")
    try:
        run("new-session", "-d", "-s", "pinme", "-c", str(tmp_path), "-x", "80", "-y", "24",
            'sh -c "exit 0"')
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline and run("list-panes", "-t", "pinme", "-F", "#{pane_dead}").stdout.strip() != "1":
            time.sleep(0.1)
        seen = []

        async def spy_refusal(sock, name, **kwargs):
            seen.append(kwargs.get("claude_account"))
            return None

        with patch.object(SessionManager, "_load_session_metadata", return_value=None):
            manager = SessionManager()
        recorded = []

        async def spy_record(*args, **kwargs):
            recorded.append(kwargs.get("account_id"))

        with patch.object(launch_env, "restart_refusal", spy_refusal), \
                patch("src.core.launch_profiles.restart_seam.write_record", spy_record), \
                patch.object(SessionManager, "_agent_command_for_tmux_name", return_value="sh -c 'sleep 1'"), \
                patch.object(SessionManager, "_row_identity_for_tmux_name", return_value={"session_uuid": "u1"}):
            result = await manager.respawn_session(
                "pinme", socket_name=socket, account_id="work", account_pinned=True)
            assert result["ok"] is True
            assert result["account_id"] == "work" and result["account_pin"] == "pinned"
            assert session_pin.pin_for(config, "u1") == "work"
            await manager.respawn_session("pinme", socket_name=socket, live_restart_confirmed=True)
            await manager.respawn_session(
                "pinme", socket_name=socket, live_restart_confirmed=True, account_id="play", account_pinned=False)
            assert session_pin.pin_for(config, "u1") is None
            with pytest.raises(ValueError):
                await manager.respawn_session("pinme", socket_name=socket, account_id="cx")
        assert seen == ["work", "work", "play"]
        assert recorded == ["work", "work", "play"]
    finally:
        subprocess.run(["tmux", "-L", socket, "kill-server"], capture_output=True, check=False)
