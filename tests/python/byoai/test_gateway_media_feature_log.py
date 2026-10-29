
import pytest

from src.config.byoai import TargetRef
from src.core.byoai import adapters, gateway as gateway_module
from src.core.byoai.calllog import CallLog
from src.core.byoai.gateway import Gateway
from src.core.byoai.keys import KeyStore
from src.core.byoai.registry import register_feature
from src.core.byoai.store import ByoaiStore
from tests.python.byoai.test_byoai_routes import FakeKeychain

FEATURE = "test.media_feature_log"


@pytest.mark.asyncio
async def test_generate_logs_the_feature_for_a_routed_ref_and_an_explicit_target(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text("{}")
    keys = KeyStore(backend=FakeKeychain())
    store = ByoaiStore(config, keys=keys)
    conn = store.add_connection(preset="openai", label="openai")
    store.set_feature(FEATURE, TargetRef(connection=conn.id, model="gpt-image-2"), expected_revision=store.read().revision)
    register_feature(FEATURE, "image", "ai.feature.test", "ai.feature.test.description")
    log = CallLog(tmp_path)
    gateway = Gateway(store, log, keys)

    async def fake_generate(protocol, capability, target, key, prompt, fields):
        return gateway_module.MediaResult(items=[])

    async def no_key(connection):
        return None

    monkeypatch.setattr(adapters, "generate", fake_generate)
    monkeypatch.setattr(gateway, "_key", no_key)
    await gateway.generate(FEATURE, "a")
    await gateway.generate(gateway.feature_target(FEATURE), "b", capability="image", feature=FEATURE)
    await gateway.generate(gateway.feature_target(FEATURE), "c", capability="image")
    calls = log.page(limit=10)["calls"]
    assert sorted(str(c["feature"]) for c in calls) == ["None", FEATURE, FEATURE]
