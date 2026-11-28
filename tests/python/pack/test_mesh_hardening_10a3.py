
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import pytest
from fastapi import HTTPException

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_h10a3_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_h10a3_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

pytest.importorskip("fastapi")

from src.core.federation import mesh_peers  # noqa: E402
from src.core.pack.machines import capabilities, runtime as machines_runtime  # noqa: E402
from src.core.pack.machines.config_state import ConfigState  # noqa: E402
from src.core.pack.rollup_import import member_pull  # noqa: E402
from tests.python.pack import test_link_peers as lp  # noqa: E402
from tests.python.pack import test_roster_v2 as t2  # noqa: E402



def test_n1_list_changed_tells_the_listeners_of_a_v1_only_list_and_start_registers_one(monkeypatch, tmp_path):
    reg = mesh_peers.MeshPeers(open_db=lambda: None, self_iid="iid-a", fed_dir=tmp_path, sign=lambda _m: "")  # type: ignore[arg-type]
    seen: List[Any] = []
    monkeypatch.setattr(mesh_peers, "_LIST_LISTENERS", [seen.append])
    v1_only = SimpleNamespace(kind="v1")
    asyncio.run(reg.list_changed(v1_only, False))
    assert seen == [v1_only]
    asyncio.run(reg.list_changed(v1_only, True))
    assert seen == [v1_only]

    state = ConfigState(lambda: tmp_path / "config.json")
    monkeypatch.setattr(machines_runtime, "default_state", lambda: state)
    db = tmp_path / "start.db"
    from src.core.db import connect, db_path_for  # noqa: PLC0415
    from src.core.db_migration import ensure_db_migrated  # noqa: PLC0415
    from src.core.pack.meshdata import gossip  # noqa: PLC0415
    ensure_db_migrated(tmp_path)
    path = db_path_for(tmp_path)
    monkeypatch.setattr(gossip, "STEPS", [])
    monkeypatch.setattr(gossip, "PREPARE", [])
    from src.core.federation import peer_links  # noqa: PLC0415
    monkeypatch.setattr(peer_links, "LINKS", None)
    from src.core.pack.machines import exchange as machines_exchange  # noqa: PLC0415
    monkeypatch.setattr(machines_runtime, "_WIRING", None)
    monkeypatch.setattr(machines_exchange, "RUNTIME", None)

    async def boot() -> int:
        monkeypatch.setattr(mesh_peers, "_LIST_LISTENERS", [])
        task = machines_runtime.start(lambda: connect(path, create=False), lambda: None, label="t", app_version="1", state_dir=lambda: str(tmp_path))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return len(mesh_peers._LIST_LISTENERS)

    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", False)
    assert asyncio.run(boot()) == 0
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    assert asyncio.run(boot()) == 1
    del db



def test_n2_a_known_bump_advances_the_switch_memory_before_the_save_and_a_lost_v2_still_has_it(monkeypatch, tmp_path):
    pack, _ = t2._four(monkeypatch, tmp_path, caps_extra=(capabilities.CAP_MESH,))
    a = pack["a"]
    t2._settle(pack, 2)
    calls: List[int] = []
    real = ConfigState.advance_link_switches
    monkeypatch.setattr(ConfigState, "advance_link_switches", lambda self, g, s, at=None: calls.append(g) or real(self, g, s, at))
    assert a.refresh_roster(lp._inputs()) == "bump:first"
    assert a.refresh_roster(lp._inputs(), link_peers={lp.IDS["b"]: False}) == "bump:authority"
    assert len(calls) == 1
    from src.core.pack.machines import settings_custody  # noqa: PLC0415

    def no_key(_roster):
        raise settings_custody.DeviceKeyUnavailable()
    monkeypatch.setattr(a.custody, "_issue_roster_v2", no_key)
    assert a.refresh_roster(t2._computers(6)) == ""
    assert len(calls) == 2



def test_n3_a_removed_members_pull_is_cancelled_and_finished_entries_are_dropped(monkeypatch):
    monkeypatch.setattr(member_pull, "_PAIRS", [("iid-b", object()), ("iid-c", object())])
    monkeypatch.setattr(member_pull, "_TASKS", {})
    import src.core.computers.mesh_choice as mesh_choice  # noqa: PLC0415
    monkeypatch.setattr(mesh_choice, "eligible_ids", lambda lst, me: ["iid-c"])

    async def scenario() -> None:
        never = asyncio.Event()
        running = asyncio.create_task(never.wait())
        done = asyncio.create_task(asyncio.sleep(0))
        await done
        member_pull._TASKS.update({"iid-b": running, "iid-c": done})
        importer = SimpleNamespace(members=frozenset({"iid-b", "iid-c"}), member_caps={}, live=None)
        member_pull.on_list(importer, object(), "iid-a")
        await asyncio.sleep(0)
        assert running.cancelled() and member_pull._TASKS == {}

    asyncio.run(scenario())



