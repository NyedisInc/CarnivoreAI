
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from src.api import pack_jobs_routes as routes
from src.api import project_replica_routes
from src.api.auth import require_auth
from src.core.pack.jobs import boot, place, policy, wipe
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import JobRecord, JobState
from src.core.pack.placement import rule

_REAL_ASK = wipe._ask
UID = "uid12345678"
ME = "iid-me"
URL = "/api/v1/projects/trader/auto-delegate"


def _git(repo: Path, *words: str) -> str:
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "HOME": str(repo), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.invalid"}
    return subprocess.run(["git", "-C", str(repo), *words], capture_output=True, text=True, check=True, env=env).stdout.strip()


class Far:

    def __init__(self, store: JobStore) -> None:
        self.store, self.calls, self.answers, self.marks = store, [], {}, []

    async def ask(self, install_id: str, body: Dict[str, Any]) -> Any:
        self.calls.append((install_id, body))
        self.marks.append(policy.get(self.store, UID).auto_delegate)
        answer = self.answers.get(install_id, {"verdict": "deleted" if not body["dry_run"] else "deletable", "code": "", "root": f"/far/{install_id}"})
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture()
def world(tmp_path: Path, monkeypatch):
    repo = tmp_path / "home"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("a")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "one")
    first = _git(repo, "rev-parse", "HEAD")
    _git(repo, "tag", "-a", "-m", "v1", "v1")
    _git(repo, "tag", "light")
    (repo / "b.txt").write_text("b")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-q", "-m", "two")
    second = _git(repo, "rev-parse", "HEAD")
    _git(repo, "branch", "side", first)
    (repo / "c.txt").write_text("c")
    _git(repo, "add", "c.txt")
    _git(repo, "commit", "-q", "-m", "three")
    stray = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/zed", stray)
    _git(repo, "update-ref", "refs/carnivore/iid-x/main", stray)
    tagged = _git(repo, "commit-tree", second + "^{tree}", "-p", second, "-m", "only the tag holds this")
    _git(repo, "tag", "-a", "-m", "v2", "v2", tagged)
    _git(repo, "reset", "-q", "--hard", second)
    store = JobStore(tmp_path / "state")
    far = Far(store)
    project = {"uid": UID, "display_name": "trader", "root": str(repo)}
    engine = SimpleNamespace(store=store, list=lambda **kw: store.list_jobs(limit=kw.get("limit", 50), project_uid=kw.get("project_uid"),
                                                                            live_only=kw.get("live_only", False)))
    monkeypatch.setattr(boot, "engine", lambda: engine)
    monkeypatch.setattr(routes, "_read_project", lambda name: {
        "project": project, "install_id": ME, "label": "mini", "role": "home", "refusal": None, "other": None,
        "replicas": [{"install_id": "iid-new", "label": "studio", "root": "/r/trader", "created_at": 5.0},
                     {"install_id": "iid-old", "label": "tower", "root": "/o/trader", "created_at": 6.0},
                     {"install_id": "iid-hand", "label": "odin", "root": "/h/trader", "created_at": 7.0}]})
    monkeypatch.setattr(routes.bundles, "is_repo", lambda path: True)
    monkeypatch.setattr(wipe, "_ask", far.ask)
    monkeypatch.setattr(wipe, "_capable", lambda iid: iid in ("iid-new", "iid-hand"))
    home_rows: List[str] = []
    monkeypatch.setattr(wipe, "_forget_home_row", lambda uid, iid: home_rows.append(iid))
    detached: List[str] = []

    async def fake_remove(name: str, machine: str):
        detached.append(machine)
        return {}

    monkeypatch.setattr(project_replica_routes, "remove_project_replica", fake_remove)
    store.auto_replica_add(UID, "iid-new")
    store.auto_replica_add(UID, "iid-old")
    policy.set_auto(store, UID, True)
    return SimpleNamespace(store=store, far=far, repo=repo, second=second, first=first, stray=stray, tagged=tagged, detached=detached, home_rows=home_rows,
                           engine=engine, mp=monkeypatch)


def _client(auth: bool = True) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    if auth:
        app.dependency_overrides[require_auth] = lambda: None
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def _off(**body: Any) -> httpx.Response:
    async with _client() as c:
        if body.get("delete_copies") and "delete_only" not in body:
            body["delete_only"] = ["iid-new", "iid-old", "iid-hand"]
        return await c.put(URL, json={"on": False, "wipe_others": True, **body})


