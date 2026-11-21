
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from src.core.pack.jobs import land, snapshot
from src.core.pack.jobs.types import JobError
from tests.python.pack.jobs.test_pack_jobs_snapshot import g, jobs_root, repo, tree_files  # noqa: F401

UID, JOB = "uid12345678", "job_0123456789ab"
S = ".claude/settings.json"


def _tree_blob(snap, path: str) -> str | None:
    cp = subprocess.run(["git", "--git-dir", snap.side_git_dir, "show", f"{snap.commit}:{path}"], capture_output=True, text=True)
    return cp.stdout if cp.returncode == 0 else None


@pytest.fixture()
def dirty(repo: Path) -> Path:
    (repo / ".claude").mkdir()
    (repo / S).write_text("committed\n")
    (repo / ".mcp.json").write_text("{}\n")
    g(repo, "add", "-A")
    g(repo, "commit", "-qm", "cfg")
    (repo / S).write_text("hook edit now\n")
    (repo / ".mcp.json").write_text('{"evil": 1}\n')
    (repo / ".claude" / "settings.local.json").write_text("new local\n")
    (repo / ".codex").mkdir()
    (repo / ".codex" / "config.toml").write_text("x=1\n")
    return repo


def test_agent_snapshot_has_harness_config_only_as_committed(dirty, jobs_root):
    snap = snapshot.take(str(dirty), UID, JOB, jobs_root=jobs_root, agent=True)
    assert _tree_blob(snap, S) == "committed\n" and _tree_blob(snap, ".mcp.json") == "{}\n"
    names = tree_files(snap)
    assert ".claude/settings.local.json" not in names and ".codex/config.toml" not in names


def test_command_snapshot_carries_harness_config_as_written(dirty, jobs_root):
    snap = snapshot.take(str(dirty), UID, JOB, jobs_root=jobs_root)
    assert _tree_blob(snap, S) == "hook edit now\n" and _tree_blob(snap, ".mcp.json") == '{"evil": 1}\n'
    assert _tree_blob(snap, ".codex/config.toml") == "x=1\n"


def test_harness_paths_follow_scope():
    assert "sub/.claude/settings.json" in snapshot.harness_paths("sub") and snapshot.harness_paths("")[3] == ".codex/config.toml"


def _land_world(dirty: Path, jobs_root: Path):
    snap = snapshot.take(str(dirty), UID, JOB, jobs_root=jobs_root, agent=True)
    return snap


def _result(snap, files: dict) -> str:
    import os
    import tempfile
    side = snap.side_git_dir
    with tempfile.TemporaryDirectory() as t:
        env = {**os.environ, "GIT_INDEX_FILE": os.path.join(t, "i"), "GIT_DIR": side}
        run = lambda *a, inp=None: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], env=env, check=True,
                                                  capture_output=True, text=True, input=inp).stdout.strip()
        run("read-tree", snap.commit)
        for path in [p for p, b in files.items() if b is None]:
            run("update-index", "--index-info", inp=f"0 {'0' * 40}\t{path}\n")
        for path, body in [(p, b) for p, b in files.items() if b is not None]:
            mode, text = body if isinstance(body, tuple) else ("100644", body)
            blob = run("hash-object", "-w", "--stdin", inp=text)
            run("update-index", "--add", "--cacheinfo", f"{mode},{blob},{path}")
        tree = run("write-tree")
        commit = run("commit-tree", tree, "-p", snap.commit, "-m", "r")
        run("update-ref", f"refs/heads/result-{JOB}", commit)
        return commit


def test_land_leaves_callers_uncommitted_settings_and_drops_worker_change(dirty, jobs_root):
    snap = _land_world(dirty, jobs_root)
    result = _result(snap, {S: "worker wrote\n", "out.txt": "o\n"})
    res = land.land(str(dirty), snap.side_git_dir, snap.commit, result, JOB, snapshot_at=0.0, skip=snapshot.harness_paths(snap.scope))
    assert res.clashes == [] and res.applied == ["out.txt"] and res.dropped == [S]
    assert (dirty / S).read_text() == "hook edit now\n"


