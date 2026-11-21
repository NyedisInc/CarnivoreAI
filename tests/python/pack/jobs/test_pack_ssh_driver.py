
from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, Iterator, Optional

import pytest

from src.core.pack.jobs.ssh import far_script
from src.core.pack.jobs.types import JobError
from tests.helpers import fake_far

UID = "uid12345678"
NAME = "proj"
JOB = "job_aaaa0001"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t.invalid", *args], check=True,
                          capture_output=True, text=True).stdout.strip()


class Far:

    def __init__(self, tmp: Path) -> None:
        self.home = tmp / "home"
        self.root = self.home / ".carnivore-ssh-jobs"
        self.slot = self.root / "folders" / f"{NAME}-{UID[:8]}" / "slot1"
        self.repo = tmp / "caller repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "snap")
        (self.repo / "a.txt").write_text("one\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "base")
        self.commit = _git(self.repo, "rev-parse", "HEAD")
        self.bundle = tmp / "base.bundle"
        _git(self.repo, "bundle", "create", str(self.bundle), "refs/heads/snap")
        self.blob = hashlib.sha256(self.bundle.read_bytes()).hexdigest()[:32]
        self.sent: bytes = b""

    def call(self, verb: str, values: Optional[Dict[str, str]] = None, *, noise: bytes = b"", **kw: str) -> "far_script.FarAnswer":
        nonce = far_script.new_nonce()
        self.sent = far_script.render(verb, values or {}, nonce=nonce, **kw)
        rc, out, _err = fake_far.run(self.sent, self.home, noise=noise)
        answer = far_script.parse(out, nonce)
        assert answer.rc == rc
        return answer

    def upload_and_claim(self, job: str = JOB) -> None:
        assert self.call("claim", {"uid": UID, "name": NAME, "job": job}).fields["slot"] == "1"
        part = self.root / "in" / f"{self.blob}.part"
        part.write_bytes(self.bundle.read_bytes())
        sealed = self.call("seal", {"blob": self.blob, "size": str(part.stat().st_size), "sha256": hashlib.sha256(part.read_bytes()).hexdigest()})
        assert sealed.rc == 0

    def start(self, command: str, *, cap: int = 60, job: str = JOB, env_sh: str = "", memo: Optional[str] = None) -> "far_script.FarAnswer":
        values = {"uid": UID, "name": NAME, "job": job, "slot": "1", "commit": self.commit, "cap": str(cap), "blob": self.blob,
                  "caller": "caller-1", "est": "30"}
        if memo is not None:
            values["memo"] = memo
        return self.call("start", values, command=command, env_sh=env_sh)

    def wait_exit(self, job: str = JOB, seconds: float = 40.0) -> "far_script.FarAnswer":
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            answer = self.call("status", {"job": job})
            if answer.fields.get("state") == "exited":
                return answer
            time.sleep(0.3)
        raise AssertionError("the job did not exit in time")

    def meta(self, job: str = JOB) -> Path:
        return self.root / "meta" / job


@pytest.fixture()
def far(tmp_path: Path) -> Iterator[Far]:
    f = Far(tmp_path)
    yield f
    fake_far.kill_leftovers(f.home)


def _start_values() -> Dict[str, str]:
    return {"uid": UID, "name": NAME, "job": JOB, "slot": "1", "commit": "a" * 40, "cap": "5"}


def test_job_lifecycle_in_the_order_a_job_uses_the_verbs(far: Far) -> None:
    hello = far.call("hello")
    assert hello.rc == 0 and hello.fields["root"] and "git" in hello.fields and hello.all("tool")
    assert far.call("probe").fields["cores"].isdigit()
    assert far.call("pressure").fields["cores"].isdigit()
    far.upload_and_claim()
    started = far.start("printf 'two\\n' > b.txt; echo hello-from-far; exit 3\n", memo="memo one")
    assert started.fields["pid"].isdigit()
    done = far.wait_exit()
    assert done.fields["code"] == "3" and "hello-from-far" in " ".join(done.all("out"))
    got = far.call("collect", {"job": JOB})
    assert got.fields["exit"] == "3" and got.fields["changed"] == "1"
    result = far.root / "out" / f"{JOB}.bundle"
    assert int(got.fields["size"]) == result.stat().st_size
    assert got.fields["sha256"] == hashlib.sha256(result.read_bytes()).hexdigest()
    _git(far.repo, "fetch", "-q", str(result), f"+refs/carnivore/jobs/{JOB}/result:refs/heads/back")
    assert _git(far.repo, "show", "back:b.txt") == "two" and _git(far.repo, "rev-parse", "back") == got.fields["commit"]
    assert far.call("status", {"job": JOB}).fields["state"] == "exited"
    assert "released" in far.call("release", {"job": JOB}).fields
    assert not far.meta().exists() and not result.exists()
    again = far.call("claim", {"uid": UID, "name": NAME, "job": "job_aaaa0002"})
    assert again.fields["slot"] == "1" and again.fields["memo"] == "memo one"


def test_status_of_a_job_that_does_not_exist_is_a_refusal(far: Far) -> None:
    answer = far.call("status", {"job": "job_nothere1"})
    assert answer.rc == 1 and answer.error is not None and answer.error[0] == "no_such_job"


def test_a_nul_a_bad_token_and_a_stray_value_are_refused() -> None:
    with pytest.raises(far_script.FarScriptError):
        far_script.render("status", {"job": JOB + "\n"}, nonce=far_script.new_nonce())
    with pytest.raises(far_script.FarScriptError):
        far_script.render("start", _start_values(), command="echo \0 hi\n", nonce=far_script.new_nonce())
    with pytest.raises(far_script.FarScriptError):
        far_script.render("status", {"job": "x; rm -rf ~"}, nonce=far_script.new_nonce())
    with pytest.raises(far_script.FarScriptError):
        far_script.render("status", {"job": JOB, "extra": "1"}, nonce=far_script.new_nonce())


NASTY = """# quotes ' " ` and $HOME $(echo no) ${X} \\ backslash \\n
# a line that reads like a driver verb:
CVJ_VERB='stop'
cvj_end 0
end 0
EOF
'EOF'
printf '%s' 'done' > nasty.txt
"""


def test_nasty_command_arrives_byte_for_byte(far: Far) -> None:
    far.upload_and_claim()
    far.start(NASTY)
    far.wait_exit()
    assert hashlib.sha256((far.meta() / "command.sh").read_bytes()).hexdigest() == hashlib.sha256(NASTY.encode()).hexdigest()
    got = far.call("collect", {"job": JOB})
    assert got.fields["exit"] == "0" and got.fields["changed"] == "1" and (far.slot / "nasty.txt").read_text() == "done"


def test_profile_noise_is_ignored(far: Far) -> None:
    nonce = far_script.new_nonce()
    rc, out, _e = fake_far.run(far_script.render("hello", {}, nonce=nonce), far.home, noise=b"Welcome!\nCVJ-fake end 0\n")
    assert b"Welcome!" in out
    answer = far_script.parse(out, nonce)
    assert rc == 0 and answer.rc == 0 and all("Welcome" not in line for line in answer.lines)


def test_a_missing_or_wrong_end_line_is_far_garbled() -> None:
    nonce = far_script.new_nonce()
    for raw in (f"CVJ{nonce} root /x\n".encode(), f"CVJ{'0' * 32} end 0\n".encode(), f"CVJ{nonce} end zero\n".encode(),
                b"x" * (far_script.MAX_ANSWER + 1), f"CVJ{nonce} end 0\nCVJ{nonce} root /x\n".encode(), b""):
        with pytest.raises(JobError) as caught:
            far_script.parse(raw, nonce)
        assert caught.value.code == "far_garbled"


def test_parse_caps_and_cleans_every_field() -> None:
    nonce = far_script.new_nonce()
    answer = far_script.parse(f"CVJ{nonce} out {'a' * 400}\nCVJ{nonce} wsl 1\x1b[31m\x00\nCVJ{nonce} end 0\n".encode(), nonce)
    assert len(answer.fields["out"]) == 256 and answer.fields["wsl"] == "1[31m"


def test_far_root_under_a_synced_folder_or_windows_mount_is_bad_far_root(far: Far, tmp_path: Path) -> None:
    for root in (str(tmp_path / "Dropbox" / "jobs"), "/mnt/c/jobs"):
        answer = far.call("hello", {"root": root})
        assert answer.rc == 1 and answer.error is not None and answer.error[0] == "bad_far_root"
    assert not (tmp_path / "Dropbox").exists()
    with pytest.raises(far_script.FarScriptError):
        far_script.render("hello", {"root": "relative/jobs"}, nonce=far_script.new_nonce())


def test_hello_names_each_missing_tool(tmp_path: Path) -> None:
    nonce = far_script.new_nonce()
    rc, out, _e = fake_far.run(far_script.render("hello", {}, nonce=nonce), tmp_path / "bare home", shims=False)
    answer = far_script.parse(out, nonce)
    if rc == 0:
        pytest.skip("this computer has setsid and flock, so nothing is missing")
    assert answer.error is not None and answer.error[0] == "missing_tools"
    assert "setsid" in answer.error[1] and "flock" in answer.error[1]


def test_stop_ends_the_whole_process_group(far: Far) -> None:
    far.upload_and_claim()
    far.start("sleep 300 & echo $! > kid1\nsleep 300 & echo $! > kid2\nwait\n")
    end = time.monotonic() + 20
    while time.monotonic() < end and not ((far.slot / "kid2").exists() and (far.meta() / "cpid").exists()):
        time.sleep(0.2)
    kids = [int((far.slot / n).read_text()) for n in ("kid1", "kid2")]
    assert far.call("status", {"job": JOB}).fields["state"] == "running"
    refused = far.call("release", {"job": JOB})
    assert refused.error is not None and refused.error[0] == "still_running"
    assert "stopped" in far.call("stop", {"job": JOB}).fields
    assert far.call("status", {"job": JOB}).fields["state"] == "exited"
    time.sleep(0.3)
    for pid in kids:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def test_time_cap_answers_124(far: Far) -> None:
    far.upload_and_claim()
    far.start("sleep 60\n", cap=1)
    assert far.wait_exit().fields["code"] == "124"


def test_environment_of_the_caller_never_travels(far: Far, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CVJ_PLANTED_MARK", "zz-planted-9917")
    far.upload_and_claim()
    far.start("env > envdump.txt\n", env_sh="export FOO='bar'\n")
    assert b"zz-planted-9917" not in far.sent and b"CVJ_PLANTED_MARK" not in far.sent
    far.wait_exit()
    dump = (far.slot / "envdump.txt").read_text()
    names = {line.split("=", 1)[0] for line in dump.splitlines() if "=" in line}
    allowed = {"HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "LANG", "PATH", "CARNIVORE_JOB_ID", "CARNIVORE_JOB_DIR", "FOO", "PWD", "SHLVL", "_", "OLDPWD"}
    assert "zz-planted-9917" not in dump and "FOO" in names
    assert {n for n in names if not n.startswith("GIT_CONFIG_")} <= allowed


def test_sweep_and_forget(far: Far) -> None:
    far.upload_and_claim()
    far.start("true\n")
    far.wait_exit()
    old = far.meta()
    stamp = time.time() - 9 * 86400
    os.utime(old, (stamp, stamp))
    os.utime(far.slot.parent / "slot1.job", (stamp, stamp))
    assert far.call("sweep").fields["swept"] == "1" and not old.exists()
    far.upload_and_claim("job_aaaa0009")
    far.start("true\n", job="job_aaaa0009")
    far.wait_exit("job_aaaa0009")
    far.call("release", {"job": "job_aaaa0009", "keep": "1"})
    kept = far.call("forget", {"uid": UID, "name": NAME})
    assert kept.rc == 0 and kept.fields["kept"].endswith("slot1") and (far.root / "repos" / f"{UID}.git").exists()


def test_forget_removes_a_project_with_nothing_kept(far: Far) -> None:
    far.upload_and_claim()
    far.start("true\n")
    far.wait_exit()
    far.call("release", {"job": JOB})
    assert far.call("forget", {"uid": UID, "name": NAME}).rc == 0
    assert not (far.root / "repos" / f"{UID}.git").exists() and not far.slot.parent.exists()


def test_forget_removes_a_folder_made_under_another_name(far: Far) -> None:
    far.upload_and_claim()
    far.start("true\n")
    far.wait_exit()
    far.call("release", {"job": JOB})
    other = far.root / "folders" / f"feature-x-{UID[:8]}"
    (other / "slot1").mkdir(parents=True)
    assert far.call("forget", {"uid": UID, "name": "any"}).rc == 0
    assert not other.exists() and not far.slot.parent.exists() and not (far.root / "repos" / f"{UID}.git").exists()


def test_seal_refuses_a_wrong_hash(far: Far) -> None:
    far.call("hello")
    part = far.root / "in" / "abcd1234.part"
    part.write_bytes(b"data")
    bad = far.call("seal", {"blob": "abcd1234", "size": "4", "sha256": "0" * 64})
    assert bad.error is not None and bad.error[0] == "bad_upload" and part.exists()


def test_a_command_with_a_close_paren_runs_as_data_under_bash_3(far: Far) -> None:
    if not os.path.exists("/bin/bash"):
        pytest.skip("no /bin/bash")
    far.upload_and_claim()
    marker = far.home / "driver-ran-this"
    command = f"echo a )\ntouch {marker}\n"
    values = {"uid": UID, "name": NAME, "job": JOB, "slot": "1", "commit": far.commit, "cap": "60", "blob": far.blob}
    nonce = far_script.new_nonce()
    rc, out, _err = fake_far.run(far_script.render("start", values, command=command, nonce=nonce), far.home, shell="/bin/bash")
    assert far_script.parse(out, nonce).rc == 0 == rc
    assert (far.meta() / "command.sh").read_text() == command
    far.wait_exit()


def test_a_second_claim_of_one_project_gets_another_slot(far: Far) -> None:
    assert far.call("claim", {"uid": UID, "name": NAME, "job": JOB}).fields["slot"] == "1"
    assert far.call("claim", {"uid": UID, "name": NAME, "job": "job_aaaa0002"}).fields["slot"] == "2"
    old = time.time() - 2 * 3600
    os.utime(far.slot.parent / "slot1.job", (old, old))
    assert far.call("claim", {"uid": UID, "name": NAME, "job": "job_aaaa0003"}).fields["slot"] == "1"


def test_a_command_group_is_killed_when_its_leader_exits(far: Far) -> None:
    far.upload_and_claim()
    pidfile = far.home / "bg.pid"
    far.start(f"sleep 300 &\necho $! > {pidfile}\n")
    far.wait_exit()
    pid = int(pidfile.read_text())
    for _ in range(40):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.25)
    raise AssertionError("the background process outlived the job")


def test_an_existing_root_without_the_marker_is_refused(far: Far) -> None:
    mine = far.home / "work"
    (mine / "meta").mkdir(parents=True)
    mine.chmod(0o755)
    answer = far.call("hello", {"root": str(mine)})
    assert answer.error is not None and answer.error[0] == "bad_far_root"
    assert (mine.stat().st_mode & 0o777) == 0o755
    with pytest.raises(far_script.FarScriptError):
        far_script.render("hello", {"root": "/a/../etc"}, nonce=far_script.new_nonce())


def test_a_bad_pid_file_reads_lost(far: Far) -> None:
    far.upload_and_claim()
    far.start("true\n")
    far.wait_exit()
    far.meta().joinpath("exit").unlink()
    for bad in ("1\n", "12 34\n", "x\n"):
        far.meta().joinpath("pid").write_text(bad)
        assert far.call("status", {"job": JOB}).fields["state"] == "lost"


def test_parse_refuses_a_second_end_line_and_strips_c1_controls() -> None:
    nonce = far_script.new_nonce()
    with pytest.raises(JobError):
        far_script.parse(f"CVJ{nonce} end 0\nCVJ{nonce} end 1\n".encode(), nonce)
    answer = far_script.parse(f"CVJ{nonce} reason x\u009b31m\u202eevil\nCVJ{nonce} end 0\n".encode(), nonce)
    assert answer.fields["reason"] == "x31mevil"
