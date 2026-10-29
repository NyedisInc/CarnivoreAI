
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from src.cplugs.host import dependencies, developer_mode, runtime
from src.cplugs.sdk.data_decl import DataDecl, DataPolicy
from tests.python.gate import cycle
from tests.python.gate.test_plugin_cycle import build_version


def _with_store(monkeypatch: pytest.MonkeyPatch, purge: str) -> None:
    monkeypatch.setattr(dependencies, "app_version", build_version)
    monkeypatch.setattr(developer_mode, "is_on", lambda: True)
    monkeypatch.setattr(runtime, "_host", None)
    original = runtime.definitions()
    decl = DataDecl(id="scratch", kind="folder", scope_by="install", state_path=f"gate-{purge}-store",
                    policy=DataPolicy(own="excluded", share="excluded", reason="a synthetic store for the gate", purge=purge))
    patched = tuple(replace(d, manifest=replace(d.manifest, data=(decl,))) if d.id == "unread" else d for d in original)
    monkeypatch.setattr(runtime, "_definitions", patched)


def test_a_purge_removes_a_store_marked_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _with_store(monkeypatch, "removed")
    status, detail = cycle.run_cycle("unread", tmp_path).checks["files_gone"]
    assert status == cycle.PASS, detail


def test_a_purge_keeps_a_store_marked_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _with_store(monkeypatch, "kept")
    outcome = cycle.run_cycle("unread", tmp_path)
    assert outcome.checks["kept_stores_stay"][0] == cycle.PASS, outcome.checks["kept_stores_stay"]
    assert outcome.checks["purge_priced"][0] == cycle.PASS, outcome.checks["purge_priced"]