def test_land_without_worker_change_reports_no_clash_on_harness_paths(dirty, jobs_root):
    snap = _land_world(dirty, jobs_root)
    result = _result(snap, {"out.txt": "o\n"})
    res = land.land(str(dirty), snap.side_git_dir, snap.commit, result, JOB, snapshot_at=0.0, skip=snapshot.harness_paths(snap.scope))
    assert res.clashes == [] and res.dropped == [] and (dirty / ".mcp.json").read_text() == '{"evil": 1}\n'



import asyncio  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from types import SimpleNamespace  # noqa: E402

pytest.importorskip("fastapi")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pack_jobs_agent_engine import rig, seed  # noqa: E402,F401
from test_pack_jobs_agent_host import look, run, sim, world  # noqa: E402,F401

from src.core.attention import evidence as ev  # noqa: E402
from src.core.pack.jobs import agent_launch, agent_watch  # noqa: E402
from src.core.pack.jobs.agent_types import CAP_REPLY_DIGEST, ReplyBody, digest_of  # noqa: E402
from src.core.pack.jobs.types import HostState, JobError, JobState  # noqa: E402

JID = "job_0123456789ab"


def test_reply_body_without_a_digest_is_byte_for_byte_the_old_body_and_a_digest_is_checked() -> None:
    assert ReplyBody(job_id=JID, text="yes").model_dump() == {"job_id": JID, "text": "yes"}
    assert ReplyBody(job_id=JID, text="yes", question_digest="0a1b2c3d").model_dump()["question_digest"] == "0a1b2c3d"
    for bad in ("0A1B2C3D", "0a1b2c3", "0a1b2c3d0", "zzzzzzzz", ""):
        with pytest.raises(ValueError):
            ReplyBody(job_id=JID, text="yes", question_digest=bad)


async def _park_question(sim) -> Any:
    body = await sim.start()
    sim.obs = look(ev.STATE_NEEDS_USER, ev.REASON_QUESTION, dialog=SimpleNamespace(question="Which database?", options=("sqlite",), startup_kind=None))
    parked = await sim.until(lambda r: r.state == HostState.PARKED)
    return body, parked.question


def test_target_refuses_a_stale_digest_and_types_nothing_and_takes_a_matching_one(sim) -> None:
    async def go() -> None:
        body, question = await _park_question(sim)
        with pytest.raises(JobError) as err:
            await sim.w.host.reply("iid-a", ReplyBody(job_id=body.job_id, text="x", question_digest=digest_of("another question")))
        assert err.value.code == "question_changed" and err.value.status == 409 and sim.typed == [] and sim.delivered == []
        assert sim.row().state == HostState.PARKED
        await sim.w.host.reply("iid-a", ReplyBody(job_id=body.job_id, text="sqlite", question_digest=digest_of(question)))
        assert sim.delivered == ["sqlite"]
    run(go())


def test_target_without_a_digest_behaves_as_before(sim) -> None:
    async def go() -> None:
        body, _q = await _park_question(sim)
        await sim.w.host.reply("iid-a", ReplyBody(job_id=body.job_id, text="sqlite"))
        assert sim.delivered == ["sqlite"]
    run(go())


def _caller_rows(rig, caps):
    rig._view_for = lambda root, uid: SimpleNamespace(caps={"iid-b": caps})
    return seed(rig, JobState.QUESTION, question="q?", question_kind="question",
                request_json=json.dumps({"snap": {"project_root": "/x"}}))


