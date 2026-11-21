
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



from src.core.argent import rebuild
from src.core.launch_profiles import restart_seam
from src.core.session_transcript_presence import ConversationPresence

UUID = "11111111-2222-3333-4444-555555555555"


@pytest.mark.parametrize("line,flags,model", [
    ("/u/bin/claude --resume " + UUID + " --name x --model opus --permission-mode plan", ("--permission-mode", "plan"), "opus"),
    ("claude --dangerously-skip-permissions --effort=high", ("--dangerously-skip-permissions", "--effort", "high"), ""),
    ("claude", (), ""),
])
def test_allow_listed_flags_are_copied_and_per_run_words_are_skipped(line, flags, model):
    got = rebuild.parse_flags("claude", line)
    assert got == rebuild.Rebuilt("claude", model, flags)
    assert rebuild.parse_flags("claude", line + " --chrome") == rebuild.Unrebuildable("unknown flag --chrome")


def test_codex_resume_subcommand_and_flags():
    assert rebuild.parse_flags("codex", "codex resume " + UUID + " -m gpt-x --sandbox read-only") == rebuild.Rebuilt("codex", "gpt-x", ("--sandbox", "read-only"))
    assert isinstance(rebuild.parse_flags("codex", "codex --dangerously-bypass-approvals-and-sandbox"), rebuild.Unrebuildable)


def test_secret_looking_value_and_unknown_shapes_make_the_row_unrebuildable_without_echoing_them():
    secret = "sk-ant-api03-" + "A1b2C3d4" * 6
    got = rebuild.parse_flags("claude", f"claude --model opus --api-key {secret}")
    assert isinstance(got, rebuild.Unrebuildable) and secret not in got.cause and "secret" in got.cause
    assert rebuild.parse_flags("claude", "claude --add-dir /nonexistent-dir-xyz") == rebuild.Unrebuildable("flag --add-dir names a folder that cannot be read")
    assert rebuild.parse_flags("claude", "claude stray") == rebuild.Unrebuildable("an unknown word on the command line")
    assert rebuild.parse_flags("gemini", "gemini") == rebuild.Unrebuildable("unknown agent family")
    here = str(Path(__file__).parent)
    assert rebuild.parse_flags("claude", "claude --add-dir " + here).flags == ("--add-dir", here)


@pytest.fixture
def pane(monkeypatch):
    box = {"measure": ("claude", "claude --model opus --permission-mode plan"), "present": "present"}
    monkeypatch.setattr(rebuild, "_measure", lambda socket, name: box["measure"])
    import src.core.session_transcript_presence as tp
    monkeypatch.setattr(tp, "family_conversation_presence", lambda *a, **k: ConversationPresence(outcome=box["present"]))
    return box


def test_missing_conversation_or_transcript_or_pane_each_give_a_cause(pane):
    ok = run(rebuild.rebuild_pane("cloude", REF, conversation_uuid=UUID, working_dir="/w"))
    assert ok == rebuild.Rebuilt("claude", "opus", ("--permission-mode", "plan"))
    assert run(rebuild.rebuild_pane("cloude", REF, conversation_uuid=None, working_dir="/w")) == rebuild.Unrebuildable("no conversation yet")
    pane["present"] = "absent"
    assert run(rebuild.rebuild_pane("cloude", REF, conversation_uuid=UUID, working_dir="/w")) == rebuild.Unrebuildable("the conversation transcript was not found")
    pane["measure"] = (None, "the pane process could not be read")
    pane["present"] = "present"
    assert run(rebuild.rebuild_pane("cloude", REF, conversation_uuid=UUID, working_dir="/w")).cause == "the pane process could not be read"


def test_rebuilt_launch_goes_through_the_overlay_with_resume_and_flags(env, pane, monkeypatch):
    seen = {}

    async def fake_resolve(settings, agent_type, **kw):
        seen.update(agent_type=agent_type, **kw)
        return restart_seam.ReplayedLaunch(command="CMD", record="{}")

    monkeypatch.setattr(restart_seam, "resolve_replay", fake_resolve)
    got = run(restart_seam.replay_for_restart(None, None, "cloude", REF, model=None, extra_args=["--resume", UUID],
                                              rebuild_adopted=True, conversation_uuid=UUID))
    assert got.command == "CMD"
    assert seen["agent_type"] == "claude" and seen["model"] == "opus" and seen["session_ref"] == REF
    assert seen["extra_args"] == ["--resume", UUID, "--permission-mode", "plan"]
    assert env["alerts"] == [] and row_state.rows("ten_1") == []


def test_unrebuildable_row_is_listed_once_never_launched_and_the_error_carries_the_cause(env, pane, monkeypatch):
    called = []

    async def fake_resolve(*a, **k):
        called.append(1)

    monkeypatch.setattr(restart_seam, "resolve_replay", fake_resolve)
    pane["measure"] = ("claude", "claude --chrome")
    for _ in range(2):
        with pytest.raises(rebuild.CannotRebuild, match="cannot rebuild launch command: unknown flag --chrome"):
            run(restart_seam.replay_for_restart(None, None, "cloude", REF, model=None, extra_args=None, rebuild_adopted=True, conversation_uuid=UUID))
    assert called == [] and env["mints"] == []
    assert env["alerts"] == [notices.UNTETHERED_PREFIX + REF]
    listed = row_state.rows("ten_1")
    assert listed == [{"session_ref": REF, "working_dir": "", "state": row_state.NOT_TETHERED, "reason": "cannot rebuild launch command: unknown flag --chrome"}]


def test_feature_off_or_no_flag_rebuilds_nothing(env, pane, monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("must not rebuild")

    monkeypatch.setattr(rebuild, "rebuild_pane", boom)
    assert run(restart_seam.replay_for_restart(None, None, "cloude", REF, model=None, extra_args=None, rebuild_adopted=False)) is None
    launch_overlay.register(None)
    assert run(restart_seam.replay_for_restart(None, None, "cloude", REF, model=None, extra_args=None, rebuild_adopted=True, conversation_uuid=UUID)) is None
