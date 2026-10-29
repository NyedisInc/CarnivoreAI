from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from types import SimpleNamespace
from typing import Any, List

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_att_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_att_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

import src.config  # noqa: E402,F401
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api import automation_attachment_routes  # noqa: E402
from src.api.auth import require_auth  # noqa: E402
from src.core.automations import attachments, command_allowlist, gates, models as m, targets  # noqa: E402
from src.core.automations.scheduler import Scheduler  # noqa: E402
from src.core.automations.store import AutomationStore  # noqa: E402
from src.core.automations.store_schema import storage_for  # noqa: E402
from src.core.automations.targets import agent, command  # noqa: E402
from src.core.provider_ledger import refresh_poke  # noqa: E402

SCRIPT = r'''
import os
d = os.environ["CARNIVORE_RUN_ATTACHMENTS_DIR"]
open(os.path.join(d, "a.txt"), "w").write("hello")
open(os.path.join(d, "b.json"), "w").write("{}")
os.symlink("/etc/hosts", os.path.join(d, "link.txt"))
os.mkdir(os.path.join(d, "sub"))
open(os.path.join(d, "sub", "inner.txt"), "w").write("x")
with open(os.path.join(d, "big.bin"), "wb") as f:
    f.truncate(11 * 1024 * 1024)
open(os.path.join(d, ".hidden"), "w").write("x")
'''


@pytest.fixture
def world(tmp_path, monkeypatch):
    script = tmp_path / "make_files.py"
    script.write_text(SCRIPT)
    monkeypatch.setattr(command_allowlist, "allows", lambda command, path=None: True)
    monkeypatch.setattr(command_allowlist, "argv_of", lambda entry: [sys.executable, str(script)])
    monkeypatch.setitem(targets.RUNNERS, "command", command.run)
    store = AutomationStore(storage_for(tmp_path / "state"), notify=lambda _t: None)
    auto = store.create(name="files", cron="0 7 * * 1", target={"kind": "command", "command": "make-files"})
    app = FastAPI()
    app.include_router(automation_attachment_routes.router)
    app.state.automation_store = store
    app.dependency_overrides[require_auth] = lambda: None
    return SimpleNamespace(store=store, auto=auto, sched=Scheduler(SimpleNamespace(), store), app=app, client=TestClient(app))


def _run_command(world) -> str:
    run = world.store.insert_run(world.auto["automation_id"], "boot")
    run = world.store.update_run(run["run_id"], status=m.RUNNING, started_at=1.0, notes={"by": {"kind": "app"}})
    automation = world.store.get(world.auto["automation_id"])
    asyncio.run(world.sched._execute(targets.RUNNERS["command"], automation, run))
    return run["run_id"]


def test_command_run_keeps_files_and_names_the_rest(world):
    run = world.store.run(_run_command(world))
    assert run["status"] == m.SUCCEEDED, run
    assert run["attachments"] == [{"name": "a.txt", "bytes": 5, "mime": "text/plain"},
                                  {"name": "b.json", "bytes": 2, "mime": "application/json"}]
    left = {item["name"]: item["reason"] for item in run["notes"]["attachments_left_out"]}
    assert left == {"link.txt": "not_a_file", "sub": "not_a_file", "big.bin": "too_large", ".hidden": "bad_name"}
    assert run["notes"]["by"] == {"kind": "app"}
    folder = attachments.folder_for(world.store.attachments_root, run["run_id"])
    assert sorted(os.listdir(folder)) == ["a.txt", "b.json"]
    assert oct(folder.stat().st_mode & 0o777) == "0o700"
    assert os.path.exists("/etc/hosts")


def test_caps_total_and_count(tmp_path):
    folder = tmp_path / "f"
    folder.mkdir()
    for i in range(23):
        (folder / f"f{i:02d}.txt").write_text("x")
    kept, left = attachments.collect(folder)
    assert [k["name"] for k in kept] == [f"f{i:02d}.txt" for i in range(20)]
    assert [x for x in left] == [{"name": f"f{i:02d}.txt", "reason": "too_many"} for i in range(20, 23)]
    for p in folder.iterdir():
        p.unlink()
    for i in range(6):
        with open(folder / f"m{i}.bin", "wb") as f:
            f.truncate(9 * 1024 * 1024)
    kept, left = attachments.collect(folder)
    assert len(kept) == 5 and left == [{"name": "m5.bin", "reason": "total_too_large"}]