def test_the_caller_sends_the_digest_only_to_a_target_that_advertises_the_capability(rig) -> None:
    rec = _caller_rows(rig, [CAP_REPLY_DIGEST])
    asyncio.run(rig.reply(rec.id, "yes", "ses_caller", digest_of("q?")))
    assert rig.target.replies[-1].question_digest == digest_of("q?")
    old = _caller_rows(rig, ["pack.jobs.agent"])
    asyncio.run(rig.reply(old.id, "yes", "ses_caller", digest_of("q?")))
    assert rig.target.replies[-1].question_digest is None and "question_digest" not in rig.target.replies[-1].model_dump()


def test_the_route_module_registers_the_capability() -> None:
    from src.api import federation_pack_jobs_routes  # noqa: F401
    from src.core.pack.machines import capabilities

    assert CAP_REPLY_DIGEST in capabilities.names()


def test_worker_usage_read_never_follows_a_path_planted_in_the_state_file(tmp_path: Path, monkeypatch) -> None:
    import sqlite3

    home = tmp_path / "codex home"
    (home / "sessions" / "2026" / "11" / "16").mkdir(parents=True)
    conv = "0198a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"
    outside = tmp_path / "outside.jsonl"
    outside.write_text('{"type":"session_meta","payload":{"id":"x"}}\n')
    db = sqlite3.connect(home / "state_5.sqlite")
    db.execute("CREATE TABLE threads (id TEXT, rollout_path TEXT)")
    db.execute("INSERT INTO threads VALUES (?, ?)", (conv, str(outside)))
    db.commit()
    db.close()
    opened: list = []
    from src.core.session_token_usage import codex_reader

    real = codex_reader.read_codex_usage
    monkeypatch.setattr(codex_reader, "read_codex_usage", lambda p: (opened.append(str(p)), real(p))[1])
    assert agent_watch.read_usage_totals("codex", conv, None, str(home)) is None
    assert opened == []


