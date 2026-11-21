
from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import stat
import struct
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator, List

import pytest

from src.core.hosts import ssh_exec
from src.core.hosts.ssh_exec import HARDENING_OPTIONS, SshDestination, argv_command, direct_argv, master_argv, mux_argv
from src.core.hosts.ssh_master import control_path_for, instance_tag_for
from src.core.pack.jobs.ssh import conn as conn_mod
from src.core.pack.jobs.ssh.conn import (
    DOWNLOAD_FAR_SCRIPT, UPLOAD_FAR_SCRIPT, SshConn, host_alias, jobs_pre_options, known_hosts_path, pin_key)
from src.core.pack.jobs.types import JobError
from tests.helpers.fake_ssh import FakeSshHost, fake_ssh_host_fixture

FAKE_HOST_ID = "fakehost000001"


def make_key(seed: bytes = b"k") -> "tuple[str, str]":
    blob = struct.pack(">I", 11) + b"ssh-ed25519" + struct.pack(">I", 32) + hashlib.sha256(seed).digest()
    fp = "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    return "ssh-ed25519 " + base64.b64encode(blob).decode(), fp


@pytest.fixture
def fake() -> Iterator[FakeSshHost]:
    yield from fake_ssh_host_fixture()


def make_conn(fake: FakeSshHost, state: Path, pinned: "str | None", **options) -> SshConn:
    host = SimpleNamespace(key=FAKE_HOST_ID, ssh_target="alex@fakehost", ssh_port=2222, login_shell="/bin/sh")
    settings = dict(connect_timeout=5.0, check_interval=0.5, delay=lambda attempt: 0.05)
    settings.update(options)
    return SshConn(host, state, pinned_fp=pinned, ssh_binary=fake.ssh_binary, control_dir=fake.control_dir, **settings)


def pinned_conn(fake: FakeSshHost, state: Path, seed: bytes = b"k") -> SshConn:
    key, fp = make_key(seed)
    pin_key(FAKE_HOST_ID, fp, key, state)
    return make_conn(fake, state, fp)


def far_file(fake: FakeSshHost, job_id: str, data: bytes) -> str:
    root = fake.root / "far"
    (root / "out").mkdir(parents=True, exist_ok=True)
    (root / "out" / f"{job_id}.bundle").write_bytes(data)
    return str(root)


JOB = "job_12345678"


def test_pre_options_are_exactly_h4(tmp_path: Path) -> None:
    kh = tmp_path / "k"
    assert jobs_pre_options(FAKE_HOST_ID, kh) == [
        ("UserKnownHostsFile", str(kh)), ("GlobalKnownHostsFile", "/dev/null"), ("StrictHostKeyChecking", "yes"),
        ("HostKeyAlias", host_alias(FAKE_HOST_ID)), ("UpdateHostKeys", "no"), ("VerifyHostKeyDNS", "no"),
        ("KnownHostsCommand", "none"), ("CheckHostIP", "no"), ("PermitLocalCommand", "no"), ("RequestTTY", "no")]


def test_default_argv_is_unchanged() -> None:
    dest = SshDestination("alex@tower", 2222)
    hardening = [w for k, v in HARDENING_OPTIONS for w in ("-o", f"{k}={v}")]
    assert master_argv(dest, "/tmp/cm/t-1a2b3c4d-0", ssh_binary="ssh") == [
        "ssh", *hardening, "-o", "ControlMaster=yes", "-o", "ControlPersist=no", "-o", "ControlPath=/tmp/cm/t-1a2b3c4d-0",
        "-p", "2222", "-N", "--", "alex@tower"]
    assert mux_argv(dest, "/tmp/cm/t-1a2b3c4d-0", "exec /bin/sh -s", ssh_binary="ssh") == [
        "ssh", *hardening, "-o", "ControlMaster=no", "-o", "ControlPath=/tmp/cm/t-1a2b3c4d-0", "-o", "ProxyCommand=false",
        "-p", "2222", "--", "alex@tower", "exec /bin/sh -s"]
    assert direct_argv(dest, "true", ssh_binary="ssh")[:3] == ["ssh", "-o", "BatchMode=yes"]