def test_nothing_made_means_null_and_no_folder(world, monkeypatch):
    monkeypatch.setattr(command_allowlist, "argv_of", lambda entry: [sys.executable, "-c", "pass"])
    run = world.store.run(_run_command(world))
    assert run["status"] == m.SUCCEEDED and run["attachments"] is None
    assert "attachments_left_out" not in (run["notes"] or {})
    assert not attachments.folder_for(world.store.attachments_root, run["run_id"]).exists()


def test_agent_run_gets_add_dir_and_env(world, monkeypatch, tmp_path):
    seen: List[Any] = []

    async def fake_child(argv, env, *, on_line, **kw):
        seen.append((list(argv), dict(env)))
        return SimpleNamespace(ran=True, timed_out=False, exit_code=0, stderr_tail=b"", spawn_error=None)

    monkeypatch.setattr(refresh_poke, "resolve_claude_binary", lambda: "/fake/claude")
    monkeypatch.setattr(refresh_poke, "run_child_streaming", fake_child)
    monkeypatch.setattr(gates, "login_of", lambda target: (None, None))
    monkeypatch.setattr(agent, "folder_problem", lambda folder: None)
    work = tmp_path / "work"
    work.mkdir()
    run = world.store.insert_run(world.auto["automation_id"], "boot")
    automation = {"target": {"kind": "agent", "folder": str(work), "prompt": "p", "max_turns": 3}, "delivery": {"notify": False}}
    asyncio.run(agent.run(SimpleNamespace(store=world.store), automation, run))
    assert seen, "population check: the faked child never ran"
    argv, env = seen[0]
    folder = str(attachments.folder_for(world.store.attachments_root, run["run_id"]))
    assert argv[argv.index("--add-dir") + 1] == folder
    assert env["CARNIVORE_RUN_ATTACHMENTS_DIR"] == folder


def test_route_serves_with_headers_and_refuses_the_rest(world):
    run_id = _run_command(world)
    client = world.client
    ok = client.get(f"/automations/runs/{run_id}/attachments/a.txt")
    assert ok.status_code == 200 and ok.content == b"hello"
    assert ok.headers["content-type"].startswith("application/octet-stream")
    assert ok.headers["content-disposition"] == "attachment; filename*=UTF-8''a.txt"
    assert ok.headers["x-content-type-options"] == "nosniff" and ok.headers["cache-control"] == "no-store"
    assert client.get(f"/automations/runs/{run_id}/attachments/..%2Fx").status_code == 404
    assert client.get(f"/automations/runs/{run_id}/attachments/nope.txt").status_code == 404
    assert client.get(f"/automations/runs/{run_id}/attachments/big.bin").status_code == 404
    assert client.get("/automations/runs/run_nope/attachments/a.txt").status_code == 404
    world.app.dependency_overrides.pop(require_auth)
    assert client.get(f"/automations/runs/{run_id}/attachments/a.txt").status_code == 401


def test_route_refuses_a_stored_name_that_escapes_the_folder(world):
    run_id = _run_command(world)
    folder = attachments.folder_for(world.store.attachments_root, run_id)
    (folder / "a.txt").unlink()
    os.symlink("/etc/hosts", folder / "a.txt")
    assert world.client.get(f"/automations/runs/{run_id}/attachments/a.txt").status_code == 404


def test_folder_goes_with_prune_delete_and_orphan_sweep(world, tmp_path):
    root = world.store.attachments_root
    first = _run_command(world)
    assert attachments.folder_for(root, first).is_dir()
    for _ in range(m.RUNS_KEPT):
        run = world.store.insert_run(world.auto["automation_id"], "boot")
        world.store.update_run(run["run_id"], status=m.SUCCEEDED, ended_at=2.0)
    with pytest.raises(m.AutomationNotFound):
        world.store.run(first)
    assert not attachments.folder_for(root, first).exists()
    kept = _run_command(world)
    orphan = attachments.folder_for(root, "run_orphan")
    orphan.mkdir(parents=True)
    (orphan / "x.txt").write_text("x")
    world.sched.sweep_attachments()
    assert not orphan.exists() and attachments.folder_for(root, kept).is_dir()
    world.store.delete(world.auto["automation_id"])
    assert not attachments.folder_for(root, kept).exists()
