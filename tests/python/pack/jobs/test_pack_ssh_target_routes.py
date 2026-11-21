
from __future__ import annotations

import base64
import json
import re
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from tests.layouts_helpers import migrated  # noqa: F401

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import pack_jobs_routes, pack_ssh_target_routes as routes
from src.api.auth import require_auth
from src.api.hosts_routes import router as hosts_router
from src.core.db import connect
from src.core.mcp import pack_jobs_tools, tools as mcp_tools
from src.core.mcp import route_adapters as ra
from src.core.mcp.approvals import display
from src.core.pack.jobs import boot, carry, copy_run, place
from src.core.pack.jobs.ssh import conn, far_script, owner, readings as readings_mod
from src.core.pack.jobs.ssh.readings import Link, Readings
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import JobError, JobRecord, JobRequest, JobState

KEY_LINE = "ssh-ed25519 " + base64.b64encode(b"\x00\x00\x00\x0bssh-ed25519" + bytes(range(40))).decode()
FP = conn.fingerprint_of(KEY_LINE)
OTHER_FP = "SHA256:" + "B" * 43
API = "/api/v1/pack/ssh-targets"
PROBE = ["uname Linux 5.15.133.1-microsoft-standard-WSL2 x86_64", "cores 24", "memtotal_kb 33554432", "disk_free_kb 524288000",
         "gpu NVIDIA GeForce RTX 4090, 24564", "tool git /usr/bin/git"]
PRESSURE = ["cores 24", "loadavg 0.50 0.4 0.3 1/200 99", "stat cpu  100 0 100 9800 0 0 0 0", "memavail_kb 30000000", "disk_free_kb 524288000"]


def ans(*lines: str) -> far_script.FarAnswer:
    out = far_script.FarAnswer(rc=0)
    for line in lines:
        out.lines.append(line)
        key, _sp, value = line.partition(" ")
        out.fields[key] = value
    return out


class FarStub:

    def __init__(self) -> None:
        self.calls: List[Any] = []
        self.answers: Dict[str, Any] = {"hello": ans("uname Linux 5.15 x86_64", "wsl 1", "git 2.43.0", "tool setsid /usr/bin/setsid", "tool flock -"),
                                        "forget": ans("forgotten"), "sweep": ans("swept 0")}

    async def _far(self, verb: str, values: Optional[Dict[str, str]] = None, **_kw: Any) -> far_script.FarAnswer:
        self.calls.append((verb, dict(values or {})))
        got = self.answers[verb]
        if isinstance(got, Exception):
            raise got
        return got


class StubConn:

    def __init__(self, silent: bool = False) -> None:
        self.silent = silent

    async def call(self, script: bytes, timeout: float) -> Any:
        text = script.decode()
        verb, nonce = re.search(r"CVJ_VERB='(\w+)'", text).group(1), re.search(r"CVJ_NONCE='([0-9a-f]+)'", text).group(1)
        if self.silent:
            return SimpleNamespace(failure="timed_out", stdout=b"")
        lines = {"probe": PROBE, "pressure": PRESSURE}[verb]
        return SimpleNamespace(failure=None, stdout=("".join(f"CVJ{nonce} {x}\n" for x in lines) + f"CVJ{nonce} end 0\n").encode())


