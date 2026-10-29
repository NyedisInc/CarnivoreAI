
from __future__ import annotations

from contextlib import closing

import pytest

from src.api import pack_migrate_env  # noqa: F401
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.pack.identity import replicas
from src.core.pack.machines import restrictions as restrict
from src.core.pack.migrate import receive
from src.core.pack.transport import blobs


@pytest.fixture
def home_base(tmp_path, monkeypatch):
    from src.config import settings

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path, raising=True)
    assert ensure_db_migrated(tmp_path).status == "ok"
    base = tmp_path / "carnivore-projects"
    base.mkdir()
    return tmp_path, base


def test_replica_accept_onto_the_base_folder_is_refused(home_base):
    state, base = home_base
    with closing(connect(db_path_for(state), create=False)) as conn:
        with pytest.raises(replicas.ReplicaRefused) as refused:
            replicas.accept_replica(conn, home_install_id="A", project_uid="c0f1c0f1", name="x", root=str(base))
    assert refused.value.status == 409 and refused.value.code == "project_root_refused"


def test_migrate_prepare_onto_the_base_folder_is_refused(home_base):
    state, base = home_base
    env = receive.TargetEnv(
        open_db=lambda: connect(db_path_for(state), create=False), state_dir=str(state), inbox=blobs.Inbox(state / "inbox"),
        install_id="me", restrictions=lambda: restrict.Restrictions(may_receive_projects=True), projects_dir=str(base))
    body = {"op_id": "op-1", "project_uid": "u-1", "name": "x", "root_hint": str(base), "bytes_needed": 0, "dry_run": True}
    with pytest.raises(receive.MigrateRefused) as refused:
        receive.prepare(env, "sender-1", body)
    assert refused.value.status == 409 and refused.value.code == "project_root_refused"