@pytest.mark.asyncio
async def test_delete_false_never_calls_forget_copy(world):
    r = await _off(wipe_others=True)
    assert r.status_code == 200 and world.far.calls == []
    assert sorted(world.detached) == ["iid-new", "iid-old"] and r.json()["deleted"] == [] and r.json()["kept"] == []
    assert (await _off()).json()["handoff"] is None and world.far.calls == []


@pytest.mark.asyncio
async def test_delete_asks_only_the_capable_made_copy_after_the_mark_is_off(world):
    r = await _off(delete_copies=True)
    body = r.json()
    assert r.status_code == 200
    assert [c[0] for c in world.far.calls] == ["iid-new"] and world.far.calls[0][1]["dry_run"] is False
    assert world.far.marks == [False] and policy.get(world.store, UID).auto_delegate is False
    assert body["deleted"] == [{"label": "studio", "root": "/far/iid-new", "code": ""}]
    assert body["kept"] == [{"label": "tower", "code": "needs_update", "root": "/o/trader"}]
    assert world.home_rows == ["iid-new"] and world.detached == ["iid-old"]
    assert world.store.auto_replica_list(UID) == []


@pytest.mark.asyncio
async def test_kept_timeout_refusal_unreachable_and_garbage_are_detached_with_a_code(world):
    world.store.auto_replica_add(UID, "iid-hand")
    cases = [("iid-new", {"verdict": "kept", "code": "dirty", "root": "/r/trader"}, "dirty"),
             ("iid-hand", HTTPException(502, {"code": "machine_unreachable"}), "unreachable")]
    for iid, answer, _ in cases:
        world.far.answers[iid] = answer
    r = await _off(delete_copies=True)
    kept = {k["label"]: k["code"] for k in r.json()["kept"]}
    assert r.status_code == 200 and kept == {"studio": "dirty", "odin": "unknown", "tower": "needs_update"}
    assert sorted(world.detached) == ["iid-new", "iid-old"]
    for answer, code in [(HTTPException(409, {"code": "x"}), "refused"), ({"verdict": "deleted", "code": "weird"}, "bad_answer"),
                         ("not json", "bad_answer"), ({"verdict": "kept", "code": "made_up"}, "bad_answer"),
                         ({"verdict": "deletable", "code": ""}, "bad_answer"), ({"verdict": "deleted", "code": "", "ignored_more": -1}, "bad_answer"),
                         ({"verdict": "deleted", "code": "", "ignored": [5]}, "bad_answer")]:
        far = await wipe.ask_one("iid-new", UID, [], dry_run=False, ask=lambda i, b, a=answer: _raise_or(a))
        assert (far.verdict, far.code) == ("kept", code), answer


async def _raise_or(answer: Any) -> Any:
    if isinstance(answer, Exception):
        raise answer
    return answer


@pytest.mark.asyncio
async def test_real_ask_that_times_out_is_unknown_and_is_not_detached_or_recorded(world):
    world.far.answers["iid-new"] = HTTPException(502, {"code": "machine_unreachable"})
    r = await _off(delete_copies=True)
    assert r.status_code == 200 and {"label": "studio", "code": "unknown", "root": "/r/trader"} in r.json()["kept"]
    assert "iid-new" not in world.detached and policy.detached_root(world.store, UID, "iid-new") is None
    assert [b["dry_run"] for i, b in world.far.calls if i == "iid-new"] == [False, True]


@pytest.mark.asyncio
async def test_lost_answer_then_no_record_means_it_was_deleted(world):
    answers = iter([HTTPException(502, {"code": "machine_unreachable"}), {"verdict": "kept", "code": "no_record", "root": ""}])

    async def ask(iid: str, body: Dict[str, Any]) -> Any:
        return await _raise_or(next(answers))

    world.mp.setattr(wipe, "_ask", ask)
    r = await _off(delete_copies=True, delete_only=["iid-new"])
    assert r.json()["deleted"][0]["label"] == "studio" and "iid-new" not in world.detached


@pytest.mark.asyncio
async def test_no_record_on_a_real_ask_is_detached_without_remembering_the_folder(world):
    world.far.answers["iid-new"] = {"verdict": "kept", "code": "no_record", "root": ""}
    r = await _off(delete_copies=True)
    assert "iid-new" in world.detached and policy.detached_root(world.store, UID, "iid-new") is None
    assert {"label": "studio", "code": "no_record", "root": "/r/trader"} in r.json()["kept"]