def test_worker_usage_read_opens_the_contained_rollout(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "codex home"
    day = home / "sessions" / "2026" / "11" / "16"
    day.mkdir(parents=True)
    conv = "0198a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"
    rollout = day / f"rollout-2026-11-16T00-00-00-{conv}.jsonl"
    rollout.write_text("{}\n")
    from src.core.session_token_usage import codex_reader

    opened: list = []
    monkeypatch.setattr(codex_reader, "read_codex_usage", lambda p: (opened.append(os.path.realpath(p)), None)[1])
    assert agent_watch.read_usage_totals("codex", conv, None, str(home)) is None
    assert opened == [os.path.realpath(rollout)]


def test_the_worker_tmux_name_is_on_the_row_before_the_create_and_matches_the_backends_name(sim) -> None:
    from src.core import tmux_backend

    seen: list = []
    real = sim.w.host.agent.deps.create_worker

    async def create(plan, session_id, label, working_dir):
        seen.append((sim.w.host.store.host_get(sim.job_id).worker_tmux, session_id))
        return await real(plan, session_id, label, working_dir)

    sim.w.host.agent.deps.create_worker = create

    async def go() -> None:
        await sim.start()
        name, sid = seen[0]
        assert name == agent_launch.worker_tmux_name(sid) == f"{tmux_backend.SESSION_PREFIX}{tmux_backend._slugify(sid)}"
        sim.finish_text()
        await sim.ended()
    run(go())


def test_recover_keeps_a_recorded_present_worker_and_ends_a_crash_left_row_cleanly(sim) -> None:
    async def go() -> None:
        host = sim.w.host
        body = await sim.start()
        host.agent._watches[body.job_id].cancel()
        await asyncio.sleep(0.01)
        sim.listed, sim.present = False, True
        assert sim.row().worker_tmux and await host.recover_agents() == 1 and sim.row().state == HostState.RUNNING
        host.agent._watches[body.job_id].cancel()
        await asyncio.sleep(0.01)
        sim.present = False
        await host.recover_agents()
        row = sim.row()
        assert row.state == HostState.EXITED and row.detail and row.ended_at
    run(go())



def _agent_tree(dirty: Path, jobs_root: Path):
    return snapshot.take(str(dirty), UID, JOB, jobs_root=jobs_root, agent=True)


def test_snapshot_drops_a_case_variant_of_a_harness_path_for_an_agent_and_keeps_it_for_a_command(repo, jobs_root):
    (repo / ".Claude").mkdir()
    (repo / ".Claude" / "Settings.json").write_text("EVIL\n")
    assert ".Claude/Settings.json" not in tree_files(_agent_tree(repo, jobs_root))
    assert ".Claude/Settings.json" in tree_files(snapshot.take(str(repo), UID, "job_0123456789ac", jobs_root=jobs_root))


def test_snapshot_pins_the_repository_top_harness_paths_when_the_folder_is_a_subfolder(repo, jobs_root):
    (repo / ".codex").mkdir()
    (repo / ".codex" / "config.toml").write_text("STAGED-EVIL\n")
    g(repo, "add", "-A")
    snap = snapshot.take(str(repo / "sub"), UID, JOB, jobs_root=jobs_root, agent=True)
    assert ".codex/config.toml" not in tree_files(snap)


@pytest.mark.parametrize("files", [{".Claude/Settings.json": "W\n"}, {".codex/config.toml": "W\n"}])
def test_land_drops_case_variants_and_top_paths_from_a_sub_scope(dirty, jobs_root, files):
    snap = snapshot.take(str(dirty / "sub"), UID, JOB, jobs_root=jobs_root, agent=True)
    result = _result(snap, {**files, "sub/out.txt": "o\n"})
    before = (dirty / S).read_text()
    res = land.land(str(dirty), snap.side_git_dir, snap.commit, result, JOB, snapshot_at=0.0, skip=snapshot.harness_paths(snap.scope))
    assert res.clashes == [] and res.dropped == sorted(files) and res.applied == ["sub/out.txt"]
    assert (dirty / S).read_text() == before


def test_land_drops_a_result_that_makes_a_harness_folder_a_file(repo, jobs_root):
    snap = snapshot.take(str(repo), UID, JOB, jobs_root=jobs_root, agent=True)
    result = _result(snap, {".codex": "link-ish\n", "out.txt": "o\n"})
    res = land.land(str(repo), snap.side_git_dir, snap.commit, result, JOB, snapshot_at=0.0, skip=snapshot.harness_paths(snap.scope))
    assert res.dropped == [".codex"] and res.applied == ["out.txt"] and not (repo / ".codex").exists()


def _jobs_files(jobs_root: Path) -> list:
    return sorted(str(p) for p in jobs_root.rglob("*")) if jobs_root.exists() else []


def _commit_link(repo: Path, name: str, target: str) -> None:
    os.symlink(target, repo / name)
    g(repo, "add", "-A")
    g(repo, "commit", "-qm", f"link {name}")


def test_agent_take_refuses_a_committed_link_at_a_harness_folder_and_leaves_nothing(dirty, jobs_root):
    (dirty / ".claude").rename(dirty / "cfg")
    g(dirty, "add", "-A")
    g(dirty, "commit", "-qm", "move")
    _commit_link(dirty, ".claude", "cfg")
    (dirty / "cfg" / "settings.json").write_text("HOOK\n")
    with pytest.raises(JobError) as err:
        snapshot.take(str(dirty), UID, JOB, jobs_root=jobs_root, agent=True)
    assert err.value.code == "harness_linked" and ".claude" in err.value.detail and _jobs_files(jobs_root) == []
    assert _tree_blob(snapshot.take(str(dirty), UID, "job_0123456789ac", jobs_root=jobs_root), "cfg/settings.json") == "HOOK\n"


def test_agent_take_refuses_a_linked_config_file_a_hard_link_and_an_untracked_link(dirty, jobs_root, tmp_path):
    (dirty / ".mcp.json").unlink()
    (dirty / "real.json").write_text("R\n")
    _commit_link(dirty, ".mcp.json", "real.json")
    with pytest.raises(JobError) as err:
        snapshot.take(str(dirty), UID, JOB, jobs_root=jobs_root, agent=True)
    assert err.value.code == "harness_linked"
    g(dirty, "rm", "-q", "-f", ".mcp.json")
    g(dirty, "commit", "-qm", "unlink")
    os.link(dirty / S, dirty / "twin.txt")
    with pytest.raises(JobError) as err:
        snapshot.take(str(dirty), UID, JOB, jobs_root=jobs_root, agent=True)
    assert err.value.code == "harness_linked" and S in err.value.detail
    os.unlink(dirty / "twin.txt")
    (dirty / ".codex" / "config.toml").unlink()
    (dirty / ".codex").rmdir()
    (tmp_path / "x").mkdir()
    os.symlink(tmp_path / "x", dirty / ".codex")
    (dirty / ".gitignore").write_text(".codex\n")
    with pytest.raises(JobError) as err:
        snapshot.take(str(dirty), UID, JOB, jobs_root=jobs_root, agent=True)
    assert err.value.code == "harness_linked" and ".codex" in err.value.detail


def test_agent_tree_holds_head_for_a_harness_path_at_a_middle_folder_level(repo, jobs_root):
    (repo / "a" / "b").mkdir(parents=True)
    (repo / "a" / ".codex").mkdir()
    (repo / "a" / ".codex" / "config.toml").write_text("committed\n")
    (repo / "a" / "b" / "f.txt").write_text("f\n")
    g(repo, "add", "-A")
    g(repo, "commit", "-qm", "mid")
    (repo / "a" / ".codex" / "config.toml").write_text("EVIL\n")
    snap = snapshot.take(str(repo / "a" / "b"), UID, JOB, jobs_root=jobs_root, agent=True)
    assert _tree_blob(snap, "a/.codex/config.toml") == "committed\n"
    assert "a/.codex/config.toml" in snapshot.harness_paths("a/b") and len(snapshot.harness_paths("a/b")) == 12


def test_land_parks_a_result_when_the_callers_harness_folder_became_a_link(dirty, jobs_root):
    snap = _land_world(dirty, jobs_root)
    result = _result(snap, {"cfg/settings.json": "WORKER\n", "out.txt": "o\n"})
    (dirty / ".claude" / "settings.local.json").unlink()
    (dirty / S).unlink()
    (dirty / ".claude").rmdir()
    (dirty / "cfg").mkdir()
    (dirty / "cfg" / "settings.json").write_text("ok\n")
    os.symlink("cfg", dirty / ".claude")
    res = land.land(str(dirty), snap.side_git_dir, snap.commit, result, JOB, snapshot_at=0.0, skip=snapshot.harness_paths(snap.scope))
    assert res.clashes and ".claude" in res.clashes[0] and res.applied == [] and not (dirty / "out.txt").exists()
    assert (dirty / "cfg" / "settings.json").read_text() == "ok\n" and res.ref
    assert subprocess.run(["git", "-C", str(dirty), "rev-parse", "--verify", "-q", res.ref], capture_output=True).returncode == 0


def test_land_drops_a_result_that_turns_the_harness_folder_into_a_link(dirty, jobs_root):
    snap = _land_world(dirty, jobs_root)
    result = _result(snap, {".claude": ("120000", "evil"), S: None, "evil/settings.json": "WORKER\n"})
    before = (dirty / S).read_text()
    res = land.land(str(dirty), snap.side_git_dir, snap.commit, result, JOB, snapshot_at=0.0, skip=snapshot.harness_paths(snap.scope))
    assert res.clashes == [] and ".claude" in res.dropped and S in res.dropped and res.applied == ["evil/settings.json"]
    assert (dirty / ".claude").is_dir() and not (dirty / ".claude").is_symlink() and (dirty / S).read_text() == before
    assert (dirty / "evil" / "settings.json").read_text() == "WORKER\n"


def test_the_engine_keeps_an_agent_job_here_when_a_harness_path_is_linked(rig, tmp_path, monkeypatch):
    from test_pack_jobs_agent_engine import _agent_req, _repo
    from src.core.pack.jobs import engine as engine_mod
    from src.core.pack.jobs.agent_types import CAP_AGENT
    from src.core.pack.jobs.place import PlaceView
    from src.core.pack.jobs.types import PlaceAnswer
    top = str(_repo(tmp_path))
    monkeypatch.setattr(rig, "_resolve_project", lambda folder: ({"uid": "uid-test-0001", "name": "app", "root": top}, ""))
    monkeypatch.setattr(rig, "_view_for", lambda root, uid: PlaceView(
        self_input=SimpleNamespace(install_id="iid-a"), peers=[SimpleNamespace(install_id="iid-b", label="b")], caps={"iid-b": ["pack.jobs", CAP_AGENT]}))
    monkeypatch.setattr(engine_mod.place, "place", lambda *a: PlaceAnswer("remote", "iid-b", "b", "room"))
    monkeypatch.setattr(engine_mod.snapshot, "take", lambda *a, **k: (_ for _ in ()).throw(JobError("harness_linked", ".claude sits behind a link")))
    rec = asyncio.run(rig.propose(_agent_req(top)))
    assert rec.state == JobState.HERE and ".claude sits behind a link" in rec.reason and rec.peer_install_id is None


def test_the_engine_asks_for_an_agent_snapshot_and_lands_with_the_harness_skip_and_names_it(rig, tmp_path, monkeypatch):
    from test_pack_jobs_agent_engine import _agent_req, _repo
    from src.core.pack.jobs import engine as engine_mod, engine_run
    from src.core.pack.jobs.engine_agent import AgentRequest
    from src.core.pack.jobs.agent_types import CAP_AGENT
    from src.core.pack.jobs.place import PlaceView
    from src.core.pack.jobs.types import PlaceAnswer
    from src.core.pack.jobs.types import CollectAnswer, LandResult
    seen: dict = {}
    snap = SimpleNamespace(toplevel=str(_repo(tmp_path)))
    monkeypatch.setattr(engine_mod.snapshot, "take", lambda *a, **k: seen.update(take=k) or (_ for _ in ()).throw(JobError("not_a_repo", "x")))
    monkeypatch.setattr(rig, "_resolve_project", lambda folder: ({"uid": "uid-test-0001", "name": "app", "root": snap.toplevel}, ""))
    monkeypatch.setattr(rig, "_view_for", lambda root, uid: PlaceView(
        self_input=SimpleNamespace(install_id="iid-a"), peers=[SimpleNamespace(install_id="iid-b", label="b")], caps={"iid-b": ["pack.jobs", CAP_AGENT]}))
    monkeypatch.setattr(engine_mod.place, "place", lambda *a: PlaceAnswer("remote", "iid-b", "b", "room"))
    with pytest.raises(JobError):
        asyncio.run(rig.propose(_agent_req(snap.toplevel)))
    assert seen["take"]["agent"] is True
    from test_pack_jobs_agent_engine import seed as seed_row
    rec = seed_row(rig, JobState.RUNNING, snapshot_commit="a" * 40)
    ans = CollectAnswer(blob_id="blob", result_commit="c" * 40, changed=1)

    async def collect(_j):
        return ans

    async def fetch_result(_j, _a, _s):
        return "p"

    rig.target.collect = collect
    rig.target.fetch_result = fetch_result
    monkeypatch.setattr(engine_run.bundle_io, "fetch_bundle", lambda *a, **k: "c" * 40)
    monkeypatch.setattr(engine_run.bundle_io, "consumed", lambda *a, **k: None)
    monkeypatch.setattr(rig, "_is_child_of", lambda *a: True)
    monkeypatch.setattr(engine_run.land, "land", lambda *a, **k: seen.update(land=k) or LandResult(applied=["o"], dropped=[S]))
    ctx = {"snap": {"toplevel": snap.toplevel, "scope": ""}, "request": {}}
    req = AgentRequest(command="", folder=snap.toplevel, caller_session="s", task="t")
    from src.core.pack.jobs import policy as policy_mod
    asyncio.run(rig._collect_and_land(rec, ctx, req, policy_mod.Policy(project_uid="uid-test-0001"), "side"))
    assert S in seen["land"]["skip"] and ".mcp.json" in seen["land"]["skip"]
    assert S in rig.store.events(rec.id)[-1]["note"]



def _folder_state(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if rel.split(os.sep)[0] == ".git":
            continue
        out[rel] = ("link", os.readlink(p)) if p.is_symlink() else ("dir", None) if p.is_dir() else ("file", p.read_bytes())
    return out


def _land_agent(root: Path, scope_dir: Path, jobs_root: Path, files: dict, *, agent: bool = True):
    snap = snapshot.take(str(scope_dir), UID, JOB, jobs_root=jobs_root, agent=agent)
    result = _result(snap, files)
    before = _folder_state(root)
    skip = snapshot.harness_paths(snap.scope) if agent else ()
    return land.land(str(root), snap.side_git_dir, snap.commit, result, JOB, snapshot_at=0.0, skip=skip), before, snap


def _parked(res, root: Path, before: dict, named: str) -> None:
    assert res.clashes and named in res.clashes[0] and res.applied == [] and res.deleted == []
    assert _folder_state(root) == before and res.ref
    assert subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "-q", res.ref], capture_output=True).returncode == 0


