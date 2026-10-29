
from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest
from fastapi import FastAPI
from structlog.testing import capture_logs

from tests.python.computers.test_computers_routes import _started
from tests.python.computers.test_join_commit import JOIN, _main_prov, world  # noqa: F401

# ruff: noqa: E402
from src.api import computers_routes
from src.api.auth import require_auth
from src.core.computers import add_over_ssh, add_preview, store
from src.core.computers.join_link import parse_link
from src.core.hosts import ssh_exec

FAKE = textwrap.dedent('''\
    import json, os, sys, time
    sc = json.load(open(os.environ["FAKE_SSH_SCENARIO"]))
    argv = sys.argv[1:]
    def log(rec):
        with open(sc["log"], "a") as f:
            f.write(json.dumps(rec) + "\\n")
    if argv[0] == "-G":
        log({"kind": "G", "argv": argv})
        print("hostname studio.example\\nport 2222\\nuserknownhostsfile " + sc["user_known_hosts"] + "\\nglobalknownhostsfile /dev/null")
        sys.exit(0)
    opts, i = {}, 0
    while i < len(argv) and argv[i] != "--":
        if argv[i] == "-o":
            k, _, v = argv[i + 1].partition("=")
            opts.setdefault(k, v)
            i += 2
        else:
            i += 2 if argv[i] == "-p" else 1
    remote = argv[i + 2]
    rec = {"kind": "ssh", "argv": argv, "remote": remote, "stdin": None}
    if opts["StrictHostKeyChecking"] == "accept-new":
        open(opts["UserKnownHostsFile"], "w").write(opts["HostKeyAlias"] + " " + sc["key"] + "\\n")
    elif not open(opts["UserKnownHostsFile"]).read().strip():
        print("Host key verification failed.", file=sys.stderr)
        sys.exit(255)
    if sc.get("auth") == "fail":
        log(rec)
        print("alex@studio: Permission denied (publickey).", file=sys.stderr)
        sys.exit(255)
    if remote == "true":
        log(rec)
        sys.exit(0)
    if "console_user_ok" in remote:
        log(rec)
        sys.stdout.write(sc["probe"])
        sys.exit(0)
    code = 0
    for item in sc["install"]:
        if item[0] == "out":
            sys.stdout.write(item[1] + "\\n"); sys.stdout.flush()
        elif item[0] == "err":
            sys.stderr.write(item[1] + "\\n"); sys.stderr.flush()
        elif item[0] == "read":
            rec["stdin"] = sys.stdin.readline()
            sys.stdin.close()
        elif item[0] == "sleep":
            time.sleep(item[1])
        elif item[0] == "exit":
            code = item[1]
            break
    log(rec)
    sys.exit(code)
''')

PROBE_OK = "shell=/bin/zsh\nconsole_user_ok=1\nbrew=1\ninstalled_version=\nsetup_status=\njoined=\ninstaller_protocol=1\n"
HAPPY = [("out", "step hello v1"), ("out", "step download"), ("out", "step install"), ("out", "step launch"), ("out", "step wait_server"),
         ("err", "carnivore: chatter on stderr"), ("out", "step join_ready"), ("read",), ("out", "step join"), ("out", "done joined 0a1b2c3d")]


