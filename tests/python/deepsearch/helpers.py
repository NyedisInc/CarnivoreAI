
from __future__ import annotations

import json
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import src.config  # noqa: F401,E402  pylint
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.pipeline.engine import Engine
from src.core.pipeline.registry import plugins as pipeline_plugins
from src.core.deepsearch.pipeline_plugin import DEEPSEARCH
from src.core.deepsearch import constants as SK
from src.core.deepsearch import index_scope
from src.core.deepsearch import rules
from src.core.deepsearch.cache import db as cache_db
from src.core.deepsearch.cache import flip
from src.core.transcript_manifest import condition
from src.cplugs.host import runtime, state as owner_state

from tests.python.transcript_source.helpers import CONV, FOLDER, WORKDIR

SUBAGENT_WORDS = ("quokkaone", "quokkatwo", "quokkathree")
PREFS: Dict[str, Any] = {"values": {}}


def choose_scope(state: Path, value: str) -> None:
    PREFS["values"][index_scope.PREFERENCE_FIELD] = value


def rec(i: int, text: str, kind: str = "user", **extra: Any) -> bytes:
    if kind == "assistant":
        message = {"role": "assistant", "content": [{"type": "text", "text": text}]}
    else:
        message = {"role": "user", "content": text}
    return (json.dumps({"type": kind, "uuid": f"u-{i}", "message": message, **extra}) + "\n").encode()


def build_world(tmp_path: Path, monkeypatch: Any) -> Dict[str, Any]:
    state = tmp_path / "state"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    switch(state, "save", True)
    folder = tmp_path / "corpus" / FOLDER
    (folder / CONV / "subagents").mkdir(parents=True)
    main = folder / f"{CONV}.jsonl"
    main.write_bytes(rec(0, "the main conversation talks about wombatmain") + rec(1, "wombatmain again", "assistant"))
    subagents: List[Path] = []
    for i, word in enumerate(SUBAGENT_WORDS):
        path = folder / CONV / "subagents" / f"agent-{i}.jsonl"
        path.write_bytes(rec(100 + i, f"subagent {i} found {word}", isSidechain=True))
        subagents.append(path)
    with closing(connect(db_path_for(state), create=False)) as conn:
        conn.execute(
            "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, working_dir, origin, "
            "lifecycle, claude_session_uuid, agent_type, agent_family, created_at, updated_at, title) VALUES "
            "('sess-uuid-1','cloude','cloude_a',111,?,'created','stopped',?,'claude','claude','2026-09-01',"
            "'2026-09-01','wombat work')", (WORKDIR, CONV))
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"save_pipeline": {"capture_scope": "all"}}))
    monkeypatch.setattr(rules, "default_config_path", lambda: config)
    monkeypatch.setattr(SK, "INDEX_SCOPE", "all")
    PREFS["values"] = {}
    index_scope.install(lambda: PREFS)
    return {"state": state, "db": db_path_for(state), "corpus": tmp_path / "corpus", "main": main,
            "subagents": subagents}


def mount(world: Dict[str, Any], monkeypatch: Any) -> Any:
    from fastapi import FastAPI

    from src.api import deepsearch_routes
    from src.api.auth import require_auth
    from src.config import settings as app_settings

    monkeypatch.setattr(app_settings, "state_dir_override", str(world["state"]))
    app = FastAPI()
    app.include_router(deepsearch_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    return app


def teardown() -> None:
    condition.uninstall()
    index_scope.uninstall()


def scan(world: Dict[str, Any]) -> Dict[str, Any]:
    record = condition.run_scan(world["state"], claude_roots=(world["corpus"],), codex_home="")
    assert record["status"] == "ok", record
    return record


def drain(world: Dict[str, Any]) -> None:
    kinds = frozenset({"conversation", "subagent"})
    now = [0.0]
    engine = Engine(world["state"], db_path=world["db"], clock=lambda: now[0], plugins=pipeline_plugins([replace(DEEPSEARCH, file_kinds=kinds)]),
                    refresh_fn=lambda: SimpleNamespace(changed=()))
    assert engine.scanner.run_once()["status"] == "ok"
    now[0] += 10.0
    for _ in range(2000):
        delay = engine.step()
        if delay is None or delay > 0:
            engine.signal_caught_up()
            return
    raise AssertionError("the worker never ran out of due work")


def q(db: Path, sql: str, *args: Any) -> List[tuple]:
    with closing(connect(db, create=False)) as conn:
        return [tuple(r) for r in conn.execute(sql, args).fetchall()]


def switch(state: Path, cplug_id: str, on: bool) -> None:
    d = runtime.find(cplug_id)
    assert d is not None
    owner_state.update(state, d.manifest, None,
                       lambda st: replace(st, enabled=on, grants=tuple(d.manifest.permissions) if on else st.grants))


def cq(world: Dict[str, Any], sql: str, *args: Any) -> List[tuple]:
    with closing(cache_db.open_cache(world["state"])) as conn:
        return [tuple(r) for r in conn.execute(sql, args).fetchall()]


def go_ready(world: Dict[str, Any]) -> None:
    flip.mark_ready(world["state"])