def test_n5_while_the_held_list_is_unreadable_a_yes_for_any_but_the_held_master_is_a_forget(monkeypatch, tmp_path):
    from src.core.pack.relay import approval  # noqa: PLC0415
    from tests.python.pack import test_mesh_screens_9c2 as sc  # noqa: PLC0415
    from src.core.pack.machines import roster_v2  # noqa: PLC0415
    from tests.python.pack.test_roster import _inputs  # noqa: PLC0415

    lst = roster_v2.plan_v2(None, _inputs(("a", "b", "c"), b={"may_receive_logins": True}), alpha=sc.A)
    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    open_db = sc._wire(monkeypatch, tmp_path, lst, sc.C)
    custody = machines_runtime.wiring().runtime.custody
    sc._put(sc.A, "yes")
    with closing(open_db()) as conn:
        assert approval.answers(conn) == {sc.A: "yes"}
        approval.forget(conn, sc.A)
    custody.held_lists = lambda: (_ for _ in ()).throw(OSError("unreadable"))
    custody.settings = lambda: SimpleNamespace(master_install_id="iid-someone-else")
    with pytest.raises(HTTPException) as refused:
        sc._put(sc.A, "yes")
    assert refused.value.status_code == 409 and refused.value.detail["code"] == "relay_list_unreadable"
    with closing(open_db()) as conn:
        assert approval.answers(conn) == {}
    custody.settings = lambda: SimpleNamespace(master_install_id=sc.A)
    sc._put(sc.A, "yes")
    with closing(open_db()) as conn:
        assert approval.answers(conn) == {sc.A: "yes"}
        approval.forget(conn, sc.A)
    sc._put(sc.A, "no")
    with closing(open_db()) as conn:
        assert approval.answers(conn) == {sc.A: "no"}



def test_d1_an_approval_that_read_false_while_the_list_was_unreadable_revokes_nothing(monkeypatch, tmp_path):
    from tests.python.pack import test_mesh_removal as mr  # noqa: PLC0415

    monkeypatch.setattr(capabilities, "MESH_BUILD_ON", True)
    flag = {"readable": False, "first": True}

    def frozen() -> bool:
        if flag["first"]:
            flag["first"] = False
            return False
        if flag["readable"]:
            flag["readable"] = False
            return False
        return True

    def approved(_iid: str) -> bool:
        flag["readable"] = True
        return False

    sync, rig, deletes = mr._frozen_sender(monkeypatch, tmp_path, [mr.C, mr.X], frozen=frozen)
    sync.credentials._approved = approved
    asyncio.run(sync.credentials.push(mr.X))
    assert deletes == [] and rig.store.delegate_get(mr.X) is not None



def test_e4_a_shadow_row_does_not_make_a_member_folder_look_taken(monkeypatch, tmp_path):
    from src.core import project_writes  # noqa: PLC0415
    from src.core.db import connect  # noqa: PLC0415
    from src.core.pack.identity import replicas  # noqa: PLC0415
    from tests.layouts_helpers import migrated  # noqa: PLC0415

    base = tmp_path / "projects"
    base.mkdir()
    monkeypatch.setattr(project_writes, "_base_folders", lambda: [str(base)])
    db = migrated(tmp_path / "state")
    target = base / "p" / "new"
    with closing(connect(db, create=False)) as conn:
        conn.execute("INSERT INTO projects (root, raw_path, display_name, source, presence, host_key, created_at, updated_at, last_opened_at) "
                     "VALUES (?, ?, 'shadow', 'peer', 'present', 'peer-x', 1, 1, 1)", (str(base / "p"), str(base / "p")))
        conn.commit()
        replicas._require_member_root(str(target), conn)
        conn.execute("UPDATE projects SET host_key = 'local' WHERE display_name = 'shadow'")
        conn.commit()
        with pytest.raises(replicas.ReplicaRefused):
            replicas._require_member_root(str(target), conn)