def test_pre_options_go_first_and_are_checked() -> None:
    dest = SshDestination("alex@tower")
    pre = (("StrictHostKeyChecking", "yes"),)
    for argv in (master_argv(dest, "/tmp/cm/t-1a2b3c4d-0", ssh_binary="ssh", pre_options=pre),
                 mux_argv(dest, "/tmp/cm/t-1a2b3c4d-0", "true", ssh_binary="ssh", pre_options=pre)):
        assert argv[:3] == ["ssh", "-o", "StrictHostKeyChecking=yes"]
        assert argv[3:5] == ["-o", "BatchMode=yes"]
    with pytest.raises(ssh_exec.SshArgumentError):
        master_argv(dest, "/tmp/cm/t-1a2b3c4d-0", pre_options=(("A", "b\nc"),))


@pytest.mark.asyncio
async def test_every_argv_holds_hardening_and_pre_options_first(fake: FakeSshHost, tmp_path: Path) -> None:
    conn = pinned_conn(fake, tmp_path)
    src = tmp_path / "up.bin"
    src.write_bytes(b"x" * 10)
    far = far_file(fake, JOB, b"abc")
    try:
        assert (await conn.call(b"echo hi\n", 10)).stdout == b"hi\n"
        await conn.upload(src, str(fake.root / "far"), "ab" * 16)
        await conn.download(far, JOB, 3, hashlib.sha256(b"abc").hexdigest(), tmp_path / "d.bundle")
    finally:
        await conn.close()
    pre = [w for k, v in jobs_pre_options(FAKE_HOST_ID, known_hosts_path(tmp_path)) for w in ("-o", f"{k}={v}")]
    hardening = [w for k, v in HARDENING_OPTIONS for w in ("-o", f"{k}={v}")]
    calls = fake.calls("master") + fake.calls("mux")
    assert len(fake.calls("master")) == 1 and len(fake.calls("mux")) == 3
    for call in calls:
        argv = call["argv"]
        assert argv[:len(pre)] == pre and argv[len(pre):len(pre) + len(hardening)] == hardening
        assert "-p" in argv and argv[argv.index("-p") + 1] == "2222"
    up, down = fake.calls("mux")[1]["argv"][-1], fake.calls("mux")[2]["argv"][-1]
    assert up == argv_command(["/bin/sh", "-c", UPLOAD_FAR_SCRIPT, "sh", str(fake.root / "far"), "ab" * 16])
    assert down == argv_command(["/bin/sh", "-c", DOWNLOAD_FAR_SCRIPT, "sh", far, JOB])
    assert fake.calls("mux")[0]["argv"][-1] == argv_command(["/bin/sh", "-s"])
    assert not fake.calls("direct_fallback")


def test_control_path_differs_from_the_terminal_pool(fake: FakeSshHost, tmp_path: Path) -> None:
    conn = make_conn(fake, tmp_path, None)
    jobs = conn.pool._slots[0].master.control_path  # noqa: SLF001
    terminal = control_path_for(fake.control_dir, FAKE_HOST_ID, instance_tag_for(str(tmp_path)), 0)
    assert jobs != terminal and conn_mod.instance_tag(tmp_path) != instance_tag_for(str(tmp_path))


@pytest.mark.asyncio
async def test_unpinned_or_other_key_fails_closed(fake: FakeSshHost, tmp_path: Path) -> None:
    with pytest.raises(JobError) as none_pinned:
        await make_conn(fake, tmp_path, None).call(b"true\n", 5)
    assert none_pinned.value.code == "host_key_unverified"
    _, other_fp = make_key(b"other")
    key, fp = make_key()
    pin_key(FAKE_HOST_ID, fp, key, tmp_path)
    conn = make_conn(fake, tmp_path, other_fp)
    with pytest.raises(JobError) as changed:
        await conn.call(b"true\n", 5)
    assert changed.value.code == "host_key_changed"
    assert not fake.calls()


@pytest.mark.asyncio
async def test_ssh_refusing_the_key_is_host_key_changed_and_never_repinned(fake: FakeSshHost, tmp_path: Path) -> None:
    conn = pinned_conn(fake, tmp_path)
    before = known_hosts_path(tmp_path).read_text()
    fake.set("scenario", "host_key_changed")
    try:
        with pytest.raises(JobError) as err:
            await conn.call(b"true\n", 5)
        assert err.value.code == "host_key_changed"
    finally:
        await conn.close()
    assert known_hosts_path(tmp_path).read_text() == before