def _ignore(repo: Path, name: str) -> None:
    with open(repo / ".gitignore", "a") as fh:
        fh.write(f"{name}\n")
    g(repo, "add", ".gitignore")
    g(repo, "commit", "-qm", "ignore")


def test_land_parks_a_result_through_an_ignored_link_to_the_folder_itself(repo, jobs_root):
    _ignore(repo, "loop")
    os.symlink(".", repo / "loop")
    res, before, _ = _land_agent(repo, repo, jobs_root, {"loop/.mcp.json": "WORKER\n"})
    _parked(res, repo, before, "loop")
    assert not (repo / ".mcp.json").exists()


@pytest.mark.parametrize("harness,leaf,link", [(".claude", "settings.json", "cfg"), (".codex", "config.toml", "lnk")])
def test_land_parks_a_result_through_an_ignored_link_into_a_harness_folder(repo, jobs_root, harness, leaf, link):
    (repo / harness).mkdir()
    (repo / harness / "keep").write_text("a\n")
    g(repo, "add", "-A")
    g(repo, "commit", "-qm", "h")
    _ignore(repo, link)
    os.symlink(harness, repo / link)
    res, before, _ = _land_agent(repo, repo, jobs_root, {f"{link}/{leaf}": "WORKER\n"})
    _parked(res, repo, before, link)
    assert not (repo / harness / leaf).exists()