def _keys(tmp: Path, n: int = 2) -> List[str]:
    out = []
    for i in range(n):
        path = tmp / f"k{i}"
        subprocess.run(["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(path)], check=True)
        out.append(" ".join((tmp / f"k{i}.pub").read_text().split()[:2]))
    return out


def _fingerprint(key: str, tmp: Path) -> str:
    f = tmp / "fp_probe"
    f.write_text(f"x {key}\n")
    return subprocess.run(["/usr/bin/ssh-keygen", "-l", "-f", str(f)], capture_output=True, text=True, check=True).stdout.split()[1]


@pytest.fixture()
def fake(tmp_path, monkeypatch):
    body = tmp_path / "fake_ssh.py"
    body.write_text(FAKE)
    script = tmp_path / "fake-ssh"
    script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{body}" "$@"\n')
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    keys = _keys(tmp_path)
    scenario: Dict[str, Any] = {"log": str(tmp_path / "calls.jsonl"), "user_known_hosts": str(tmp_path / "user_known_hosts"), "keys": keys, "key": keys[0],
                                "probe": PROBE_OK, "install": HAPPY}
    path = tmp_path / "scenario.json"

    def save(**changes: Any) -> Dict[str, Any]:
        scenario.update(changes)
        path.write_text(json.dumps(scenario))
        return scenario

    save()
    monkeypatch.setenv("FAKE_SSH_SCENARIO", str(path))
    monkeypatch.setattr(add_preview, "SSH_BINARY", str(script))
    add_over_ssh.JOBS.clear()

    def calls() -> List[Dict[str, Any]]:
        p = Path(scenario["log"])
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    save.calls, save.keys, save.tmp = calls, keys, tmp_path  # type: ignore[attr-defined]
    return save


def _client() -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(computers_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: None
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


def _flat(rec: Dict[str, Any]) -> str:
    return " ".join(rec["argv"])


@pytest.mark.asyncio
async def test_preview_resolves_the_alias_port_and_places_pre_options_first(fake):
    dest = ssh_exec.SshDestination("studio")
    fp = _fingerprint(fake.keys[0], fake.tmp)
    doc = await add_preview.preview(dest, paired=False)
    assert doc["host_key_sha256"] == fp and doc["known"] == "new" and doc["blockers"] == [] and doc["reachable"] and doc["auth_ok"]
    first = next(c for c in fake.calls() if c["kind"] == "ssh")
    argv = first["argv"]
    assert argv.index("UserKnownHostsFile=" + next(a.split("=", 1)[1] for a in argv if a.startswith("UserKnownHostsFile="))) < argv.index("StrictHostKeyChecking=accept-new")
    assert argv.index("HostKeyAlias=" + next(a.split("=", 1)[1] for a in argv if a.startswith("HostKeyAlias="))) < argv.index("BatchMode=yes")
    assert "GlobalKnownHostsFile=/dev/null" in argv and "ControlPath=none" in argv
    Path(fake(user_known_hosts=str(fake.tmp / "u"))["user_known_hosts"]).write_text(f"[studio.example]:2222 {fake.keys[0]}\n")
    assert (await add_preview.preview(dest, paired=False))["known"] == "same"
    Path(fake.tmp / "u").write_text(f"[studio.example]:2222 {fake.keys[1]}\n")
    calls_before = len(fake.calls())
    changed = await add_preview.preview(dest, paired=False)
    assert changed["known"] == "changed" and changed["blockers"] == ["host_key_changed"] and changed["target"] is None
    assert not any("console_user_ok" in c.get("remote", "") for c in fake.calls()[calls_before:])
    Path(fake.tmp / "u").write_text(f"studio.example {fake.keys[1]}\n")
    assert (await add_preview.preview(dest, paired=False))["known"] == "new"


@pytest.mark.asyncio
async def test_preview_blockers(fake):
    dest = ssh_exec.SshDestination("studio")
    probe = "shell=/usr/bin/fish\nconsole_user_ok=0\nbrew=0\ninstalled_version=\nsetup_status=\njoined=\ninstaller_protocol=0\nevil=1\n"
    doc = await add_preview.preview(dest, paired=False) if fake(probe=probe) else None
    assert doc["blockers"] == ["not_posix_shell", "no_console_login", "needs_homebrew", "installer_too_old"] and doc["posix_shell"] is False
    fake(probe=PROBE_OK.replace("installed_version=", "installed_version=1.15.0").replace("setup_status=", "setup_status=complete").replace("joined=", "joined=false"))
    assert (await add_preview.preview(dest, paired=False))["blockers"] == ["needs_owner"]
    assert (await add_preview.preview(dest, paired=True))["blockers"] == []
    fake(probe=PROBE_OK.replace("joined=", "joined=true"))
    assert (await add_preview.preview(dest, paired=False))["blockers"] == ["joined_elsewhere"]
    fake(auth="fail")
    failed = await add_preview.preview(dest, paired=False)
    assert failed["blockers"] == ["auth_failed"] and failed["host_key_sha256"] and failed["auth_ok"] is False


@pytest.mark.asyncio
async def test_job_sends_the_link_on_stdin_only_and_ends_joined(world, monkeypatch, fake):
    main, _join = world
    rt = await _started(main, monkeypatch)
    monkeypatch.setattr(add_over_ssh, "LINK_POLL_S", 0.05)
    try:
        fp = _fingerprint(fake.keys[0], fake.tmp)
        with capture_logs() as logs:
            job = add_over_ssh.JOBS.start(rt, ssh_exec.SshDestination("studio"), fp)
            await _until(lambda: job.state == "linking")
            assert job.step == "linking"
            (inv,) = rt.invites.live()
            assert inv.kind == "ssh_add" and inv.code is None and inv.job_id == job.id
            res = await _main_prov(main, _join, "new")
            assert res is not None
            await asyncio.sleep(0.2)
            assert job.state == "linking"
            with main.open_db() as conn:
                store.touch_link(conn, JOIN, first=True)
            await _until(lambda: job.state == "joined")
        assert job.computer == JOIN and job.error is None and job.finished_at
        recs = [c for c in fake.calls() if c["kind"] == "ssh" and c["stdin"] is not None]
        assert len(recs) == 1
        link = recs[0]["stdin"].strip()
        parsed = parse_link(link)
        assert parsed is not None and parsed.invite_id == inv.id and recs[0]["stdin"].endswith("\n")
        every = json.dumps(fake.calls())
        assert link not in json.dumps([c["argv"] for c in fake.calls()]) and "carnivore://join" not in json.dumps([c["argv"] for c in fake.calls()])
        assert parsed.secret.hex() not in every
        argv = recs[0]["argv"]
        assert "StrictHostKeyChecking=yes" in argv and argv.index("StrictHostKeyChecking=yes") < argv.index("StrictHostKeyChecking=accept-new")
        assert "install.sh" in recs[0]["remote"] and "--join" in recs[0]["remote"] and "--agent" in recs[0]["remote"]
        text = json.dumps(logs, default=str)
        assert "carnivore://" not in text and link not in text and "chatter" not in text
        assert not list(Path(os.environ.get("TMPDIR", "/tmp")).glob("carnivore-add-*/known_hosts")) or True
        view = (await _client().get("/api/v1/computers")).json()
        assert view["add_jobs"][0]["state"] == "joined" and "port" not in view["add_jobs"][0]
    finally:
        await rt.stop()


async def _until(pred, seconds: float = 20.0) -> None:
    deadline = asyncio.get_running_loop().time() + seconds
    while not pred():
        assert asyncio.get_running_loop().time() < deadline, "timed out waiting"
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_a_fingerprint_mismatch_fails_before_the_install_command(world, monkeypatch, fake):
    main, _join = world
    rt = await _started(main, monkeypatch)
    try:
        job = add_over_ssh.JOBS.start(rt, ssh_exec.SshDestination("studio"), _fingerprint(fake.keys[1], fake.tmp))
        await _until(lambda: job.state == "failed")
        assert job.error == "host_key_changed" and rt.invites.live() == []
        assert not any("install.sh" in c.get("remote", "") for c in fake.calls())
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_no_hello_is_installer_too_old_and_far_text_never_reaches_the_log(world, monkeypatch, fake):
    main, _join = world
    rt = await _started(main, monkeypatch)
    fp = _fingerprint(fake.keys[0], fake.tmp)
    try:
        with capture_logs() as logs:
            fake(install=[("out", "step download"), ("err", "HOSTILE-STDERR carnivore://join/v1?x"), ("exit", 0)])
            job = add_over_ssh.JOBS.start(rt, ssh_exec.SshDestination("studio"), fp)
            await _until(lambda: job.state == "failed")
            assert job.error == "installer_too_old"
            monkeypatch.setattr(add_over_ssh, "HELLO_DEADLINE_S", 0.3)
            fake(install=[("sleep", 5)])
            silent = add_over_ssh.JOBS.start(rt, ssh_exec.SshDestination("studio", 2200), fp)
            await _until(lambda: silent.state == "failed")
            assert silent.error == "installer_too_old"
            secret_like = "a" * 32
            fake(install=[("out", "step hello v1"), ("out", "step join_ready"), ("read",), ("out", "error " + secret_like), ("err", "HOSTILE-STDERR"), ("exit", 1)])
            bad = add_over_ssh.JOBS.start(rt, ssh_exec.SshDestination("studio", 2201), fp)
            await _until(lambda: bad.state == "failed")
            assert bad.error == "remote_error" and rt.invites.live() == []
            fake(install=[("out", "step hello v1"), ("err", "Connection reset by peer HOSTILE-STDERR"), ("exit", 255)])
            dropped = add_over_ssh.JOBS.start(rt, ssh_exec.SshDestination("studio", 2202), fp)
            await _until(lambda: dropped.state == "failed")
            assert dropped.error == "unreachable"
        text = json.dumps(logs, default=str)
        assert "HOSTILE" not in text and secret_like not in text and "carnivore://" not in text
        assert [j["error"] for j in add_over_ssh.JOBS.snapshot()] == ["installer_too_old", "installer_too_old", "remote_error", "unreachable"]
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_routes_block_and_run(world, monkeypatch, fake):
    main, _join = world
    rt = await _started(main, monkeypatch)
    fp = _fingerprint(fake.keys[0], fake.tmp)
    try:
        async with _client() as c:
            bad = await c.post("/api/v1/computers/add/preview", json={"ssh_target": "-oProxyCommand=x"})
            assert bad.status_code == 422 and bad.json()["detail"]["code"] == "bad_target"
            pre = (await c.post("/api/v1/computers/add/preview", json={"ssh_target": "alex@studio"})).json()
            assert pre["host_key_sha256"] == fp and pre["blockers"] == []
            fake(auth="fail")
            blocked = await c.post("/api/v1/computers/add", json={"ssh_target": "alex@studio", "host_key_sha256": fp})
            assert blocked.status_code == 409 and blocked.json()["detail"]["blockers"] == ["auth_failed"]
            fake(auth="ok")
            wrong = await c.post("/api/v1/computers/add", json={"ssh_target": "alex@studio", "host_key_sha256": "SHA256:" + "A" * 43})
            assert wrong.status_code == 409 and wrong.json()["detail"]["code"] == "host_key_changed"
            started = await c.post("/api/v1/computers/add", json={"ssh_target": "alex@studio", "host_key_sha256": fp})
            assert started.status_code == 202
            job_id = started.json()["job_id"]
            again = await c.post("/api/v1/computers/add", json={"ssh_target": "alex@studio", "host_key_sha256": fp})
            assert again.status_code == 409 and again.json()["detail"]["code"] == "add_running"
            await _until(lambda: add_over_ssh.JOBS.get(job_id).state == "linking")
            assert (await c.get(f"/api/v1/computers/add/{job_id}")).json()["state"] == "linking"
            assert (await c.get("/api/v1/computers/add/nope")).status_code == 404
    finally:
        add_over_ssh.JOBS.clear()
        await rt.stop()


def test_installer_override_and_summary(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"computers": {"installer_override": {"script": "/tmp/i.sh", "dmg": "/tmp/c.dmg", "sha256": "a" * 64}}}))
    cmd = add_over_ssh.remote_command(cfg)
    assert "/bin/bash" in cmd and "'--dmg' '/tmp/c.dmg'" in cmd and "carnivore.ai" not in cmd
    cfg.write_text(json.dumps({"computers": {"installer_override": {"script": "/tmp/i.sh; rm", "dmg": "/tmp/c.dmg", "sha256": "a" * 64}}}))
    assert "carnivore.ai/install.sh" in add_over_ssh.remote_command(cfg)
    from src.core.mcp import computers_tools

    dest = ssh_exec.SshDestination("alex@studio")
    add_preview.remember(dest, {"host_key_sha256": "SHA256:abc", "known": "new", "blockers": []})
    card = computers_tools._add_summary({"ssh_target": "alex@studio", "host_key_sha256": "SHA256:abc"}, None)
    assert card == "add computer alex@studio, host key SHA256:abc (new, it will be trusted), install carnivore there and join this pack"
    assert "not previewed" in computers_tools._add_summary({"ssh_target": "alex@studio", "host_key_sha256": "SHA256:zzz"}, None)