class World:

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.config import settings

        self.state = tmp_path / "state"
        self.db = migrated(self.state)
        monkeypatch.setattr(type(settings), "get_state_dir", lambda self_: self.state, raising=True)
        self.store = JobStore(self.state)
        self.far = FarStub()
        self.silent: set = set()
        self.contacts = 0
        owner._PROBED.clear()
        monkeypatch.setattr(boot, "engine", lambda: SimpleNamespace(store=self.store, list=lambda **kw: self.store.list_jobs(**kw)))
        monkeypatch.setattr(owner, "ssh_target_for", lambda host_key: self.far)
        monkeypatch.setattr(readings_mod, "_SHARED", {"readings": Readings(self.store, lambda hk: Link(f"box-{hk[:4]}", StubConn(hk in self.silent)))})
        monkeypatch.setattr(readings_mod, "default_link", lambda hk: Link(f"box-{hk[:4]}", StubConn()))
        monkeypatch.setattr(owner, "first_contact_key", self._contact)
        app = FastAPI()
        app.include_router(hosts_router, prefix="/api/v1")
        app.include_router(routes.router, prefix="/api/v1")
        app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
        self.client = TestClient(app)
        self.shown = (FP, "ED25519", KEY_LINE, "new")

    async def _contact(self, host: Any) -> Any:
        self.contacts += 1
        return self.shown

    def add_host(self, label: str = "Box", **columns: Any) -> str:
        key = self.client.post("/api/v1/hosts", json={"label": label, "ssh_target": f"{label.lower()}.example", "ssh_port": 2222}).json()["key"]
        columns = {"enabled": 1, **columns}
        with closing(connect(self.db, create=False)) as c:
            c.execute(f"UPDATE hosts SET {','.join(f'{k}=?' for k in columns)} WHERE key=?", [*columns.values(), key])
            c.commit()
        return key

    def pin(self, key: str, takes_work: int = 1) -> None:
        self.store.ssh_target_put(key, takes_work=takes_work, pinned_fp=FP)

    def live_job(self, key: str) -> None:
        self.store.create_job(JobRecord(id="job_00000000a1b2", project_uid="uid12345678", state=JobState.RUNNING, peer_install_id="ssh:" + key))


@pytest.fixture()
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return World(tmp_path, monkeypatch)


def test_every_route_refuses_an_api_key(world: World) -> None:
    key = world.add_host()
    headers = {"Authorization": "Bearer cak_not_a_real_key"}
    calls = [world.client.get(API, headers=headers), world.client.put(f"{API}/{key}", json={"takes_work": True}, headers=headers),
             world.client.post(f"{API}/{key}/probe", headers=headers), world.client.delete(f"{API}/{key}/folders", headers=headers)]
    assert [r.status_code for r in calls] == [403] * 4
    assert {r.json()["detail"]["code"] for r in calls} == {"ssh_target_owner_only"}
    assert world.store.ssh_target_get(key) is None and world.far.calls == []


def test_takes_work_on_without_the_fingerprint_is_409_and_pins_nothing(world: World) -> None:
    key = world.add_host()
    r = world.client.put(f"{API}/{key}", json={"takes_work": True, "labels": ["gpu box"]})
    detail = r.json()["detail"]
    assert r.status_code == 409 and detail["code"] == "confirm_host_key"
    assert detail["fingerprints"] == [{"sha256": FP, "type": "ED25519"}] and detail["known"] == "new" and detail["pinned"] is None
    assert detail["changed_since_shown"] is False
    assert world.store.ssh_target_get(key) is None and not conn.known_hosts_path(world.state).exists() and world.far.calls == []


def test_the_right_fingerprint_pins_once_and_a_wrong_one_pins_nothing(world: World) -> None:
    key = world.add_host()
    wrong = world.client.put(f"{API}/{key}", json={"takes_work": True, "host_key_sha256": OTHER_FP})
    assert wrong.status_code == 409 and wrong.json()["detail"]["changed_since_shown"] is True and world.store.ssh_target_get(key) is None
    ok = world.client.put(f"{API}/{key}", json={"takes_work": True, "host_key_sha256": FP, "labels": ["RTX 4090"]})
    assert ok.status_code == 200, ok.text
    row = world.store.ssh_target_get(key)
    assert row["pinned_fp"] == FP and row["takes_work"] == 1 and json.loads(row["labels_json"]) == ["rtx 4090"]
    assert conn.known_hosts_path(world.state).read_text().count(conn.host_alias(key)) == 1
    assert [c[0] for c in world.far.calls] == ["hello"] and ok.json()["target"]["state"] == "taking_work"
    contacts = world.contacts
    again = world.client.put(f"{API}/{key}", json={"takes_work": True, "host_key_sha256": FP})
    assert again.status_code == 200 and world.contacts == contacts
    assert conn.known_hosts_path(world.state).read_text().count(conn.host_alias(key)) == 1


