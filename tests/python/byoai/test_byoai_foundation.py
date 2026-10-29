
import json
from typing import Dict, Optional, Tuple

import pytest

from src.config.byoai import TargetRef
from src.core.byoai import calllog, registry
from src.core.byoai.contracts import ByoaiError, InvalidKey, StaleRevision
from src.core.byoai.keys import KeyStore
from src.core.byoai.store import ByoaiStore
from src.core.byoai.transport import auth_headers, join_url, scrub

SECRET = "z" * 20 + "WXYZ"


class FakeKeychain:

    def __init__(self) -> None:
        self.items: Dict[Tuple[str, str], str] = {}
        self.locked = False

    def state(self, service: str, account: str) -> str:
        if self.locked:
            return "unavailable"
        return "ok" if (service, account) in self.items else "absent"

    def read(self, service: str, account: str) -> Optional[str]:
        return self.items.get((service, account))

    def write(self, service: str, account: str, secret: str) -> None:
        self.items[(service, account)] = secret

    def delete(self, service: str, account: str) -> bool:
        return self.items.pop((service, account), None) is not None


@pytest.fixture
def env(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"other_block": {"keep": True}}))
    keychain = FakeKeychain()
    return config, keychain, ByoaiStore(config, keys=KeyStore(backend=keychain))


def test_connection_round_trips_without_its_key_and_a_host_change_drops_it(env):
    config, keychain, store = env
    conn = store.add_connection(preset="openai", key=SECRET)

    raw = config.read_text()
    assert SECRET not in raw and SECRET[:-4] not in raw
    block = json.loads(raw)["byoai"]
    assert block["revision"] == 1 and json.loads(raw)["other_block"] == {"keep": True}
    saved = store.read().connections[0]
    assert saved.id == conn.id and saved.key_hint == SECRET[-4:] and saved.key_host == "https://api.openai.com"
    assert keychain.items == {("carnivore-byoai", conn.id): SECRET}

    store.update_connection(conn.id, base_url="https://api.openai.com/v2")
    assert keychain.items and store.read().connections[0].key_host == "https://api.openai.com"

    store.update_connection(conn.id, base_url="https://evil.example/v1")
    gone = store.read().connections[0]
    assert not keychain.items and gone.key_host is None and gone.key_hint == ""

    store.update_connection(conn.id, base_url="https://other.example/v1", key=SECRET + "2")
    assert store.read().connections[0].key_host == "https://other.example"
    assert SECRET not in config.read_text()


def test_stale_write_is_refused_and_leaves_the_keychain_alone(env):
    _, keychain, store = env
    store.add_connection(preset="ollama")
    with pytest.raises(StaleRevision):
        store.add_connection(preset="openai", key=SECRET, expected_revision=0)
    assert not keychain.items and len(store.read().connections) == 1


def test_secret_shaped_options_and_unsafe_keys_are_refused(env):
    _, keychain, store = env
    with pytest.raises(ByoaiError):
        store.add_connection(preset="custom", base_url="http://h", options={"api_key": "x"})
    with pytest.raises(InvalidKey):
        store.add_connection(preset="openai", key="has space")
    with pytest.raises(InvalidKey):
        store.add_connection(preset="openai", key='has"quote')
    assert not keychain.items and not store.read().connections


def test_fal_shaped_key_with_a_colon_is_accepted():
    from src.core import relay_keychain
    assert relay_keychain.is_safe_secret("0123abcd-0000-1111-2222-333344445555:deadbeefdeadbeefdeadbeefdeadbeef")
    assert not relay_keychain.is_safe_secret("a b") and not relay_keychain.is_safe_secret("a'b")


def test_routing_follows_connections_and_delete_clears_it(env):
    _, keychain, store = env
    conn = store.add_connection(preset="lmstudio", key="lm-studio-key")
    store.set_default("chat", TargetRef(connection=conn.id, model="m"))
    store.set_feature("changelog.headline", TargetRef(connection=conn.id))
    store.delete_connection(conn.id)
    block = store.read()
    assert not block.connections and not block.defaults and not block.features and not keychain.items


def test_transport_helpers_keep_the_key_on_its_host(env):
    _, _, store = env
    fal = store.add_connection(preset="fal", key=SECRET)
    assert auth_headers(fal, "k1") == {"Authorization": "Key k1"}
    assert scrub("denied for k1 " + "x" * 5000, "k1").startswith("denied for *** ") and len(scrub("x" * 5000, "k1")) == 2048
    assert join_url("http://h:1/v1", "/chat") == "http://h:1/v1/chat"
    for bad in ("http://evil/x", "//evil/x", "/a/../b", "x"):
        with pytest.raises(ByoaiError):
            join_url("http://h:1/v1", bad)
    with pytest.raises(ByoaiError):
        join_url("ftp://h/v1", "/x")


def test_registry_and_calllog(tmp_path, monkeypatch):
    reg = registry.FeatureRegistry()
    reg.register_feature("a.b", "chat", "ai.feature.a_b")
    with pytest.raises(ByoaiError):
        reg.register_feature("a.b", "chat", "x")
    monkeypatch.setattr(calllog, "MAX_CALLS", 3)
    log = calllog.CallLog(tmp_path)
    for i in range(6):
        log.record(calllog.CallRecord("chat", True, latency_ms=i))
    assert [r["latency_ms"] for r in log.recent()] == [5, 4, 3]