def test_land_parks_a_result_through_an_ignored_link_to_a_middle_level_of_a_sub_scope(repo, jobs_root):
    (repo / "a" / "b").mkdir(parents=True)
    (repo / "a" / "b" / "x").write_text("1\n")
    g(repo, "add", "-A")
    g(repo, "commit", "-qm", "ab")
    _ignore(repo, "lnk")
    os.symlink("a", repo / "lnk")
    res, before, _ = _land_agent(repo, repo / "a" / "b", jobs_root, {"lnk/.mcp.json": "WORKER\n"})
    _parked(res, repo, before, "lnk")
    assert not (repo / "a" / ".mcp.json").exists()


def test_a_command_job_landing_through_an_ignored_link_is_parked_and_a_link_two_levels_down_is_caught(repo, jobs_root):
    (repo / "real").mkdir()
    (repo / "x").mkdir()
    (repo / "x" / "k").write_text("k\n")
    g(repo, "add", "-A")
    g(repo, "commit", "-qm", "r")
    _ignore(repo, "lnk")
    _ignore(repo, "x/y")
    os.symlink("real", repo / "lnk")
    os.symlink("../real", repo / "x" / "y")
    res, before, _ = _land_agent(repo, repo, jobs_root, {"lnk/f.txt": "W\n"}, agent=False)
    _parked(res, repo, before, "lnk")
    res, before, _ = _land_agent(repo, repo, jobs_root, {"x/y/f.txt": "W\n"}, agent=False)
    _parked(res, repo, before, "x/y")
    assert not (repo / "real" / "f.txt").exists()