def test_an_existing_pin_is_replaced_only_by_the_owners_new_fingerprint(world: World) -> None:
    key = world.add_host()
    world.client.put(f"{API}/{key}", json={"takes_work": True, "host_key_sha256": FP})
    new_line = "ssh-ed25519 " + base64.b64encode(b"\x00\x00\x00\x0bssh-ed25519" + bytes(range(50, 90))).decode()
    world.shown = (conn.fingerprint_of(new_line), "ED25519", new_line, "changed")
    asked = world.client.put(f"{API}/{key}", json={"takes_work": True})
    body = asked.json()["detail"]
    assert asked.status_code == 409 and body["code"] == "confirm_host_key" and body["fingerprints"][0]["sha256"] == world.shown[0]
    assert body["pinned"] == FP and world.store.ssh_target_get(key)["pinned_fp"] == FP
    refused = world.client.put(f"{API}/{key}", json={"takes_work": True, "host_key_sha256": OTHER_FP})
    assert refused.status_code == 409 and world.store.ssh_target_get(key)["pinned_fp"] == FP
    swapped = world.client.put(f"{API}/{key}", json={"takes_work": True, "host_key_sha256": world.shown[0]})
    assert swapped.status_code == 200 and world.store.ssh_target_get(key)["pinned_fp"] == world.shown[0]
    text = conn.known_hosts_path(world.state).read_text()
    assert text.count(conn.host_alias(key)) == 1 and new_line in text and KEY_LINE not in text


def test_a_fingerprint_of_the_wrong_shape_is_422(world: World) -> None:
    key = world.add_host()
    for bad in ("SHA256:short", "MD5:" + "a" * 43, FP + "x", ""):
        assert world.client.put(f"{API}/{key}", json={"takes_work": True, "host_key_sha256": bad}).status_code == 422
    assert world.store.ssh_target_get(key) is None and world.contacts == 0


def test_a_paired_computer_and_a_host_with_carnivore_are_not_job_targets(world: World) -> None:
    paired = world.add_host("Studio", computer_install_id="iid-studio")
    runs = world.add_host("Mini", remote_carnivore="running")
    off = world.add_host("Dark", enabled=0)
    for key, why in ((paired, "paired_computer"), (runs, "runs_carnivore")):
        r = world.client.put(f"{API}/{key}", json={"takes_work": True, "host_key_sha256": FP})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "not_a_job_target" and r.json()["detail"]["reason"] == why
        assert world.store.ssh_target_get(key) is None
    assert world.client.put(f"{API}/{off}", json={"takes_work": True, "host_key_sha256": FP}).json()["detail"]["reason"] == "host_disabled"
    shown = {t["host_key"]: t for t in world.client.get(API).json()["targets"]}
    assert paired not in shown and shown[runs]["state"] == "not_a_job_target" and shown[off]["state"] == "host_disabled"
    assert world.client.put(f"{API}/nosuchhost", json={"takes_work": False}).status_code == 404


def test_a_computer_without_the_tools_stays_off(world: World) -> None:
    key = world.add_host()
    world.far.answers["hello"] = JobError("missing_tools", "git,setsid", 409)
    r = world.client.put(f"{API}/{key}", json={"takes_work": True, "host_key_sha256": FP})
    assert r.status_code == 409 and r.json()["detail"]["reason"] == "missing_tools"
    assert world.store.ssh_target_get(key)["takes_work"] == 0


TARGET_KEYS = {"host_key": str, "label": str, "ssh_target": str, "enabled": bool, "state": str, "takes_work": bool, "pinned": bool, "labels": list,
               "reserve_config": dict, "usable": bool, "live_jobs": int}


def test_the_list_answers_every_state(world: World) -> None:
    fresh, off, unconfirmed, answers, silent = (world.add_host(n) for n in ("Fresh", "Off", "Unconfirmed", "Answers", "Silent"))
    world.store.ssh_target_put(off, takes_work=0, pinned_fp=FP)
    world.store.ssh_target_put(unconfirmed, takes_work=1)
    world.pin(answers)
    world.pin(silent)
    world.silent.add(silent)
    world.live_job(answers)
    got = {t["host_key"]: t for t in world.client.get(API).json()["targets"]}
    assert {k: got[k]["state"] for k in got} == {fresh: "not_set_up", off: "off", unconfirmed: "host_key_not_confirmed", answers: "taking_work", silent: "did_not_answer"}
    one = got[answers]
    for name, kind in TARGET_KEYS.items():
        assert isinstance(one[name], kind), name
    assert one["usable"] is True and one["live_jobs"] == 1 and one["fingerprint"] == FP and one["can"]["os"] == "linux" and "wsl" in one["can"]["labels"]
    assert one["load"]["cores"] == 24 and one["pressure"]["pegged"] is False and one["reason"] is None
    assert got[silent]["usable"] is False and got[silent]["load"] is None and got[silent]["reason"] == readings_mod.NO_ANSWER
    assert got[fresh]["can"] is None and got[fresh]["fingerprint"] is None


