
from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

HOST_KEY_CHANGED_TEXT = """@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @
@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@
IT IS POSSIBLE THAT SOMEONE IS DOING SOMETHING NASTY!
Someone could be eavesdropping on you right now (man-in-the-middle attack)!
It is also possible that a host key has just been changed.
The fingerprint for the ED25519 key sent by the remote host is
SHA256:0000000000000000000000000000000000000000000.
Please contact your system administrator.
Add correct host key in {root}/known_hosts to get rid of this message.
Offending ED25519 key in {root}/known_hosts:1
Host key for {host} has changed and you have requested strict checking.
Host key verification failed.
"""

_FLAGS_WITH_VALUE = ("-p", "-O", "-F")
_BARE_FLAGS = ("-N", "-G")


def _say(message: str) -> None:
    sys.stderr.write(message.rstrip("\n") + "\n")
    sys.stderr.flush()


def _fail(message: str) -> int:
    _say(message)
    return 255


def _read(root: Path, name: str, default: str) -> str:
    try:
        return (root / name).read_text(encoding="utf-8").strip() or default
    except FileNotFoundError:
        return default


def _parse(argv: List[str]) -> Tuple[Dict[str, str], List[Tuple[str, str]], Dict[str, str],
                                      Optional[str], List[str]]:
    options: Dict[str, str] = {}
    pairs: List[Tuple[str, str]] = []
    flags: Dict[str, str] = {}
    index = 0
    while index < len(argv):
        word = argv[index]
        if word == "--":
            index += 1
            break
        if not word.startswith("-") or word == "-":
            break
        if word.startswith("-o"):
            value = word[2:] or (argv[index + 1] if index + 1 < len(argv) else "")
            index += 1 if word[2:] else 2
            key, sep, setting = value.partition("=")
            if not sep or not key:
                raise ValueError(f"fake_ssh: -o needs key=value, got {value!r}")
            options.setdefault(key.lower(), setting)
            pairs.append((key, setting))
            continue
        if word in _FLAGS_WITH_VALUE:
            if index + 1 >= len(argv):
                raise ValueError(f"fake_ssh: {word} needs a value")
            flags[word] = argv[index + 1]
            index += 2
            continue
        if word in _BARE_FLAGS:
            flags[word] = ""
            index += 1
            continue
        raise ValueError(f"fake_ssh: unsupported option {word}")
    destination = argv[index] if index < len(argv) else None
    return options, pairs, flags, destination, argv[index + 1:]


def _master_pid(control_path: Optional[str]) -> Optional[int]:
    if not control_path or control_path == "none":
        return None
    try:
        pid = int(Path(control_path).read_text(encoding="utf-8").strip())
        os.kill(pid, 0)
    except (OSError, ValueError):
        return None
    return pid


