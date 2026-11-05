
from __future__ import annotations

import pytest

from src.core.pack.machines import runtime as pack_runtime
from src.core.swarm import admission, conflicts


@pytest.fixture(autouse=True)
def _machine_unmeasured(monkeypatch, tmp_path):
    monkeypatch.setattr(admission, "measure", lambda: admission.Machine(None, None, None, None))
    monkeypatch.setattr(conflicts, "path", lambda: tmp_path / "swarm-conflicts.json")


@pytest.fixture(autouse=True)
def _no_pack_wiring(monkeypatch):
    monkeypatch.setattr(pack_runtime, "_WIRING", None)


@pytest.fixture(autouse=True)
def _auto_answer_engine_off(monkeypatch):
    from src.core.approvals.auto_answer import catalog, engine
    from tests.python.approvals.auto_helpers import FixedPolicy

    monkeypatch.setattr(engine, "grid_policy", lambda: FixedPolicy(off=[i.id for i in catalog.RULE_INFOS]))
