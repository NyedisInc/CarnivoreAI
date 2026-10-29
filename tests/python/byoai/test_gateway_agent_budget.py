
import pytest

from src.config.byoai import TargetRef
from src.core.byoai import gateway as gateway_module
from src.core.byoai.calllog import CallLog
from src.core.byoai.gateway import Gateway
from src.core.byoai.keys import KeyStore
from src.core.byoai.native import claude_cli, cli_run
from src.core.byoai.store import ByoaiStore
from src.core.provider_ledger import refresh_poke
from tests.python.byoai.test_byoai_native_cli import Recorder
from tests.python.byoai.test_byoai_routes import FakeKeychain

PROMPT = "ZEBRA-PROMPT-TEXT"


@pytest.fixture
def routed(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text("{}")
    keys = KeyStore(backend=FakeKeychain())
    store = ByoaiStore(config, keys=keys)
    conn = store.add_connection(preset="claude_cli", label="claude")
    store.set_feature("budget.test", TargetRef(connection=conn.id, model="sonnet"),
                      expected_revision=store.read().revision)
    gateway_module.set_gateway(Gateway(store, CallLog(tmp_path), keys))
    rec = Recorder(b'{"result":"ok","total_cost_usd":0.001,"usage":{"input_tokens":3,"output_tokens":2}}')
    monkeypatch.setattr(cli_run, "spawn", rec)
    monkeypatch.setattr(claude_cli, "_login_unusable", lambda profile, account: False)
    monkeypatch.setattr(refresh_poke, "resolve_claude_binary", lambda: "/abs/claude")
    yield rec
    gateway_module.set_gateway(None)


@pytest.mark.asyncio
async def test_agent_forwards_the_budget_and_no_budget_means_no_flag(routed):
    result = await gateway_module.agent("budget.test", PROMPT, max_budget_usd=1.0)
    assert result.text == "ok"
    argv = routed.calls[0]["argv"]
    assert argv[argv.index("--max-budget-usd") + 1] == "1"
    assert PROMPT not in " ".join(argv) and routed.calls[0]["stdin"] == PROMPT.encode()
    await gateway_module.agent("budget.test", PROMPT)
    assert "--max-budget-usd" not in routed.calls[1]["argv"]
