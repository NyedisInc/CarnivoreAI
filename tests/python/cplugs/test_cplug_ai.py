
from __future__ import annotations

import asyncio
import copy
from dataclasses import replace

import pytest

from src.config.byoai import TargetRef
from src.core.byoai import adapters, calllog, registry
from src.core.byoai.contracts import ChatResult, EmbedResult, Usage
from src.core.byoai.gateway import Gateway
from src.core.byoai.keys import KeyStore
from src.core.byoai.store import ByoaiStore
from src.cplugs.host import ai_budget, plugin_ai, runtime, state as owner_state
from src.cplugs.sdk import ManifestError
from src.cplugs.sdk.context import CapabilityMissing
from src.cplugs.sdk.definition import CplugDefinition
from src.cplugs.sdk.manifest import parse_manifest

FID = "cplug.demoai.summary"
EID = "cplug.demoai.vec"
MANIFEST = {
    "schema": 1, "id": "demoai", "name_key": "cplug.demoai.name", "description_key": "cplug.demoai.description",
    "version": "1.0.0", "icon": "list", "author": "test", "min_app_version": "1.12.20", "tier": "builtin",
    "default_enabled": False, "surfaces": {}, "settings_schema": {"version": 1, "fields": {}},
    "permissions": {"app": [f"ai_features:{FID}", f"ai_features:{EID}"]},
    "ai_features": {"summary": {"capability": "chat", "calls_per_day": 2, "tokens_per_day": 500},
                    "vec": {"capability": "embed", "calls_per_day": 5, "tokens_per_day": 5000}},
}


class _NoKeychain:

    def state(self, service, account): return "absent"
    def read(self, service, account): return None
    def write(self, service, account, secret): raise AssertionError("no key is written here")
    def delete(self, service, account): return False