@pytest.mark.asyncio
async def test_one_leftover_copy_trash_leaves_every_other_copy_registered(world):
    async with _client() as c:
        r = await c.put(URL, json={"on": False, "delete_copies": True, "delete_only": ["iid-new"]})
        assert r.json()["deleted"][0]["label"] == "studio" and world.detached == []
        r = await c.put(URL, json={"on": False, "delete_copies": True, "delete_only": ["iid-old"]})
    assert r.json()["kept"][0]["code"] == "needs_update" and world.detached == []
    assert world.store.auto_replica_list(UID) == ["iid-old"]


@pytest.mark.asyncio
async def test_only_the_confirmed_copies_are_asked(world):
    r = await _off(delete_copies=True, delete_only=[])
    assert world.far.calls == [] and {k["code"] for k in r.json()["kept"]} >= {"not_chosen"} and "iid-new" in world.detached
    r = await _client().put(URL, json={"on": False, "wipe_others": True, "delete_copies": True})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "delete_only_required"


@pytest.mark.asyncio
async def test_a_real_forget_gets_a_longer_peer_limit_than_a_dry_run(world):
    import asyncio

    seen: List[float] = []

    async def fake_call(peer: Any, method: str, path: str, body: Any = None, *, timeout: float = 20.0) -> Any:
        seen.append(timeout)
        return {"verdict": "deletable", "code": ""}

    world.mp.setattr(wipe, "_ask", _REAL_ASK)
    world.mp.setattr(project_replica_routes, "find_peer", lambda m: SimpleNamespace(peer_install_id=m, label=m, key=m))
    world.mp.setattr(project_replica_routes, "call_peer", fake_call)
    await wipe._ask("iid-new", {"dry_run": True})
    await wipe._ask("iid-new", {"dry_run": False})
    assert seen[0] == project_replica_routes.PEER_TIMEOUT_SECONDS and seen[1] > 100 and wipe.ASK_REAL_TIMEOUT_S > seen[1]
    assert asyncio  # noqa


@pytest.mark.asyncio
async def test_call_peer_takes_its_own_limit(monkeypatch):
    import asyncio
    from src.core.federation import peer_links

    class Client:
        async def request(self, *a: Any, **k: Any) -> Any:
            await asyncio.sleep(0.2)
            return SimpleNamespace(status_code=200, json=lambda: {"ok": True})

    monkeypatch.setattr(peer_links, "LINKS", SimpleNamespace(client=lambda i: Client()))
    monkeypatch.setattr(project_replica_routes, "PEER_TIMEOUT_SECONDS", 0.05)
    peer = SimpleNamespace(peer_install_id="i", label="x")
    with pytest.raises(HTTPException):
        await project_replica_routes.call_peer(peer, "POST", "/x", {}, timeout=0.05)
    assert await project_replica_routes.call_peer(peer, "POST", "/x", {}, timeout=2.0) == {"ok": True}


@pytest.mark.asyncio
async def test_two_offs_for_one_project_run_one_after_the_other(world):
    import asyncio

    r1, r2 = await asyncio.gather(_off(delete_copies=True), _off(delete_copies=True))
    assert r1.json()["deleted"] and r2.json()["deleted"] == [] and r2.json()["kept"] == []
    assert [c[0] for c in world.far.calls] == ["iid-new"]


@pytest.mark.asyncio
async def test_keep_by_label_is_this_computer_only_when_no_paired_computer_has_it(world, monkeypatch):
    found = {"install_id": ME, "label": "mini"}
    assert await routes._keeper(found, None) is None and await routes._keeper(found, ME) is None
    monkeypatch.setattr(project_replica_routes, "find_peer", lambda m: (_ for _ in ()).throw(HTTPException(404, {"code": "unknown_machine"})))
    assert await routes._keeper(found, "MINI") is None
    with pytest.raises(HTTPException):
        await routes._keeper(found, "ghost")
    found["replicas"] = []
    monkeypatch.setattr(project_replica_routes, "find_peer", lambda m: SimpleNamespace(peer_install_id="iid-x", label="Mini", key="k"))
    with pytest.raises(HTTPException):
        await routes._keeper(found, "mini")