def _log(root: Path, mode: str, argv: List[str]) -> None:
    line = json.dumps({"mode": mode, "argv": argv, "pid": os.getpid(), "t": time.time()})
    with open(root / "calls.jsonl", "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _connection_failure(root: Path, destination: str) -> Optional[int]:
    scenario = _read(root, "scenario", "ok")
    host = destination.rpartition("@")[2]
    if scenario == "unreachable":
        return _fail(f"ssh: connect to host {host} port 22: Connection refused")
    if scenario == "auth_failed":
        return _fail(f"{destination}: Permission denied (publickey).")
    if scenario == "host_key_changed":
        return _fail(HOST_KEY_CHANGED_TEXT.format(root=root, host=host))
    if scenario == "hang":
        time.sleep(3600)
        return 255
    return None


def _serve_master(control_path: str) -> int:
    stop = {signal.SIGTERM, signal.SIGINT, signal.SIGHUP}
    signal.pthread_sigmask(signal.SIG_BLOCK, stop)
    if os.path.lexists(control_path):
        _say(f"ControlSocket {control_path} already exists, disabling multiplexing")
        signal.sigwait(stop)
        return 0
    foreign = _read(Path(os.environ["FAKE_SSH_ROOT"]), "scenario", "ok") == "foreign_master"
    fd = os.open(control_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(fd, str(os.getppid() if foreign else os.getpid()).encode())
    os.close(fd)
    signal.sigwait(stop)
    if _read(Path(control_path).parent, Path(control_path).name, "") in (
            str(os.getpid()), str(os.getppid())):
        os.unlink(control_path)
    return 0


def _exec_remote(root: Path, destination: str, command: str) -> int:
    user = destination.rpartition("@")[0] or os.environ.get("USER", "user")
    home = root / "home"
    tmux_tmpdir = root / "tmux"
    home.mkdir(exist_ok=True)
    tmux_tmpdir.mkdir(mode=0o700, exist_ok=True)
    env = {
        "HOME": str(home), "USER": user, "LOGNAME": user, "LANG": "C",
        "SHELL": _read(root, "shell", "/bin/sh"),
        "PATH": _read(root, "path", "/usr/bin:/bin:/usr/sbin:/sbin"),
        "TMUX_TMPDIR": str(tmux_tmpdir),
        "SSH_CONNECTION": "127.0.0.1 50000 127.0.0.1 22",
    }
    os.execve("/bin/sh", ["/bin/sh", "-c", command], env)
    return 255


def main(argv: List[str]) -> int:
    root_text = os.environ.get("FAKE_SSH_ROOT", "")
    if not root_text or not os.path.isdir(root_text):
        return _fail("fake_ssh: FAKE_SSH_ROOT is not a directory; refusing to run anything")
    root = Path(root_text)
    try:
        options, pairs, flags, destination, words = _parse(argv)
    except ValueError as exc:
        _log(root, "refused", argv)
        return _fail(str(exc))
    if destination is None:
        _log(root, "refused", argv)
        return _fail("fake_ssh: no destination")
    if destination.startswith("-"):
        _log(root, "refused", argv)
        return _fail("hostname contains invalid characters")
    control_path = options.get("controlpath")
    if "-G" in flags:
        _log(root, "config", argv)
        for key, value in pairs:
            print(f"{key.lower()} {value}")
        print(f"hostname {destination.rpartition('@')[2]}")
        if "userknownhostsfile" not in options:
            print("userknownhostsfile " + _read(root, "known_hosts_setting",
                                                "~/.ssh/known_hosts ~/.ssh/known_hosts2"))
        return 0
    if "-O" in flags:
        _log(root, f"control_{flags['-O']}", argv)
        pid = _master_pid(control_path)
        if pid is None:
            reason = "Connection refused" if control_path and os.path.lexists(control_path) \
                else "No such file or directory"
            return _fail(f"Control socket connect({control_path}): {reason}")
        if flags["-O"] == "check":
            _say(f"Master running (pid={pid})")
            return 0
        if flags["-O"] == "exit":
            os.kill(pid, signal.SIGTERM)
            _say("Exit request sent.")
            return 0
        return _fail(f"fake_ssh: -O {flags['-O']} is not emulated")
    if "-N" in flags:
        if options.get("controlmaster") not in ("yes", "auto"):
            return _fail("fake_ssh: -N without ControlMaster=yes is not emulated")
        if not control_path or control_path == "none":
            return _fail("fake_ssh: a master needs a ControlPath")
        _log(root, "master", argv)
        failed = _connection_failure(root, destination)
        return failed if failed is not None else _serve_master(control_path)
    if not words:
        return _fail("fake_ssh: an interactive login is not emulated")
    command = " ".join(words)
    if control_path and control_path != "none" and options.get("controlmaster", "no") == "no":
        if _master_pid(control_path) is not None:
            _log(root, "mux", argv)
            return _exec_remote(root, destination, command)
        if "proxycommand" in options:
            _log(root, "mux_refused", argv)
            return 255
        _log(root, "direct_fallback", argv)
    else:
        _log(root, "direct", argv)
    failed = _connection_failure(root, destination)
    return failed if failed is not None else _exec_remote(root, destination, command)



class FakeSshHost:

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(dir="/tmp", prefix="fssh"))
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.control_dir = Path(tempfile.mkdtemp(prefix="cm"))
        wrapper_dir = self.root / "local"
        wrapper_dir.mkdir()
        self.ssh_binary = str(wrapper_dir / "fake_ssh")
        Path(self.ssh_binary).write_text(
            "#!/bin/sh\n"
            f"FAKE_SSH_ROOT={shlex.quote(str(self.root))}; export FAKE_SSH_ROOT\n"
            f"exec {shlex.quote(sys.executable)} {shlex.quote(str(Path(__file__).resolve()))} "
            '"$@"\n', encoding="utf-8")
        os.chmod(self.ssh_binary, 0o755)
        (self.root / "home").mkdir()

    def set(self, name: str, value: str) -> None:
        (self.root / name).write_text(value + "\n", encoding="utf-8")

    def add_tool(self, name: str, script: str) -> Path:
        path = self.bin_dir / name
        path.write_text("#!/bin/sh\n" + script, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return path

    def add_fake_tmux(self, version: str = "tmux 3.7c", running: Tuple[str, ...] = ()) -> Path:
        names = " ".join(running)
        return self.add_tool("tmux", (
            f'if [ "$1" = "-V" ]; then echo "{version}"; exit 0; fi\n'
            'sock=default; if [ "$1" = "-L" ]; then sock=$2; fi\n'
            f'case " {names} " in *" $sock "*) echo x; exit 0;; esac\n'
            'echo "no server running on /private/tmp/tmux-501/$sock" >&2; exit 1\n'))

    def calls(self, mode: Optional[str] = None) -> List[dict]:
        try:
            lines = (self.root / "calls.jsonl").read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        entries = [json.loads(line) for line in lines if line.strip()]
        return [entry for entry in entries if mode is None or entry["mode"] == mode]

    def master_pids(self) -> List[int]:
        if not self.control_dir.is_dir():
            return []
        pids = [_master_pid(str(path)) for path in self.control_dir.iterdir()]
        return [pid for pid in pids if pid is not None]

    def cleanup(self) -> None:
        for pid in self.master_pids():
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.control_dir, ignore_errors=True)


def fake_ssh_host_fixture() -> Iterator[FakeSshHost]:
    host = FakeSshHost()
    try:
        yield host
    finally:
        host.cleanup()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