def test_the_probe_is_limited_to_one_a_minute(world: World) -> None:
    key = world.add_host()
    world.pin(key)
    first = world.client.post(f"{API}/{key}/probe").json()
    assert first["fresh"] is True and first["hello"]["wsl"] is True and first["hello"]["tools"] == ["setsid"] and first["hello"]["far_jobs"] == 0
    assert first["target"]["can"]["gpus"][0]["model"].startswith("NVIDIA")
    second = world.client.post(f"{API}/{key}/probe").json()
    assert second["fresh"] is False and second["hello"] is None
    assert [c[0] for c in world.far.calls] == ["hello"]
    other = world.add_host("Other")
    world.pin(other)
    assert world.client.post(f"{API}/{other}/probe").json()["fresh"] is True
    paired = world.add_host("Paired", computer_install_id="iid-p")
    assert world.client.post(f"{API}/{paired}/probe").status_code == 409


def test_deleting_a_host_with_a_live_job_is_409_and_an_idle_one_drops_both_rows(world: World) -> None:
    busy, idle = world.add_host("Busy"), world.add_host("Idle")
    for key in (busy, idle):
        world.client.put(f"{API}/{key}", json={"takes_work": True, "host_key_sha256": FP})
        world.store.ssh_seed_set("uid12345678", key, "abc")
    world.live_job(busy)
    r = world.client.delete(f"/api/v1/hosts/{busy}")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "host_in_use"
    assert world.store.ssh_target_get(busy) is not None and world.store.ssh_seeds_for(busy) == ["uid12345678"]
    assert world.client.get(f"/api/v1/hosts/{busy}").status_code == 200
    gone = world.client.delete(f"/api/v1/hosts/{idle}")
    assert gone.status_code == 409 and gone.json()["detail"]["code"] == "host_has_copies" and world.store.ssh_target_get(idle) is not None
    world.store.ssh_seed_drop("uid12345678", idle)
    assert world.client.delete(f"/api/v1/hosts/{idle}").status_code == 200
    assert world.store.ssh_target_get(idle) is None and world.store.ssh_seeds_for(idle) == []
    assert conn.host_alias(idle) not in conn.known_hosts_path(world.state).read_text()
    assert world.client.get(f"/api/v1/hosts/{idle}").status_code == 404 and world.store.ssh_target_get(busy)["pinned_fp"] == FP


