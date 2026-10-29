
import asyncio
import json

import pytest

from src.core.byoai import transport
from src.core.byoai.contracts import AgentRequest, ByoaiError, Connection, MissingKey, Target
from src.core.byoai.keys import KeyStore
from src.core.byoai.media import _common
from src.core.byoai.native import claude_cli, cli_run, codex_cli
from src.core.byoai.store import ByoaiStore

from tests.python.byoai.test_byoai_foundation import FakeKeychain, SECRET


def test_origin_change_clears_key_and_transport_refuses_an_unbound_origin(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({}))
    keychain = FakeKeychain()
    store = ByoaiStore(config, keys=KeyStore(backend=keychain))
    conn = store.add_connection(preset="openai", key=SECRET)

    store.update_connection(conn.id, base_url="HTTPS://API.OPENAI.COM.:443/v1")
    assert keychain.items and store.read().connections[0].key_host == "https://api.openai.com"

    store.update_connection(conn.id, base_url="http://api.openai.com/v1")
    assert not keychain.items and store.read().connections[0].key_host is None

    http_conn = Connection(id="o", preset="openai", base_url="http://api.openai.com/v1",
                           key_host="https://api.openai.com")
    with pytest.raises(MissingKey):
        asyncio.run(transport.raw(http_conn, SECRET, "GET", "/models"))
    port_conn = Connection(id="o", preset="openai", base_url="https://api.openai.com:8443/v1",
                           key_host="https://api.openai.com")
    with pytest.raises(MissingKey):
        asyncio.run(transport.raw(port_conn, SECRET, "GET", "/models"))


@pytest.mark.parametrize("bad", ["--dangerously-skip-permissions", "-x", ""])
def test_cli_values_that_could_be_flags_are_refused_before_any_spawn(monkeypatch, bad):
    async def never(*a, **kw):
        raise AssertionError("spawned")

    monkeypatch.setattr(cli_run, "spawn", never)
    conn = Connection(id="c1", preset="claude_cli")
    with pytest.raises(ByoaiError):
        claude_cli.build_args(model=None, isolate=True, tools_off=False, allowed_tools=("Read", bad))
    with pytest.raises(ByoaiError):
        claude_cli.build_args(model=bad or "-", isolate=True, tools_off=True)
    with pytest.raises(ByoaiError):
        asyncio.run(claude_cli.run_agent(Target(conn, "haiku"), None, AgentRequest(prompt="x", allowed_tools=(bad,))))
    with pytest.raises(ByoaiError):
        asyncio.run(claude_cli.run_agent(Target(conn, bad or "-"), None, AgentRequest(prompt="x")))
    with pytest.raises(ByoaiError):
        codex_cli.build_args(model=bad or "-", sandbox="read-only", cwd="/tmp/x", isolate=True)
    with pytest.raises(ByoaiError):
        asyncio.run(codex_cli.run_agent(Target(Connection(id="d", preset="codex_cli"), bad or "-"), None,
                                        AgentRequest(prompt="x")))
    claude_cli.build_args(model="us.anthropic.claude-haiku-4-5-v1:0", isolate=True, tools_off=False,
                          allowed_tools=("Read", "Bash(git log:*)", "mcp__srv__tool"),
                          permission_mode="plan", max_budget_usd=0.5)


def test_odd_modes_and_budgets_are_refused():
    for kw in ({"permission_mode": "--x"}, {"max_budget_usd": float("nan")}, {"max_budget_usd": True},
               {"max_budget_usd": -1}):
        with pytest.raises(ByoaiError):
            claude_cli.build_args(model=None, isolate=True, tools_off=True, **kw)
    with pytest.raises(ByoaiError):
        codex_cli.build_args(model=None, sandbox="--x", cwd="/tmp/x", isolate=True)
    with pytest.raises(ByoaiError):
        codex_cli.build_args(model=None, sandbox="read-only", cwd="-C", isolate=True)