def test_land_still_applies_new_real_sub_folders_and_changes_in_existing_ones(repo, jobs_root):
    res, _, _ = _land_agent(repo, repo, jobs_root, {"new/deep/f.txt": "n\n", "sub/s.txt": "changed\n"})
    assert res.clashes == [] and res.applied == ["new/deep/f.txt", "sub/s.txt"]
    assert (repo / "new/deep/f.txt").read_text() == "n\n" and (repo / "sub/s.txt").read_text() == "changed\n"


def test_land_replaces_a_destination_that_is_a_link_or_a_hard_link_and_never_writes_through(repo, jobs_root):
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text("H\n")
    (repo / ".mcp.json").write_text("M\n")
    g(repo, "add", "-A")
    g(repo, "commit", "-qm", "c")
    _ignore(repo, "out.txt")
    _ignore(repo, "out2.txt")
    snap = snapshot.take(str(repo), UID, JOB, jobs_root=jobs_root)
    os.symlink(".mcp.json", repo / "out.txt")
    os.link(repo / ".claude" / "settings.json", repo / "out2.txt")
    res_c = _result(snap, {"out.txt": "W1\n", "out2.txt": "W2\n"})
    res = land.land(str(repo), snap.side_git_dir, snap.commit, res_c, JOB, outputs=["out*.txt"], snapshot_at=9e12)
    assert res.clashes == [] and res.applied == ["out.txt", "out2.txt"]
    assert (repo / ".mcp.json").read_text() == "M\n" and (repo / ".claude" / "settings.json").read_text() == "H\n"
    assert not (repo / "out.txt").is_symlink() and (repo / "out.txt").read_text() == "W1\n" and (repo / "out2.txt").read_text() == "W2\n"