@pytest.mark.asyncio
async def test_far_text_is_cleaned_and_capped():
    far = wipe.parse_answer({"verdict": "kept", "code": "dirty", "root": "/a\x1b[31mb" + "x" * 5000,
                             "ignored": [f"n\x00{i}" + "y" * 900 for i in range(25)], "ignored_more": 3}, dry_run=True)
    assert "\x1b" not in far.root and len(far.root) <= 1024 and len(far.ignored) == 20 and far.ignored_more == 8
    assert all("\x00" not in n and len(n) <= 256 for n in far.ignored)


@pytest.mark.asyncio
async def test_keep_skips_the_keeper_and_answers_handoff(world, monkeypatch):
    world.store.auto_replica_add(UID, "iid-hand")
    peers = [rule.MachineInput(i, l, {"restrictions": {}}, True, False, False, True, None) for i, l in
             [("iid-new", "studio"), ("iid-old", "tower"), ("iid-hand", "odin")]]
    monkeypatch.setattr(place, "live_view", lambda root, uid: place.PlaceView(rule.MachineInput(ME, "mini", {}, True, True, True, True, None), peers))
    monkeypatch.setattr(project_replica_routes, "find_peer", lambda m: SimpleNamespace(peer_install_id={"studio": "iid-new"}.get(m, "iid-zzz"),
                                                                                       label=m, key=m))
    r = await _off(delete_copies=True, keep="studio")
    assert r.status_code == 200 and r.json()["handoff"] == {"machine": "iid-new", "label": "studio"}
    assert "iid-new" not in [c[0] for c in world.far.calls] and "iid-new" not in world.detached
    assert [c[0] for c in world.far.calls] == ["iid-hand"]


@pytest.mark.asyncio
async def test_bad_keep_is_409_and_the_mark_stays_on(world, monkeypatch):
    calls = {"peer": "iid-zzz", "usable": True, "snap": {"restrictions": {}}}
    monkeypatch.setattr(project_replica_routes, "find_peer", lambda m: (_ for _ in ()).throw(HTTPException(404, {"code": "unknown_machine"}))
                        if m == "ghost" else SimpleNamespace(peer_install_id=calls["peer"], label=m, key=m))

    def view(root: str, uid: str) -> Any:
        peer = rule.MachineInput("iid-new", "studio", calls["snap"], calls["usable"], False, False, True, None)
        return place.PlaceView(rule.MachineInput(ME, "mini", {}, True, True, True, True, None), [peer])

    monkeypatch.setattr(place, "live_view", view)
    for keep, setup, code in [("ghost", {}, "keep_unknown"), ("x", {"peer": "iid-nope"}, "keep_no_copy"),
                              ("x", {"peer": "iid-new", "usable": False}, "keep_offline"),
                              ("x", {"peer": "iid-new", "usable": True, "snap": {"restrictions": {"may_receive_projects": False}}}, "keep_cannot_receive"),
                              ("x", {"peer": "iid-new", "snap": None}, "keep_cannot_receive")]:
        calls.update({"peer": "iid-zzz", "usable": True, "snap": {"restrictions": {}}, **setup})
        r = await _off(delete_copies=True, keep=keep)
        assert r.status_code == 409 and r.json()["detail"]["code"] == code, code
        assert policy.get(world.store, UID).auto_delegate is True and world.far.calls == [] and world.detached == []


@pytest.mark.asyncio
async def test_jobs_running_refuses_first_and_nothing_is_called(world):
    world.store.create_job(JobRecord(id="job_000000000009", project_uid=UID, state=JobState.RUNNING))
    r = await _off(delete_copies=True)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "jobs_running"
    assert world.far.calls == [] and world.detached == [] and policy.get(world.store, UID).auto_delegate is True


@pytest.mark.asyncio
async def test_delete_on_a_turn_on_is_refused(world):
    r = await _client().put(URL, json={"on": True, "delete_copies": True})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "delete_copies_needs_off"


def test_tips_hold_heads_and_tags_only(world):
    tips, code = wipe.home_tips(str(world.repo))
    assert code == "" and world.second in tips and world.first in tips and world.tagged in tips
    assert world.stray not in tips
    assert all(len(t) == 40 for t in tips) and tips == sorted(set(tips))
    assert wipe.home_tips(str(world.repo / "nope")) == ([], "git_failed")


