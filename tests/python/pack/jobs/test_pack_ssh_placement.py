
from __future__ import annotations

import asyncio
import dataclasses
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from src.core.pack.jobs import place
from src.core.pack.jobs.policy import Policy
from src.core.pack.jobs.ssh import far_script, readings as readings_mod, view as ssh_view
from src.core.pack.jobs.ssh.readings import NO_ANSWER, Link, Readings, SshReading
from src.core.pack.jobs.store import JobStore
from src.core.pack.jobs.types import CAP_JOBS
from src.core.pack.machines import can_block
from src.core.pack.placement import needs as needs_mod, rule
from src.core.pack.placement.workload import Workload
from tests.helpers import fake_far
from tests.helpers.ssh_job_world import snap

KEY = "target-key-for-the-placement-tests"
FP = "SHA256:" + "A" * 43
RENDER = Workload("render", 2.0, 4.0, 1.0)
POLICY = Policy("proj-uid", auto_delegate=True)


class Clock:

    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def probe_lines(*, kernel: str = "5.15.133.1-microsoft-standard-WSL2", tools: str = "git node npm python3", gpu: Optional[str] = "NVIDIA GeForce RTX 4090, 24564") -> List[str]:
    lines = [f"uname Linux {kernel} x86_64", "cores 24", "memtotal_kb 33554432", "disk_free_kb 524288000"]
    lines += [f"gpu {gpu}"] if gpu else []
    return lines + [f"tool {t} /usr/bin/{t}" for t in tools.split()]


def pressure_lines(*, util: int = 5, free_mib: int = 22000, load: str = "0.50 0.4 0.3 1/200 99", gpu: bool = True) -> List[str]:
    lines = ["cores 24", f"loadavg {load}", "stat cpu  100 0 100 9800 0 0 0 0", "psi_mem some avg10=0.00 avg60=0.00 avg300=0.00 total=0",
             "psi_mem full avg10=0.00 avg60=0.00 avg300=0.00 total=0", "memavail_kb 30000000", "disk_free_kb 524288000"]
    return lines + ([f"gpu {util}, {free_mib}"] if gpu else [])


class StubConn:

    def __init__(self, probe: List[str], pressure: List[str], silent: bool = False) -> None:
        self.answers, self.silent, self.calls = {"probe": probe, "pressure": pressure}, silent, []

    async def call(self, script: bytes, timeout: float) -> Any:
        text = script.decode()
        verb, nonce = re.search(r"CVJ_VERB='(\w+)'", text).group(1), re.search(r"CVJ_NONCE='([0-9a-f]+)'", text).group(1)
        self.calls.append(verb)
        if self.silent:
            return SimpleNamespace(failure="timed_out", stdout=b"")
        body = "".join(f"CVJ{nonce} {line}\n" for line in self.answers[verb]) + f"CVJ{nonce} end 0\n"
        return SimpleNamespace(failure=None, stdout=body.encode())


def make_store(tmp: Path, *, takes_work: bool = True, key: str = KEY, labels: Optional[str] = None) -> JobStore:
    store = JobStore(tmp / "state")
    store.ssh_target_put(key, takes_work=1 if takes_work else 0, pinned_fp=FP, labels_json=labels)
    return store


def readings_of(store: JobStore, conns: Dict[str, StubConn], clock: Optional[Clock] = None) -> Readings:
    return Readings(store, lambda hk: Link(f"box-{hk[:4]}", conns[hk]), clock or Clock())


def get_readings(rd: Readings) -> List[SshReading]:
    return asyncio.run(rd.for_placement())


def paired(install_id: str, can: Dict[str, Any], load1: float = 1.0) -> rule.MachineInput:
    return rule.MachineInput(install_id, install_id, {**snap(load1), "can": can}, True, False, False, True, None)


def me_busy(master: Optional[str] = "iid-a") -> place.PlaceView:
    can = can_block.build({"probed_at": 1.0, "os": "macos", "tools": {}, "gpus": []}, [], None)
    mine = rule.MachineInput("iid-a", "a", {**snap(9.5), "can": can, "restrictions": {"may_host_agents": False}}, True, True, True, True, 0)
    return place.PlaceView(mine, [], {}, master, None)


def no_gpu_can(os_name: str = "macos") -> Dict[str, Any]:
    return can_block.build({"probed_at": 1.0, "os": os_name, "tools": {}, "gpus": []}, [], None)


def with_ssh(view: place.PlaceView, rd: Readings, now: Optional[float] = None) -> place.PlaceView:
    return ssh_view.extend(view, get_readings(rd), now if now is not None else rd._clock())