def test_a_forged_result_naming_the_git_folder_writes_nothing_under_it(repo, jobs_root):
    snap = snapshot.take(str(repo), UID, JOB, jobs_root=jobs_root)
    side = snap.side_git_dir
    run = lambda *a, inp=None: subprocess.run(["git", "--git-dir", side, "-c", "user.name=t", "-c", "user.email=t@t", *a], check=False,
                                              capture_output=True, text=True, input=inp)
    blob = run("hash-object", "-w", "--stdin", inp="#!/bin/sh\nEVIL\n").stdout.strip()
    hooks = run("mktree", inp=f"100755 blob {blob}\tpre-commit\n").stdout.strip()
    dot = run("mktree", inp=f"040000 tree {hooks}\thooks\n").stdout.strip()
    top = run("ls-tree", snap.commit).stdout + f"040000 tree {dot}\t.git\n040000 tree {dot}\t.GIT\n"
    forged = run("mktree", inp=top)
    commit = run("commit-tree", forged.stdout.strip(), "-p", snap.commit, "-m", "f")
    assert commit.returncode == 0, forged.stderr
    run("update-ref", f"refs/heads/result-{JOB}", commit.stdout.strip())
    with pytest.raises(JobError) as err:
        land.land(str(repo), side, snap.commit, commit.stdout.strip(), JOB, snapshot_at=0.0)
    assert err.value.code == "unsafe_path"
    assert not (repo / ".git" / "hooks" / "pre-commit").exists()