@pytest.mark.asyncio
async def test_too_many_refs_asks_nobody(world, monkeypatch):
    monkeypatch.setattr(wipe, "MAX_TIPS", 1)
    assert wipe.home_tips(str(world.repo)) == ([], "too_many_refs")
    r = await _off(delete_copies=True)
    assert r.status_code == 200 and world.far.calls == [] and {k["code"] for k in r.json()["kept"]} == {"too_many_refs"}
    assert sorted(world.detached) == ["iid-new", "iid-old"]
    monkeypatch.setattr(wipe, "home_tips", lambda root: ([], "git_failed"))
    world.store.auto_replica_add(UID, "iid-new")
    world.store.auto_replica_add(UID, "iid-old")
    r = await _off(delete_copies=True)
    assert world.far.calls == [] and {k["code"] for k in r.json()["kept"]} == {"git_failed"}


@pytest.mark.asyncio
async def test_2001_real_refs_ask_nobody(world):
    stdin = "".join(f"create refs/heads/h{i} {_git(world.repo, 'commit-tree', world.second + '^{tree}', '-m', f'c{i}')}\n" for i in range(2001))
    subprocess.run(["git", "-C", str(world.repo), "update-ref", "--stdin"], input=stdin, text=True, check=True, capture_output=True)
    assert wipe.home_tips(str(world.repo)) == ([], "too_many_refs")
    r = await _off(delete_copies=True)
    assert world.far.calls == [] and {k["code"] for k in r.json()["kept"]} == {"too_many_refs"}


@pytest.mark.asyncio
async def test_copy_check_is_owner_only_and_writes_nothing(world):
    async with _client() as c:
        denied = await c.post(URL + "/copy-check", headers={"Authorization": "Bearer cak_abcdef"})
        assert denied.status_code == 403 and denied.json()["detail"]["code"] == "mark_owner_only" and world.far.calls == []
        before = (world.store.auto_replica_list(UID), policy.get(world.store, UID).auto_delegate, sorted(p.name for p in world.repo.iterdir()))
        world.far.answers["iid-new"] = {"verdict": "deletable", "code": "", "root": "/far/new", "ignored": ["notes.txt"], "ignored_more": 2}
        got = (await c.post(URL + "/copy-check")).json()["copies"]
    assert got == [{"install_id": "iid-new", "label": "studio", "root": "/far/new", "verdict": "deletable", "code": "", "ignored": ["notes.txt"], "ignored_more": 2},
                   {"install_id": "iid-old", "label": "tower", "root": "/o/trader", "verdict": "kept", "code": "needs_update", "ignored": [], "ignored_more": 0}]
    assert [c[0] for c in world.far.calls] == ["iid-new"] and world.far.calls[0][1]["dry_run"] is True and world.far.marks == [True]
    assert world.detached == [] and world.home_rows == []
    assert before == (world.store.auto_replica_list(UID), policy.get(world.store, UID).auto_delegate, sorted(p.name for p in world.repo.iterdir()))


@pytest.mark.asyncio
async def test_copy_check_names_a_copy_with_no_record(world):
    world.far.answers["iid-new"] = {"verdict": "kept", "code": "no_record", "root": "/r/trader"}
    async with _client() as c:
        got = (await c.post(URL + "/copy-check")).json()["copies"]
    assert got[0]["code"] == "no_record" and got[0]["verdict"] == "kept" and got[0]["root"] == "/r/trader"


@pytest.mark.asyncio
async def test_a_reattached_folder_is_not_marked_made_and_a_no_record_trash_forgets_the_mark(world):
    from src.core.pack.jobs import replicas as jobs_replicas

    async def reattach(name, body):
        return {"replica": {"created": False, "folder_made": False}}

    async def made(name, body):
        return {"replica": {"created": True, "folder_made": True}}

    assert await jobs_replicas.ensure("trader", UID, "iid-r1", store=world.store, add=reattach, has=lambda u, i: False) is True
    assert "iid-r1" not in world.store.auto_replica_list(UID)
    assert await jobs_replicas.ensure("trader", UID, "iid-r2", store=world.store, add=made, has=lambda u, i: False) is True
    assert "iid-r2" in world.store.auto_replica_list(UID)
    world.far.answers["iid-new"] = {"verdict": "kept", "code": "no_record", "root": ""}
    async with _client() as c:
        r = await c.put(URL, json={"on": False, "delete_copies": True, "delete_only": ["iid-new"]})
    assert r.json()["kept"][0]["code"] == "no_record" and "iid-new" not in world.store.auto_replica_list(UID)