def test_transcribe_test_with_no_clip_is_not_ok(monkeypatch):
    async def no_clip(_dir=None):
        return None

    async def never(*a, **kw):
        raise AssertionError("transcribe called with no clip")

    monkeypatch.setattr(_common, "get_test_clip", no_clip)
    result = asyncio.run(_common.speech_test(never, never, Target(Connection(id="e", preset="elevenlabs"), "m"),
                                             None, "transcribe"))
    assert result.ok is False and "could not test" in result.detail


def test_scrub_removes_the_key_as_a_provider_could_echo_it():
    key = "ab/cd+ef=gh" + "ZZ"
    forms = [key, "ab\\/cd+ef=ghZZ", "ab%2Fcd%2Bef%3DghZZ", "ab%2fcd%2bef%3dghZZ"]
    for form in forms:
        assert transport.scrub(f"echo {form} end", key) == "echo *** end"
    assert "ab\\/cd" in forms[1]


def test_a_key_the_keychain_will_not_delete_aborts_the_change(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{}")
    keychain = FakeKeychain()
    keychain.delete = lambda service, account: False
    store = ByoaiStore(config, keys=KeyStore(backend=keychain))
    conn = store.add_connection(preset="openai", key=SECRET)
    with pytest.raises(ByoaiError):
        store.clear_key(conn.id)
    assert store.read().connections[0].key_host == "https://api.openai.com"


def test_claude_with_no_cwd_runs_in_a_fresh_empty_directory(monkeypatch):
    seen = {}

    async def fake_spawn(argv, env, *, stdin, cwd, timeout, what):
        seen["cwd"] = cwd
        from src.core.provider_ledger import refresh_poke
        return refresh_poke.ChildResult(ran=True, exit_code=0, timed_out=False, duration_seconds=0.0,
                                        stdout=b'{"result":"ok"}')

    async def fake_command(connection, args):
        return ["claude", *args], {}

    monkeypatch.setattr(cli_run, "spawn", fake_spawn)
    monkeypatch.setattr(claude_cli, "_command", fake_command)
    asyncio.run(claude_cli.run_agent(Target(Connection(id="c1", preset="claude_cli"), "haiku"), None,
                                     AgentRequest(prompt="x")))
    import os
    assert "byoai-claude-" in seen["cwd"] and not os.path.exists(seen["cwd"])


def test_a_hand_built_target_gets_the_stored_connection(tmp_path):
    from src.core.byoai import calllog, registry
    from src.core.byoai.gateway import Gateway
    config = tmp_path / "config.json"
    config.write_text("{}")
    keys = KeyStore(backend=FakeKeychain())
    store = ByoaiStore(config, keys=keys)
    conn = store.add_connection(preset="openai", key=SECRET)
    gateway = Gateway(store, calllog.CallLog(tmp_path / "b.db"), keys, features=registry.FeatureRegistry())
    forged = Connection(id=conn.id, preset="openai", base_url="https://x.example", key_host="https://x.example")
    resolved = gateway.resolve(Target(forged, "m"), "chat")
    assert resolved.target.connection.base_url == "https://api.openai.com/v1"
    assert gateway._raw_resolve(Target(forged, "m"), None).target.connection.key_host == "https://api.openai.com"


def test_a_read_token_cannot_force_a_model_refresh():
    from src.core.mcp import byoai_tools
    from src.core.mcp.caller import AgentCaller
    from src.core.mcp.tools import ToolError
    caller = AgentCaller("s", "t", "s", token_name="x", scope="read")
    with pytest.raises(ToolError):
        asyncio.run(byoai_tools.ai_models_list(None, caller, {"connection_id": "c", "refresh": True}))


def test_a_locked_keychain_refuses_the_clear_and_leaves_config_untouched(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{}")
    keychain = FakeKeychain()
    store = ByoaiStore(config, keys=KeyStore(backend=keychain))
    conn = store.add_connection(preset="openai", key=SECRET)
    before = config.read_text()
    keychain.locked = True
    keychain.delete = lambda service, account: False
    with pytest.raises(ByoaiError, match="could not be reached"):
        store.clear_key(conn.id)
    with pytest.raises(ByoaiError, match="could not be reached"):
        store.update_connection(conn.id, base_url="http://api.openai.com/v1")
    assert config.read_text() == before and keychain.items


def test_a_key_already_absent_clears_without_error(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{}")
    keychain = FakeKeychain()
    store = ByoaiStore(config, keys=KeyStore(backend=keychain))
    conn = store.add_connection(preset="openai", key=SECRET)
    keychain.items.clear()
    assert store.clear_key(conn.id).key_host is None


def _gateway(tmp_path, enabled=True):
    from src.core.byoai import calllog, registry
    from src.core.byoai.gateway import Gateway
    config = tmp_path / "config.json"
    config.write_text("{}")
    keys = KeyStore(backend=FakeKeychain())
    store = ByoaiStore(config, keys=keys)
    conn = store.add_connection(preset="openai", key=SECRET)
    store.update_connection(conn.id, enabled=enabled)
    return conn, Gateway(store, calllog.CallLog(tmp_path / "b.db"), keys, features=registry.FeatureRegistry())


def test_a_switched_off_connection_never_discovers_and_cached_only_never_calls(tmp_path, monkeypatch):
    from src.core.byoai import gateway as gateway_module
    from src.core.byoai.contracts import NotConfigured

    async def never(*a, **kw):
        raise AssertionError("a keyed provider call was made")

    monkeypatch.setattr(gateway_module, "discover", never)
    conn, gateway = _gateway(tmp_path, enabled=False)
    with pytest.raises(NotConfigured):
        asyncio.run(gateway.list_models(conn.id))
    (tmp_path / "on").mkdir()
    conn, gateway = _gateway(tmp_path / "on")
    assert asyncio.run(gateway.list_models(conn.id, cached_only=True))[1] == []


def test_a_test_that_returns_not_ok_is_logged_as_failed(tmp_path, monkeypatch):
    from src.core.byoai import adapters
    from src.core.byoai.contracts import TestResult
    conn, gateway = _gateway(tmp_path)

    async def not_ok(*a, **kw):
        return TestResult(False, "chat", 1, None, "could not test")

    monkeypatch.setattr(adapters, "test", not_ok)
    assert asyncio.run(gateway.test(conn.id, "chat", "m")).ok is False
    assert gateway.calllog.recent(1)[0]["ok"] in (False, 0)


def test_claude_with_an_empty_or_relative_cwd_never_runs_in_the_servers_directory(monkeypatch):
    seen = []

    async def fake_spawn(argv, env, *, stdin, cwd, timeout, what):
        seen.append(cwd)
        from src.core.provider_ledger import refresh_poke
        return refresh_poke.ChildResult(ran=True, exit_code=0, timed_out=False, duration_seconds=0.0,
                                        stdout=b'{"result":"ok"}')

    async def fake_command(connection, args):
        return ["claude", *args], {}

    monkeypatch.setattr(cli_run, "spawn", fake_spawn)
    monkeypatch.setattr(claude_cli, "_command", fake_command)
    target = Target(Connection(id="c1", preset="claude_cli"), "haiku")
    asyncio.run(claude_cli.run_agent(target, None, AgentRequest(prompt="x", cwd="")))
    assert "byoai-claude-" in seen[0]
    with pytest.raises(ByoaiError):
        asyncio.run(claude_cli.run_agent(target, None, AgentRequest(prompt="x", cwd="relative/dir")))
    assert len(seen) == 1


@pytest.mark.parametrize("bad", ["us-east-1.example.net/", "x", "US-EAST-1", "us-east-1@evil"])
def test_a_region_cannot_choose_the_host(tmp_path, bad):
    config = tmp_path / "config.json"
    config.write_text("{}")
    store = ByoaiStore(config, keys=KeyStore(backend=FakeKeychain()))
    with pytest.raises(ByoaiError):
        store.add_connection(preset="bedrock", options={"region": bad})
    ok = store.add_connection(preset="bedrock", options={"region": "us-west-2"})
    assert ok.base_url == "https://bedrock-runtime.us-west-2.amazonaws.com/openai/v1"
