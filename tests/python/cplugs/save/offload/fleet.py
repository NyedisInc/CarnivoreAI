
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.plugins.save.offload import list_routes, offload_routes, restore_routes
from src.plugins.save.offload.ledger import Ledger
from src.plugins.sdk import session_chains as sdk
from src.plugins.sdk import transcript_files as tf
from src.plugins.sdk import vault_sources
from src.plugins.sdk.session_chains import ChainSnapshot, RunningScan, SessionFacts
from tests.python.cplugs.save.vault_helpers import World, jsonl

IDLE_SECONDS = 60 * 86400
FILE_AGE_SECONDS = 40 * 86400


def conv_id(index: int) -> str:
    return f"00000000-0000-4000-8000-{100 + index:012x}"


def build_fleet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sessions: int = 12, extra_conversations: int = 0) -> World:
    world = World(tmp_path)
    os.chmod(world.state, 0o700)
    total = sessions + extra_conversations
    for i in range(1, total + 1):
        world.write_conversation(jsonl(5, seed=i), conv=conv_id(i), subagents=1, tool_results=1)
    old = time.time() - FILE_AGE_SECONDS
    for path in [p for p in world.home.rglob("*") if p.is_file()]:
        os.utime(path, (old, old))
    for i in range(1, total + 1):
        world.capture(conv_id(i))
    idle = time.time() - IDLE_SECONDS
    facts = tuple(SessionFacts(f"S{i}", f"title {i}", 1, "local", "stopped", "closed_by_user", False, False, conv_id(i), idle) for i in range(1, sessions + 1))
    snapshot = ChainSnapshot(facts, {})
    monkeypatch.setattr(sdk, "read_snapshot", lambda: snapshot)
    monkeypatch.setattr(sdk, "read_running", lambda: RunningScan(frozenset(), 0))
    for module in (offload_routes, restore_routes, list_routes):
        monkeypatch.setattr(module.RUNTIME, "vault", lambda: world.vault)
        monkeypatch.setattr(module.RUNTIME, "sources", lambda: world.sources)
    monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
    monkeypatch.setattr(tf, "state_dir", lambda: world.state)
    store_settings(monkeypatch, offloadEnabled=True)
    return world


def store_settings(monkeypatch: pytest.MonkeyPatch, **setting: Any) -> Dict[str, Any]:
    live: Dict[str, Any] = dict(setting)
    monkeypatch.setattr(vault_sources, "plugin_settings", lambda state_dir, plugin_id: dict(live))
    return live


def ledger_of(world: World) -> Ledger:
    return Ledger(world.vault.root, world.state)


def delete_a_chunk(world: World, conversation: str) -> str:
    point = world.vault.manifests.newest(conversation)
    assert point is not None
    sha = next(iter(point.chunk_hashes()))
    found = world.vault.blobs.find(sha)
    assert found is not None
    found[0].unlink()
    return sha


def session_ids(count: int) -> List[str]:
    return [f"S{i}" for i in range(1, count + 1)]