@pytest.fixture
def rig(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text("{}")
    store = ByoaiStore(config, keys=KeyStore(backend=_NoKeychain()))
    gateway = Gateway(store, calllog.CallLog(tmp_path), KeyStore(backend=_NoKeychain()))
    seen = []

    async def chat(protocol, target, key, request):
        seen.append(("chat", protocol, request))
        return ChatResult(text="ok", usage=Usage(input_tokens=100, output_tokens=50))

    async def embed(protocol, target, key, inputs):
        seen.append(("embed", protocol, inputs))
        return EmbedResult(vectors=((0.1, 0.2),), usage=Usage(input_tokens=10))

    monkeypatch.setattr(adapters, "chat", chat)
    monkeypatch.setattr(adapters, "embed", embed)
    definition = CplugDefinition(manifest=parse_manifest(copy.deepcopy(MANIFEST)))
    monkeypatch.setattr(runtime, "_definitions", (definition,))
    monkeypatch.setattr(registry, "DEFAULT", registry.FeatureRegistry())
    plugin_ai.register_features((definition,))
    host = runtime.Host(tmp_path, publish=lambda topic: None)
    host.ai_gateway = lambda: gateway
    local = store.add_connection(preset="ollama")
    store.set_feature(FID, TargetRef(connection=local.id, model="m"))
    store.set_feature(EID, TargetRef(connection=local.id, model="e"))
    store.set_default("chat", TargetRef(connection=local.id, model="m"))
    grant(host, [f"ai_features:{FID}", f"ai_features:{EID}"])
    return host, store, gateway, seen, tmp_path


def grant(host, perms):
    owner_state.update(host.state_dir, runtime.find("demoai").manifest, None, lambda s: replace(s, enabled=True, grants=tuple(perms)))


def call(host, feature, capability, data):
    return asyncio.run(host.context("demoai").ai.call(feature, capability, data))


def refused(host, feature, capability, data):
    with pytest.raises(plugin_ai.AiRefused) as err:
        call(host, feature, capability, data)
    return err.value.code


def test_chat_goes_through_a_host_built_request_and_is_budgeted(rig):
    host, _, gateway, seen, tmp = rig
    secret = "ghp_" + "aB3dE5fG7hJ9kL1mN3pQ5rS7tV9wX1yZ3aB5"
    out = call(host, FID, "chat", {"prompt": f"summarise {secret} please", "max_tokens": 99999})
    assert out == {"output": "ok"}
    kind, protocol, request = seen[0]
    assert (protocol, request.tools, request.system, dict(request.extra), request.json_schema) == ("openai_chat", (), None, {}, None)
    assert request.max_tokens == plugin_ai.MAX_OUTPUT_TOKENS
    assert secret not in request.messages[0].content and "[secret:" in request.messages[0].content
    assert ai_budget.AiBudget(tmp).today("demoai", FID) == (1, 150)
    assert gateway.calllog.recent(5)[0]["feature"] in (FID, EID)
    assert call(host, EID, "embed", {"inputs": ["a"]}) == {"output": [[0.1, 0.2]]}


@pytest.mark.parametrize("key", ["tools", "allowed_tools", "mcp_config", "mcp", "cwd", "permission_mode", "model", "system", "extra", "json_schema"])
def test_a_plugin_cannot_pass_tools_mcp_cwd_or_a_permission_mode(rig, key):
    host, _, _, seen, _ = rig
    assert refused(host, FID, "chat", {"prompt": "hi", key: "x"}) == "option_not_allowed"
    assert refused(host, EID, "embed", {"inputs": ["hi"], key: "x"}) == "option_not_allowed"
    assert seen == []


def test_agent_ungranted_foreign_and_unrouted_features_are_refused(rig):
    host, store, _, seen, _ = rig
    assert refused(host, FID, "agent", {"prompt": "hi"}) == "capability_not_allowed"
    assert refused(host, FID, "embed", {"inputs": ["hi"]}) == "bad_input"
    assert refused(host, "cplug.other.summary", "chat", {"prompt": "hi"}) == "not_granted"
    assert refused(host, "changelog.headline", "chat", {"prompt": "hi"}) == "not_granted"
    grant(host, [f"ai_features:{EID}"])
    assert refused(host, FID, "chat", {"prompt": "hi"}) == "not_granted"
    grant(host, [f"ai_features:{FID}"])
    store.set_feature(FID, None)
    assert refused(host, FID, "chat", {"prompt": "hi"}) == "not_routed"
    assert seen == []


def test_a_provider_that_can_run_tools_is_refused(rig):
    host, store, _, seen, _ = rig
    store.set_feature(FID, TargetRef(connection=store.add_connection(preset="codex_cli").id, model="gpt"))
    assert refused(host, FID, "chat", {"prompt": "hi"}) == "provider_not_allowed"
    store.set_feature(FID, TargetRef(connection=store.add_connection(preset="claude_cli").id, model="haiku"))
    assert seen == []
    assert call(host, FID, "chat", {"prompt": "hi"}) == {"output": "ok"}
    assert seen[0][1] == "claude_cli"


def test_output_is_truncated_and_claude_cli_with_user_config_is_refused(rig, monkeypatch):
    host, store, _, seen, _ = rig
    conn = store.add_connection(preset="claude_cli")
    store.set_feature(FID, TargetRef(connection=conn.id, model="haiku"))

    async def long_chat(protocol, target, key, request):
        return ChatResult(text="x" * 50_000, usage=None)

    monkeypatch.setattr(adapters, "chat", long_chat)
    assert len(call(host, FID, "chat", {"prompt": "hi"})["output"]) == plugin_ai.MAX_OUTPUT_CHARS
    assert refused(host, FID, "chat", {"prompt": " /compact"}) == "bad_input"
    monkeypatch.setattr("src.core.byoai.native.cli_run.isolated", lambda c: False)
    assert refused(host, FID, "chat", {"prompt": "hi"}) == "provider_not_allowed"
    assert seen == []


def test_refusals_are_labelled_by_plugin_and_rate_limited(rig, monkeypatch):
    host, _, gateway, _, _ = rig
    monkeypatch.setattr(plugin_ai, "MAX_REFUSAL_ROWS", 3)
    for _ in range(6):
        assert refused(host, "changelog.headline", "chat", {"prompt": "hi"}) == "not_granted"
    rows = gateway.calllog.recent(20)
    assert len(rows) == 3
    assert all(r["feature"] == "cplug.demoai" and "cplug demoai refused" in r["error"] for r in rows)


def test_the_per_day_budget_is_enforced_and_logged(rig):
    host, _, gateway, seen, tmp = rig
    for _ in range(2):
        call(host, FID, "chat", {"prompt": "hi"})
    assert refused(host, FID, "chat", {"prompt": "hi"}) == "budget_exceeded"
    assert len(seen) == 2
    assert "budget_exceeded" in gateway.calllog.recent(1)[0]["error"]
    clock = [ai_budget.AiBudget(tmp)._clock()]
    tomorrow = ai_budget.AiBudget(tmp, clock=lambda: clock[0] + 86400)
    assert tomorrow.reserve("demoai", FID, 2, 500) is None
    spent = ai_budget.AiBudget(tmp)
    spent.add_tokens("demoai", EID, 5000)
    assert refused(host, EID, "embed", {"inputs": ["hi"]}) == "budget_exceeded"


@pytest.mark.parametrize("mutate, message", [
    (lambda m: m["ai_features"]["summary"].update(capability="agent"), "never agent"),
    (lambda m: m["ai_features"]["summary"].update(tools=["x"]), "exactly"),
    (lambda m: m["ai_features"]["summary"].update(cwd="/"), "exactly"),
    (lambda m: m["ai_features"]["summary"].update(calls_per_day=0), "calls_per_day"),
    (lambda m: m["ai_features"]["summary"].update(tokens_per_day=10**9), "tokens_per_day"),
    (lambda m: m["permissions"]["app"].append("ai_features:cplug.other.x"), "must match"),
    (lambda m: m["permissions"]["app"].remove(f"ai_features:{EID}"), "must match"),
])
def test_a_manifest_that_asks_for_more_than_chat_or_embed_is_refused(mutate, message):
    raw = copy.deepcopy(MANIFEST)
    parse_manifest(raw)
    mutate(raw)
    with pytest.raises(ManifestError, match=message):
        parse_manifest(raw)


def test_ctx_ai_is_absent_until_a_feature_is_granted(rig):
    host, *_ = rig
    grant(host, [])
    with pytest.raises(CapabilityMissing, match="ai_features"):
        host.context("demoai").ai
    grant(host, [f"ai_features:{EID}"])
    assert host.context("demoai").ai is not None
    assert registry.get_feature(FID).capability == "chat"