def needs(*words: str) -> List[needs_mod.Need]:
    return needs_mod.parse_all(list(words))


def test_card_job_goes_to_the_ssh_computer_not_a_paired_one_without_a_card(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    rd = readings_of(store, {KEY: StubConn(probe_lines(), pressure_lines())})
    view = with_ssh(me_busy(), rd)
    view = dataclasses.replace(view, peers=[paired("iid-b", no_gpu_can()), *view.peers], caps={**view.caps, "iid-b": [CAP_JOBS]})
    answer = place.place(RENDER, "proj-uid", POLICY, view, needs=needs("gpu:nvidia"))
    assert (answer.decision, answer.peer_install_id) == ("remote", "ssh:" + KEY)
    assert answer.install in (None, [], ())
    ssh_machine = next(p for p in view.peers if p.install_id == "ssh:" + KEY)
    assert ssh_machine.snapshot["can"]["gpus"][0]["vram_gb"] == 24.0 and ssh_machine.snapshot["can"]["os"] == "linux"
    assert view.caps["ssh:" + KEY] == [CAP_JOBS]


def test_one_host_faulting_with_a_plain_error_leaves_the_other_read(tmp_path: Path) -> None:
    other = "second-target-key-for-the-fault-test"
    store = make_store(tmp_path)
    store.ssh_target_put(other, takes_work=1, pinned_fp=FP)

    def conns(hk: str) -> Link:
        if hk == other:
            raise RuntimeError("a fault that is not a JobError")
        return Link("box-a", StubConn(probe_lines(), pressure_lines()))

    got = get_readings(Readings(store, conns, Clock()))
    assert [r.host_key for r in got] == [KEY] and got[0].pressure is not None


def test_busy_card_pegs_the_target_with_gpu_busy(tmp_path: Path) -> None:
    for util, free in ((80, 22000), (5, 1000)):
        rd = readings_of(make_store(tmp_path / str(util)), {KEY: StubConn(probe_lines(), pressure_lines(util=util, free_mib=free))})
        reading = get_readings(rd)[0]
        assert reading.pressure["pegged"] is True and reading.pressure["why"] == "gpu busy"
        answer = place.place(RENDER, "proj-uid", POLICY, with_ssh(me_busy(), rd), needs=needs("gpu:nvidia"))
        assert answer.decision == "refused" and answer.code == "requirement_busy" and "gpu busy" in answer.reason
    quiet = get_readings(readings_of(make_store(tmp_path / "q"), {KEY: StubConn(probe_lines(), pressure_lines())}))[0]
    assert quiet.pressure["pegged"] is False


def test_drop_reasons(tmp_path: Path) -> None:
    rd = readings_of(make_store(tmp_path), {KEY: StubConn(probe_lines(), pressure_lines())})
    view = with_ssh(me_busy(), rd)
    machine = view.peers[0]
    assert place.drop_reason(machine, POLICY, view) is None
    by_id = place.drop_reason(machine, Policy("proj-uid", never_use=["ssh:" + KEY]), view)
    by_label = place.drop_reason(machine, Policy("proj-uid", never_use=[machine.label]), view)
    assert by_id == by_label == "is on the never use list"
    off = readings_of(make_store(tmp_path / "off", takes_work=False), {KEY: StubConn(probe_lines(), pressure_lines())})
    off_view = with_ssh(me_busy(), off)
    assert "may_host_agents" in str(place.drop_reason(off_view.peers[0], POLICY, off_view))
    assert off_view.peers[0].usable is False and off.cached()[0].load is None
    clock = Clock()
    stale_rd = readings_of(make_store(tmp_path / "stale"), {KEY: StubConn(probe_lines(), pressure_lines())}, clock)
    stale_view = with_ssh(me_busy(), stale_rd, now=clock.now + 31)
    assert stale_view.peers[0].usable is False
    answer = place.place(RENDER, "proj-uid", POLICY, stale_view)
    assert answer.decision == "here" and "figures are older than 30 s" in answer.reason
    fresh_view = with_ssh(me_busy(), stale_rd, now=clock.now + 5)
    assert place.place(RENDER, "proj-uid", POLICY, fresh_view).decision == "remote"


def test_a_member_view_keeps_its_ssh_computer_despite_the_master_rule(tmp_path: Path) -> None:
    rd = readings_of(make_store(tmp_path), {KEY: StubConn(probe_lines(), pressure_lines())})
    view = with_ssh(me_busy(master="iid-m"), rd)
    other = paired("iid-b", no_gpu_can())
    assert place.drop_reason(other, POLICY, dataclasses.replace(view, caps={"iid-b": [CAP_JOBS]})) == "is not the master and this computer is not either"
    assert place.drop_reason(view.peers[0], POLICY, view) is None
    assert place.place(RENDER, "proj-uid", POLICY, view).peer_install_id == "ssh:" + KEY


def test_a_silent_target_reads_unusable_with_no_figures(tmp_path: Path) -> None:
    other = "f" * 32
    store = make_store(tmp_path)
    store.ssh_target_put(other, takes_work=1, pinned_fp=FP)
    rd = readings_of(store, {KEY: StubConn([], [], silent=True), other: StubConn(probe_lines(), pressure_lines())})
    got = {r.host_key: r for r in get_readings(rd)}
    silent = got[KEY]
    assert (silent.usable, silent.reason, silent.load, silent.pressure) == (False, NO_ANSWER, None, None)
    assert silent.to_dict(rd._clock())["load"] is None and store.ssh_target_get(KEY)["last_error"] == NO_ANSWER
    assert got[other].usable is True
    machine = ssh_view.machine_of(silent, rd._clock())
    assert machine.usable is False and machine.snapshot is None


def test_a_missing_tool_is_never_sent_there_and_never_installed(tmp_path: Path) -> None:
    rd = readings_of(make_store(tmp_path), {KEY: StubConn(probe_lines(tools="git node"), pressure_lines())})
    view = with_ssh(me_busy(), rd)
    answer = place.place(RENDER, "proj-uid", POLICY, view, needs=needs("ffmpeg"))
    assert answer.decision == "refused" and answer.code == "requirement_unmet" and "lacks ffmpeg" in answer.reason
    assert not answer.install
    can = view.peers[0].snapshot["can"]
    assert can["brew"] is False and can["tools"]["ffmpeg"] is False
    assert place.install_candidates(RENDER, "proj-uid", POLICY, view, needs=needs("ffmpeg")) is None
    ok = place.place(RENDER, "proj-uid", POLICY, view, needs=needs("node"))
    assert ok.peer_install_id == "ssh:" + KEY


def test_os_and_label_needs_on_a_wsl_computer(tmp_path: Path) -> None:
    rd = readings_of(make_store(tmp_path), {KEY: StubConn(probe_lines(), pressure_lines())})
    view = with_ssh(me_busy(), rd)
    assert view.peers[0].snapshot["can"]["labels"] == ["wsl"] and view.peers[0].snapshot["can"]["os"] == "linux"
    assert place.place(RENDER, "proj-uid", POLICY, view, needs=needs("os:windows")).decision == "refused"
    for word in ("os:linux", "label:wsl"):
        assert place.place(RENDER, "proj-uid", POLICY, view, needs=needs(word)).peer_install_id == "ssh:" + KEY
    plain = readings_of(make_store(tmp_path / "p"), {KEY: StubConn(probe_lines(kernel="6.1.0-18-amd64"), pressure_lines())})
    assert with_ssh(me_busy(), plain).peers[0].snapshot["can"]["labels"] == []


def test_a_placed_job_holds_room_and_the_owner_labels_ride(tmp_path: Path) -> None:
    store = make_store(tmp_path, labels='["rtx 4090"]')
    rd = readings_of(store, {KEY: StubConn(probe_lines(), pressure_lines())})
    view = with_ssh(me_busy(), rd)
    view = dataclasses.replace(view, ssh_hold=lambda i, c, r: rd.hold(i[4:], "j1", c, r, 120.0))
    assert place.place(RENDER, "proj-uid", POLICY, view).peer_install_id == "ssh:" + KEY
    assert rd.cached()[0].pressure["held"] == {"cpu": 2.0, "ram_gb": 4.0, "n": 1}
    assert rd.cached()[0].can["labels"] == ["rtx 4090", "wsl"]


def test_the_real_driver_lines_parse_and_a_tool_under_a_version_manager_is_found(tmp_path: Path) -> None:
    def conn_for(home: Path) -> Any:
        shims = home.parent / (home.name + "-shims")
        shims.mkdir(parents=True, exist_ok=True)
        smi = shims / "nvidia-smi"
        smi.write_text('#!/bin/sh\ncase "$*" in *utilization*) echo "7, 20000";; *) echo "NVIDIA GeForce RTX 4090, 24564";; esac\n')
        smi.chmod(0o755)

        class Real:
            async def call(self, script: bytes, timeout: float) -> Any:
                code, out, _err = await asyncio.to_thread(fake_far.run, script, home)
                return SimpleNamespace(failure=None if code == 0 else "failed", stdout=out)
        return Real()

    plain, managed = tmp_path / "plain", tmp_path / "managed"
    node = managed / ".nvm" / "versions" / "node" / "v20.1.0" / "bin"
    node.mkdir(parents=True)
    for tool in ("node", "codex"):
        (node / tool).write_text("#!/bin/sh\n")
        (node / tool).chmod(0o755)
    results = {}
    for name, home in (("plain", plain), ("managed", managed)):
        store = make_store(tmp_path / name)
        rd = readings_of(store, {KEY: conn_for(home)})
        results[name] = get_readings(rd)[0]
        fake_far.kill_leftovers(home)
    assert results["managed"].can["tools"]["node"] is True and results["managed"].can["tools"]["codex"] is True
    assert results["plain"].can["tools"]["codex"] is False
    assert results["managed"].can["gpus"][0]["model"] == "NVIDIA GeForce RTX 4090" and results["managed"].can["gpus"][0]["vram_gb"] == 24.0
    assert results["managed"].usable and results["managed"].pressure["pegged"] is False and results["managed"].load["cores"]


def test_far_strings_are_data() -> None:
    answer = far_script.FarAnswer(0, {"uname": "Linux ../../etc/x $(id)", "cores": "99999999", "memtotal_kb": "abc"},
                                  ["tool git /usr/bin/git", "tool ../../evil /x", "gpu $(touch z), 99999999999999999999"])
    probe = readings_mod.parse_probe(answer, 1.0)
    assert probe["os_version"] is None and probe["arch"] is None and probe["cores"] is None and probe["mem_gb"] is None
    assert probe["tools"]["git"] is True and "../../evil" not in probe["tools"]
    block = can_block.build(probe, [], None)
    assert can_block.parse(block) is not None



def test_a_computer_with_no_can_block_is_probed_at_most_once_a_minute(tmp_path: Path) -> None:
    store, clock = make_store(tmp_path), Clock()
    conn = StubConn(probe_lines(), pressure_lines(), silent=True)
    rd = readings_of(store, {KEY: conn}, clock)
    for _ in range(4):
        got = get_readings(rd)
        clock.now += 16.0
        assert got[0].usable is False and got[0].reason == NO_ANSWER
    assert conn.calls == ["probe"], conn.calls
    clock.now += 60.0
    get_readings(rd)
    assert conn.calls == ["probe", "probe"]


def test_a_busy_figure_is_not_an_average_over_an_idle_hour(tmp_path: Path) -> None:
    store, clock = make_store(tmp_path), Clock()
    rd = readings_of(store, {KEY: StubConn(probe_lines(), pressure_lines())}, clock)
    get_readings(rd)
    clock.now += 3600.0
    again = get_readings(rd)[0]
    assert again.usable and again.load["busy_cores"] is None


def test_a_login_shell_that_is_not_posix_reads_unreachable_for_that_computer_only(tmp_path: Path) -> None:
    from src.core.hosts.ssh_pool import ShellNotVerified
    from src.core.pack.jobs.ssh.conn import SshConn
    from src.core.pack.jobs.types import JobError

    class Pool:

        is_up = True

        async def run(self, *_a: Any, **_k: Any) -> Any:
            raise ShellNotVerified("fish")

    conn = SshConn.__new__(SshConn)
    conn._pool, conn._calls, conn.host_key = Pool(), asyncio.Semaphore(1), KEY
    conn._ensure = lambda: asyncio.sleep(0)  # type: ignore[method-assign]
    with pytest.raises(JobError) as bad:
        asyncio.run(conn.call(b"true\n", 5.0))
    assert bad.value.code == "shell_not_posix"


def test_extend_live_never_raises_when_the_readings_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.pack.jobs import boot
    from src.core.pack.jobs.types import JobError

    store = make_store(tmp_path)

    class Failing(Readings):

        def placement_blocking(self, timeout: float = 3.0) -> List[SshReading]:
            raise JobError("unreachable", NO_ANSWER, 502)

    monkeypatch.setattr(boot, "engine", lambda: SimpleNamespace(store=store))
    monkeypatch.setattr(ssh_view, "shared", lambda _store: Failing(store))
    view = me_busy()
    assert ssh_view.extend_live(view) is view


def test_the_boot_binds_the_loop_so_a_worker_thread_can_read(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    rd = readings_of(store, {KEY: StubConn(probe_lines(), pressure_lines())})

    async def main() -> List[SshReading]:
        rd.bind()
        return await asyncio.to_thread(rd.placement_blocking)

    got = asyncio.run(main())
    assert len(got) == 1 and got[0].usable