def test_the_folders_delete_refuses_under_a_live_job_and_names_a_kept_slot(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    key = world.add_host()
    world.pin(key)
    for uid in ("uidaaaaaaaa", "uidbbbbbbbb", "uidgone0000"):
        world.store.ssh_seed_set(uid, key, "abc")
    world.live_job(key)
    r = world.client.delete(f"{API}/{key}/folders")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "jobs_running" and world.far.calls == []
    world.store.set_state("job_00000000a1b2", JobState.DONE)
    forget_answers = {"uidaaaaaaaa": ans("kept /far/folders/x/slot2", "cache_kept 1", "forgotten"), "uidbbbbbbbb": JobError("still_running", "no", 409),
                      "uidgone0000": ans("forgotten")}

    async def far(verb: str, values: Optional[Dict[str, str]] = None, **_kw: Any) -> far_script.FarAnswer:
        world.far.calls.append((verb, dict(values or {})))
        got = forget_answers[values["uid"]] if verb == "forget" else ans("swept 0")
        if isinstance(got, Exception):
            raise got
        return got

    monkeypatch.setattr(world.far, "_far", far)
    done = world.client.delete(f"{API}/{key}/folders").json()
    assert world.store.ssh_seeds_for(key) == ["uidaaaaaaaa", "uidbbbbbbbb"]
    assert done["kept"] == [{"project": "uidaaaaaaaa", "slot": "slot2"}]
    assert done["forgotten"] == ["uidaaaaaaaa", "uidgone0000"] and done["refused"] == [{"project": "uidbbbbbbbb", "code": "still_running"}]
    assert [c[0] for c in world.far.calls] == ["forget", "forget", "forget", "sweep"]


@pytest.mark.asyncio
async def test_marking_a_project_seeds_a_target_that_takes_work_and_never_a_never_use_one(world: World, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from src.core.pack.jobs import policy

    ids = [world.add_host(n) for n in ("Takes", "ById", "ByLabel", "Off")]
    takes, by_id, by_label, off = ids
    for key in (takes, by_id, by_label):
        world.pin(key)
    world.pin(off, takes_work=0)
    policy.set_lists(world.store, "uid12345678", never_use=[f"ssh:{by_id}", f"box-{by_label[:4]}"])

    def refuse_pack(_root: str, _uid: str) -> None:
        raise JobError("jobs_not_ready", "no pack", 503)

    monkeypatch.setattr(place, "live_view", refuse_pack)
    monkeypatch.setattr(copy_run, "finish", lambda *a, **k: None)
    monkeypatch.setattr(pack_jobs_routes.home, "notify_changed", lambda: None)
    root = tmp_path / "app"
    root.mkdir()
    await pack_jobs_routes._ensure(SimpleNamespace(store=world.store), "app", "uid12345678", str(root))
    seeded = [k for k in ids if world.store.ssh_seed_get("uid12345678", k) is not None]
    assert seeded == [takes]


def test_the_card_says_over_ssh_in_at_most_three_lines() -> None:
    args = {"computer": "aibox", "command": "nvidia-smi", "folder": "/Users/you/app", "ssh": True}
    block = display.build("delegate", args, "", "s")
    assert [c["key"] for c in block["consequences"]] == ["delegate_runs_ssh", "delegate_copy"] and len(block["consequences"]) <= 3
    assert block["consequences"][0]["params"] == {"command": "nvidia-smi", "computer": "aibox"}
    assert [c["key"] for c in display.build("delegate", {**args, "installs": ["ffmpeg"]}, "", "s")["consequences"]] == ["delegate_runs_ssh", "delegate_installs", "delegate_copy"]
    assert display.build("delegate", {k: v for k, v in args.items() if k != "ssh"}, "", "s")["consequences"][0]["key"] == "delegate_runs"
    catalog = (Path(__file__).resolve().parents[4] / "client" / "js" / "i18n" / "catalog.en.js").read_text(encoding="utf-8")
    assert "'approvals.display.c.delegate_runs_ssh': 'runs {command} on {computer} over ssh (no carnivore there)'" in catalog


def test_the_delegate_card_marks_an_ssh_job_and_only_that() -> None:
    request = JobRequest(command="nvidia-smi", folder="/p/app")
    on_ssh = JobRecord(id="job_000000000001", peer_label="aibox", peer_install_id="ssh:" + "a" * 32)
    on_pack = JobRecord(id="job_000000000002", peer_label="studio", peer_install_id="iid-studio")
    assert pack_jobs_tools._card({}, request, on_ssh)["ssh"] is True
    assert "ssh" not in pack_jobs_tools._card({}, request, on_pack)


@pytest.mark.asyncio
async def test_the_read_tool_is_read_only_and_leaks_no_state_folder_path(world: World) -> None:
    key = world.add_host()
    world.pin(key)
    assert "ssh_targets_list" in mcp_tools._TOOLS and "ssh_targets_list" not in mcp_tools.WRITE_TOOLS
    assert mcp_tools.ROUTE_GATES["ssh_targets_list"] == ra.READ
    assert not [n for n in mcp_tools._TOOLS if n.startswith("ssh_target") and n != "ssh_targets_list"]
    answer = await routes.list_targets()
    text = json.dumps(answer)
    assert answer["targets"][0]["host_key"] == key and answer["targets"][0]["state"] == "taking_work"
    assert str(world.state) not in text and str(Path.home()) not in text and "known_hosts" not in text
