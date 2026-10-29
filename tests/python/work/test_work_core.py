
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI

from src.core.work import lists, seq, tx
from src.core.work.capability import WorkCapability
from src.core.work.storage import STORAGE, storage_for
from src.cplugs.host import runtime, state as owner_state
from src.cplugs.sdk import permission_registry as registry
from src.cplugs.sdk import CapabilityMissing
from src.cplugs.sdk.context import CplugContext
from src.cplugs.sdk.manifest import ManifestError, parse_manifest
from src.cplugs.sdk.work import STORAGE as DOOR_STORAGE
from tests.python.cplugs.owner import turn_on

INSERT = ("INSERT INTO work_items (list_key, text, position, created_by, state, created_at, updated_at, created_seq, seq) "
          "VALUES ('all', 'x', 1, 'joe', 'open', 0, 0, 1, 1)")


def test_next_seq_bumps_by_one_and_cursor_reads_without_taking(tmp_path: Path) -> None:
    with closing(storage_for(tmp_path).connect(True)) as conn, conn:
        start = seq.cursor(conn)
        assert seq.next_seq(conn) == start + 1 and seq.cursor(conn) == start + 1


def test_a_write_commits_then_names_each_touched_list_sorted(tmp_path: Path) -> None:
    storage, named, seen_at_notify = storage_for(tmp_path), [], []

    def notify(key: str) -> None:
        with closing(storage.connect(False)) as conn:
            seen_at_notify.append(conn.execute("SELECT COUNT(*) FROM work_items").fetchone()[0])
        named.append(key)

    with tx.write(storage.connect, {"b", "a"}, notify) as conn:
        conn.execute(INSERT)
    assert named == ["a", "b"] and seen_at_notify == [1, 1]


def test_a_raise_rolls_back_and_names_nothing(tmp_path: Path) -> None:
    storage, named = storage_for(tmp_path), []
    with pytest.raises(RuntimeError):
        with tx.write(storage.connect, {"all"}, named.append) as conn:
            conn.execute(INSERT)
            raise RuntimeError("boom")
    with closing(storage.connect(False)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 0
    assert named == []


def test_the_write_takes_the_lock_at_once(tmp_path: Path) -> None:
    storage = storage_for(tmp_path)
    with tx.write(storage.connect, set(), lambda key: None):
        other = sqlite3.connect(str(storage.db_path), timeout=0.05, isolation_level=None)
        try:
            with pytest.raises(sqlite3.OperationalError):
                other.execute("BEGIN IMMEDIATE")
        finally:
            other.close()


@pytest.mark.parametrize("key,valid,owner", [
    ("all", True, lists.ListOwner("all", 0)), ("12", True, lists.ListOwner("project", 12)), ("agent:3", True, lists.ListOwner("agent", 3)),
    ("0", False, None), ("012", False, None), ("agent:0", False, None), ("x", False, None), ("", False, None),
])
def test_list_keys(key: str, valid: bool, owner) -> None:
    assert lists.is_valid(key) is valid and lists.owner(key) == owner


def test_list_helpers() -> None:
    assert lists.agent_id_of("agent:7") == 7 and lists.agent_id_of("7") is None and lists.agent_id_of(7) is None
    assert [lists.order_id(k) for k in ("all", "12", "agent:3")] == [0, 12, 3] and not lists.is_valid(None)


def test_the_plugin_rules_ask_core() -> None:
    from src.cplugs.huddle import rules

    assert rules.ALL_LIST == lists.ALL_LIST and rules.check_list_key("agent:3") == "agent:3" and rules.agent_id_of("agent:3") == 3
    with pytest.raises(rules.TaskManagerInvalid):
        rules.check_list_key("x")


def test_the_sdk_door_is_cores_one_copy() -> None:
    assert DOOR_STORAGE is STORAGE


def test_ctx_work_is_on_the_task_manager_context_and_writes_no_audit_row(tmp_path: Path) -> None:
    host = runtime.Host(tmp_path, FastAPI(), publish=lambda topic: None)
    turn_on(host)
    ctx = host.context("huddle")
    assert ctx.has("work") and type(ctx.work) is WorkCapability
    with closing(ctx.work.storage.connect(True)) as conn, conn:
        assert ctx.work.next_seq(conn) == ctx.work.cursor(conn)


def test_a_stored_state_without_the_work_grant_still_holds_it(tmp_path: Path) -> None:
    host = runtime.Host(tmp_path, FastAPI(), publish=lambda topic: None)
    d = runtime.find("huddle")
    owner_state.update(tmp_path, d.manifest, None,
                       lambda st: replace(st, enabled=True, grants=tuple(p for p in d.manifest.permissions if p != "work")))
    assert "work" in owner_state.get(tmp_path, d.manifest).grants
    assert host.context("huddle").has("work")


def test_a_context_without_the_grant_has_no_work_and_the_error_names_it() -> None:
    ctx = CplugContext("x", storage=None, settings={}, notify=lambda n, k=None: None, log=None, grants=frozenset(), capabilities={})
    with pytest.raises(CapabilityMissing, match="work"):
        ctx.work


def test_the_work_permission_is_builtin_only() -> None:
    assert registry.risk_of("work", "thirdparty") == registry.NEVER and registry.risk_of("work", "builtin") == registry.HIGH
    raw = {"schema": 1, "id": "wk", "name_key": "cplug.wk.name", "description_key": "cplug.wk.description", "version": "1.0.0", "icon": "list",
           "author": "t", "min_app_version": "1.12.20", "tier": "core", "default_enabled": False, "surfaces": {},
           "settings_schema": {"version": 1, "fields": {}}, "permissions": {"app": ["work"]}}
    with pytest.raises(ManifestError, match="plugin only"):
        parse_manifest(raw)
    assert "work" in parse_manifest({**raw, "tier": "builtin"}).permissions
