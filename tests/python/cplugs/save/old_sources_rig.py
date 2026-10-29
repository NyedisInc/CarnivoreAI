
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Dict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_auth
from src.cplugs.host import routes as host_routes, runtime
from src.cplugs.sdk import transcript_files, vault_sources
from tests.python.cplugs.save.old_sources_helpers import lines
from tests.python.cplugs.save.vault_helpers import stop_follower

BASE = "/api/v1/cplugs/save"
C1, C2 = "aaaaaaaa-1111-2222-3333-444444444444", "bbbbbbbb-1111-2222-3333-444444444444"
ENC = "-Users-x-gone"


@pytest.fixture
def rig(tmp_path: Path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    (state / "config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(transcript_files, "state_dir", lambda: state)
    monkeypatch.setattr(transcript_files, "config_file", lambda: state / "config.json")
    monkeypatch.setattr(transcript_files, "projects_dir", lambda: tmp_path / "no-claude")
    monkeypatch.setattr(vault_sources, "claude_roots", lambda: (tmp_path / "no-claude",))
    monkeypatch.setattr(vault_sources, "codex_home", lambda: tmp_path / "codex")
    monkeypatch.setattr(vault_sources, "project_roots", lambda _state: [])
    newer, older, recovered = tmp_path / "src-new", tmp_path / "src-old", tmp_path / "recovered"
    for folder, conv, count in ((newer, C1, 5), (newer, C2, 3), (older, C1, 3)):
        (folder / ENC).mkdir(parents=True, exist_ok=True)
        (folder / ENC / f"{conv}.jsonl").write_bytes(lines(count, conv[:2]))
    (recovered / "archive-export-1" / "archive-metadata").mkdir(parents=True)
    (recovered / "archive-export-1" / "archive-metadata" / "tables.jsonl").write_text('{"t":1}\n')
    (recovered / "foreign" / "x" / "local_1").mkdir(parents=True)
    (recovered / "foreign" / "x" / "local_1" / "audit.jsonl").write_text('{"a":1}\n')
    app = FastAPI()
    host = runtime.install(app, state)
    host.publish = lambda *_a, **_k: None
    app.include_router(host_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    with TestClient(app) as client:
        revision = client.get(BASE).json()["revision"]
        assert client.put(BASE, json={"revision": revision, "enabled": True}).status_code == 200
        stop_follower(client)
        body = {"folders": [{"name": "newer", "path": str(newer)}, {"name": "older", "path": str(older)}], "recovered_root": str(recovered)}
        yield client, state, body
    asyncio.run(host.stop())


def snapshot(root: Path) -> Dict[str, str]:
    out = {}
    for path in sorted(root.rglob("*")):
        rel = str(path.relative_to(root))
        if path.is_dir() and not (rel in ("blobs", "manifests") and not any(path.iterdir())):
            out[rel] = "<dir>"
        elif path.is_file():
            out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out
