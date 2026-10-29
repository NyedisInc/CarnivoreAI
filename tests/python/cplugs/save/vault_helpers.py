
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from fastapi.testclient import TestClient

from src.cplugs import save as save_plugin
from src.cplugs.save.vault.identity import Identity
from src.cplugs.save.vault.store import Vault
from src.cplugs.save.vault.units import Sources

CONV = "12345678-aaaa-bbbb-cccc-1234567890ab"
ENC = "-Users-x-proj"
CODEX_ID = "0199aaaa-bbbb-7ccc-8ddd-eeeeffff0001"


def jsonl(lines: int, seed: int = 0, pad: int = 200) -> bytes:
    rows = []
    for i in range(lines):
        filler = os.urandom(pad // 2).hex() if pad else ""
        rows.append(b'{"type":"user","n":%d,"seed":%d,"pad":"%s"}\n' % (i, seed, filler.encode()))
    return b"".join(rows)


class World:

    def __init__(self, tmp_path: Path, codec: Optional[str] = None) -> None:
        self.home = tmp_path / "claude-home"
        self.projects = self.home / "projects"
        self.codex = tmp_path / "codex-home"
        self.state = tmp_path / "state"
        for folder in (self.projects, self.codex, self.state, self.state / "vault"):
            folder.mkdir(parents=True, exist_ok=True)
        (self.state / "vault" / "VAULT.json").write_text('{"format": 1}')
        self.sources = Sources((self.projects,), self.codex, self.state)
        self.vault = Vault(self.state / "vault", codec=codec)

    def transcript(self, conv: str = CONV, enc: str = ENC) -> Path:
        return self.projects / enc / f"{conv}.jsonl"

    def write_conversation(self, body: bytes, conv: str = CONV, enc: str = ENC, subagents: int = 2,
                           tool_results: int = 1) -> Path:
        main = self.transcript(conv, enc)
        main.parent.mkdir(parents=True, exist_ok=True)
        main.write_bytes(body)
        folder = main.parent / conv
        for i in range(subagents):
            (folder / "subagents").mkdir(parents=True, exist_ok=True)
            (folder / "subagents" / f"agent-{i}.jsonl").write_bytes(jsonl(3, seed=i))
            (folder / "subagents" / f"agent-{i}.meta.json").write_text('{"agentType":"x"}')
        for i in range(tool_results):
            (folder / "tool-results").mkdir(parents=True, exist_ok=True)
            (folder / "tool-results" / f"t{i}.txt").write_bytes(os.urandom(300))
        hist = self.home / "file-history" / conv
        hist.mkdir(parents=True, exist_ok=True)
        (hist / "abc@v1").write_bytes(os.urandom(64))
        return main

    def write_codex(self, body: bytes, thread: str = CODEX_ID, day: str = "2026/03/01") -> Path:
        path = self.codex / "sessions" / day / f"rollout-2026-03-01T10-00-00-{thread}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return path

    def capture(self, conv: str = CONV, reason: str = "follow", identity: Optional[Identity] = None, **kw):
        from src.cplugs.save.vault import units

        plan = units.plan_claude(self.sources, conv)
        assert plan is not None, "fixture conversation missing"
        return self.vault.capture(plan, identity or Identity(), reason, **kw)

    def grow_history(self, count: int, conv: str = CONV, reason: str = "follow", seeds: Optional[List[int]] = None) -> None:
        import time

        main = self.transcript(conv)
        mine: List[str] = []
        for i in range(count):
            with open(main, "ab") as handle:
                handle.write(jsonl(3, seed=(seeds[i] if seeds else i)))
            os.utime(main, (time.time() + i, time.time() + i))
            ids = self.vault.manifests.point_ids(conv)
            if ids and not self.vault.manifests.is_pinned(conv, ids[-1]):
                mine.append(ids[-1])
                self.vault.manifests.set_pinned(conv, ids[-1], True)
            assert self.capture(conv, reason=reason).status == "written"
        for point_id in mine:
            self.vault.manifests.set_pinned(conv, point_id, False)

    def side_history(self, points: int, size: int = 4096) -> None:
        import sqlite3

        path = self.state / "side.db"
        for i in range(points):
            path.unlink(missing_ok=True)
            conn = sqlite3.connect(path)
            conn.execute("create table t (v blob)")
            conn.execute("insert into t values (?)", (os.urandom(size),))
            conn.commit()
            conn.close()
            assert self.vault.capture_side_databases(self.state, [("side.db", path)]).status == "written"

    def sha_of_tree(self, files: List[Path]) -> dict:
        import hashlib

        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def stop_follower(client: TestClient) -> None:
    follower = save_plugin._Running.follower
    if follower is not None:
        client.portal.call(follower.stop)


def store_plugin_entry(state: Path, plugin_id: str, settings: dict, *, enabled: bool = True) -> None:
    import json

    from src.cplugs.host import state as owner_state

    path = owner_state.state_path(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version": owner_state.STATE_VERSION, "cplugs": {}}
    entry = data["cplugs"].get(plugin_id) or {"grants": [], "revision": 0}
    entry.update(enabled=enabled, settings=dict(settings), revision=int(entry.get("revision", 0)) + 1)
    data["cplugs"][plugin_id] = entry
    path.write_text(json.dumps(data), encoding="utf-8")
    owner_state._file_cache.pop(str(path), None)


def store_save_settings(state: Path, settings: dict, *, enabled: bool = True) -> None:
    store_plugin_entry(state, "save", settings, enabled=enabled)
