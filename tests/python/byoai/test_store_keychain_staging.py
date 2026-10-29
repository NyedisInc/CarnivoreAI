import json
from pathlib import Path

import pytest

from src.core import config_writer
from src.core.byoai.contracts import ByoaiError
from src.core.byoai.keys import KeyStore
from src.core.byoai.store import ByoaiStore
from tests.python.byoai.test_byoai_foundation import FakeKeychain

SECRET = "z" * 20 + "WXYZ"
NEW = "y" * 20 + "ABCD"


@pytest.fixture
def env(tmp_path: Path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({}))
    keychain = FakeKeychain()
    return config, keychain, ByoaiStore(config, keys=KeyStore(backend=keychain))


def _fail_replace(monkeypatch) -> None:
    def boom(*_a, **_k):
        raise OSError("disk full")
    monkeypatch.setattr(config_writer.os, "replace", boom)


def test_a_failed_add_leaves_no_orphan_key(env, monkeypatch):
    config, keychain, store = env
    _fail_replace(monkeypatch)
    with pytest.raises(OSError):
        store.add_connection(preset="openai", key=SECRET)
    assert keychain.items == {}


def test_a_failed_update_keeps_the_old_key(env, monkeypatch):
    config, keychain, store = env
    conn = store.add_connection(preset="openai", key=SECRET)
    _fail_replace(monkeypatch)
    with pytest.raises(OSError):
        store.update_connection(conn.id, key=NEW)
    assert list(keychain.items.values()) == [SECRET]


def test_a_failed_clear_keeps_the_key(env, monkeypatch):
    config, keychain, store = env
    conn = store.add_connection(preset="openai", key=SECRET)
    _fail_replace(monkeypatch)
    with pytest.raises(OSError):
        store.clear_key(conn.id)
    assert list(keychain.items.values()) == [SECRET]
    assert store.read().connections[0].key_hint == SECRET[-4:]


def test_a_refused_second_step_restores_the_first(env):
    config, keychain, store = env
    conn = store.add_connection(preset="openai", key=SECRET)
    with pytest.raises(ByoaiError):
        store.update_connection(conn.id, key="bad key with spaces")
    assert list(keychain.items.values()) == [SECRET]