@pytest.mark.asyncio
async def test_call_caps_stderr_and_limits_calls_in_flight(fake: FakeSshHost, tmp_path: Path) -> None:
    conn = pinned_conn(fake, tmp_path)
    try:
        res = await conn.call(b"head -c 20000 /dev/zero | tr '\\0' e >&2; echo done\n", 10)
        assert res.stdout == b"done\n" and 0 < len(res.stderr) <= 4096
        with pytest.raises(JobError):
            await conn.call(b"a\0b", 5)
        live: List[int] = []

        async def slow(*_a, **_k):
            live.append(1)
            await asyncio.sleep(0.05)
            peak.append(len(live))
            live.pop()
            return ssh_exec.ExecResult(0, b"", b"")

        peak: List[int] = []
        conn.pool.run = slow  # type: ignore[method-assign]
        await asyncio.gather(*(conn.call(b"true\n", 5) for _ in range(12)))
        assert max(peak) == 4
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_upload_streams_and_refuses_bad_tokens(fake: FakeSshHost, tmp_path: Path) -> None:
    conn = pinned_conn(fake, tmp_path)
    data = os.urandom(300_000)
    src = tmp_path / "up.bin"
    src.write_bytes(data)
    root = fake.root / "far"
    try:
        await conn.upload(src, str(root), "cd" * 16)
        assert (root / "in" / ("cd" * 16 + ".part")).read_bytes() == data
        for bad_root in ("rel/path", "/a/../b", "/a b", "/a$(x)", "/", "/a;b"):
            with pytest.raises(JobError):
                await conn.upload(src, bad_root, "cd" * 16)
        with pytest.raises(JobError):
            await conn.upload(src, str(root), "../x")
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_download_good_short_wrong_and_over_cap(fake: FakeSshHost, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = pinned_conn(fake, tmp_path)
    data = os.urandom(200_000)
    far = far_file(fake, JOB, data)
    sha = hashlib.sha256(data).hexdigest()
    out = tmp_path / "got.bundle"
    try:
        await conn.download(far, JOB, len(data), sha, out)
        assert out.read_bytes() == data and stat.S_IMODE(out.stat().st_mode) == 0o600
        out.unlink()
        cases = [(len(data) + 5, sha, "bundle_size_mismatch"),
                 (len(data) - 5, sha, "bundle_size_mismatch"),
                 (len(data), "0" * 64, "bundle_sha_mismatch")]
        for size, announced, code in cases:
            with pytest.raises(JobError) as err:
                await conn.download(far, JOB, size, announced, out)
            assert err.value.code == code and not out.exists()
        monkeypatch.setattr(conn_mod, "MAX_DOWNLOAD", 1000)
        with pytest.raises(JobError) as big:
            await conn.download(far, JOB, 999, sha, out)
        assert big.value.code == "bundle_too_big" and not out.exists()
        with pytest.raises(JobError) as ann:
            await conn.download(far, JOB, 5000, sha, out)
        assert ann.value.code == "bundle_too_big"
        with pytest.raises(JobError) as gone:
            await conn.download(far, "job_missing1", 3, sha, out)
        assert gone.value.code == "far_transfer_failed" and not out.exists()
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_far_values_never_choose_a_local_path(fake: FakeSshHost, tmp_path: Path) -> None:
    conn = pinned_conn(fake, tmp_path)
    far = far_file(fake, JOB, b"abc")
    try:
        for bad_job in ("../../etc/passwd", "job id", "x" * 100, "short"):
            with pytest.raises(JobError):
                await conn.download(far, bad_job, 3, "0" * 64, tmp_path / "never")
        with pytest.raises(JobError):
            await conn.download(far, JOB, "3", "0" * 64, tmp_path / "never")  # type: ignore[arg-type]
        with pytest.raises(JobError):
            await conn.download(far, JOB, 3, "../../x", tmp_path / "never")
        assert not (tmp_path / "never").exists()
        existing = tmp_path / "mine"
        existing.write_bytes(b"keep")
        with pytest.raises(FileExistsError):
            await conn.download(far, JOB, 3, hashlib.sha256(b"abc").hexdigest(), existing)
        assert existing.read_bytes() == b"keep"
    finally:
        await conn.close()


def test_pin_key_writes_private_atomically_and_refuses(tmp_path: Path) -> None:
    key, fp = make_key()
    path = pin_key(FAKE_HOST_ID, fp, key, tmp_path)
    assert path == known_hosts_path(tmp_path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert path.read_text() == f"{host_alias(FAKE_HOST_ID)} {key}\n"
    assert [p.name for p in path.parent.iterdir()] == [path.name]
    other_key, other_fp = make_key(b"two")
    with pytest.raises(JobError) as taken:
        pin_key(FAKE_HOST_ID, other_fp, other_key, tmp_path)
    assert taken.value.code == "already_pinned" and path.read_text() == f"{host_alias(FAKE_HOST_ID)} {key}\n"
    pin_key("ff" * 16, other_fp, other_key, tmp_path)
    assert len(path.read_text().splitlines()) == 2
    for bad in ("", "SHA256:short", "sha256:" + "A" * 43, fp + "A", "SHA256:" + "!" * 43):
        with pytest.raises(JobError) as err:
            pin_key("ee" * 16, bad, key, tmp_path)
        assert err.value.code == "bad_fingerprint"
    with pytest.raises(JobError) as wrong:
        pin_key("ee" * 16, other_fp, key, tmp_path)
    assert wrong.value.code == "fingerprint_mismatch"
    with pytest.raises(JobError):
        pin_key("ee" * 16, fp, "not a key", tmp_path)


def test_a_state_folder_with_a_space_never_reaches_ssh_as_a_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    spaced = tmp_path / "Application Support" / "Carnivore"
    path = known_hosts_path(spaced)
    assert " " not in str(path) and "%" not in str(path) and path != spaced / "pack" / conn_mod.KNOWN_HOSTS_NAME
    assert jobs_pre_options(FAKE_HOST_ID, path)
    with pytest.raises(JobError):
        jobs_pre_options(FAKE_HOST_ID, spaced / "pack" / "kh")
    with pytest.raises(JobError):
        jobs_pre_options(FAKE_HOST_ID, tmp_path / "a%h" / "kh")


@pytest.mark.asyncio
async def test_an_extra_line_in_the_jobs_file_fails_closed(fake: FakeSshHost, tmp_path: Path) -> None:
    conn = pinned_conn(fake, tmp_path)
    path = known_hosts_path(tmp_path)
    good = path.read_text()
    key, _fp = make_key(b"other")
    try:
        for extra in (f"@cert-authority * {key}\n", f"{host_alias(FAKE_HOST_ID)} {key}\n", f"* {key}\n"):
            path.write_text(good + extra)
            with pytest.raises(JobError) as err:
                await conn.call(b"true\n", 5)
            assert err.value.code == "host_key_changed"
    finally:
        await conn.close()


def test_the_ssh_children_get_a_minimal_environment(fake: FakeSshHost, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARNIVORE_SECRET_TOKEN", "hunter2")
    monkeypatch.setenv("LC_ALL", "x")
    env = conn_mod.minimal_env()
    assert "CARNIVORE_SECRET_TOKEN" not in env and "LC_ALL" not in env and "PATH" in env
    assert make_conn(fake, tmp_path, None).pool._child_env == env


@pytest.mark.asyncio
async def test_a_refused_download_destination_leaves_no_channel(fake: FakeSshHost, tmp_path: Path) -> None:
    conn = pinned_conn(fake, tmp_path)
    far = far_file(fake, JOB, b"abc")
    dest = tmp_path / "exists"
    dest.write_bytes(b"keep")
    try:
        with pytest.raises(FileExistsError):
            await conn.download(far, JOB, 3, hashlib.sha256(b"abc").hexdigest(), dest)
        assert not conn.pool._channels and dest.read_bytes() == b"keep"
        assert conn_mod._deadline(0) >= 60 and conn_mod._deadline(1 << 30) > conn_mod._deadline(0)
    finally:
        await conn.close()


def test_two_hosts_with_the_same_first_twelve_characters_have_their_own_alias() -> None:
    assert host_alias("workstation-a") != host_alias("workstation-b")
