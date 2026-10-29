
import json
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from tests.socket_guard import TEST_SOCKET_NAME

ROOT = Path(__file__).resolve().parents[3]
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
DENY_NETWORK = ('(version 1)(allow default)(deny network-outbound)'
                '(allow network-outbound (remote ip "localhost:*"))(allow network-outbound (remote unix-socket))')
USER_TOOL_PREFIXES = ("/opt/homebrew", "/usr/local", "/opt/local")
DENY_USER_TOOLS = "".join(f'(deny file-read* (subpath "{p}"))(deny process-exec (subpath "{p}"))' for p in USER_TOOL_PREFIXES)
PROFILE = DENY_NETWORK + DENY_USER_TOOLS
ARCH = {"arm64": "arm64", "x86_64": "x86_64"}.get(platform.machine(), "")
TREE = Path(os.environ.get("CARNIVORE_PAYLOAD_OUT", Path.home() / ".cache" / "carnivore-payload" / "out")) / f"payload-{ARCH}"
SKIP_WHY = (f"the payload tree is not built on this computer ({TREE}); build it with "
            f"`bash macOS/payload/build-payload.sh {ARCH or 'arm64'}`")

pytestmark = [
    pytest.mark.skipif(sys.platform != "darwin", reason="the payload and the sandbox profile are macOS only"),
    pytest.mark.skipif(not (TREE / "python" / "bin" / "python3").is_file() or not (TREE / "bin" / "tmux").is_file(),
                       reason=SKIP_WHY),
]


def _free_port() -> int:
    for port in range(5101, 5400):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("no free port in 5101..5399")


def _shell_env(base: Path) -> dict:
    resources = base / "res" / "payload"
    resources.mkdir(parents=True)
    (resources / TREE.name).symlink_to(TREE)
    script = ("const p=require(process.argv[1]+'/macOS/engine/payload-select.js');"
              "const payload=p.resolvePayload(process.argv[2],process.argv[3]);"
              "if(!payload){console.error('no payload');process.exit(3)}"
              "process.stdout.write(JSON.stringify(p.payloadEngineEnv(payload,{},process.argv[4]+'/server/bin',process.argv[4]+'/stage',process.argv[4]+'/pycache')))")
    node_arch = {"arm64": "arm64", "x86_64": "x64"}[ARCH]
    out = subprocess.run(["node", "-e", script, str(ROOT), str(base / "res"), node_arch, str(base)], check=True,
                         capture_output=True, text=True).stdout
    return json.loads(out)


def _sandboxed(argv, env, **kw):
    return subprocess.Popen([SANDBOX_EXEC, "-p", PROFILE, *argv], env=env, start_new_session=True, **kw)


@pytest.fixture()
def rig():
    base = Path(tempfile.mkdtemp(prefix="r204-"))
    server = base / "server"
    server.mkdir()
    (server / "src").symlink_to(ROOT / "src")
    (server / "client").symlink_to(ROOT / "client")
    config = json.loads((ROOT / "config.example.json").read_text())
    socket_name = TEST_SOCKET_NAME
    config.setdefault("session", {})["tmux_socket_name"] = socket_name
    (server / "config.json").write_text(json.dumps(config))
    for name in ("home", "state", "logs", "tmux"):
        (base / name).mkdir()
    port = _free_port()
    env = _shell_env(base)
    env.update({
        "HOME": str(base / "home"), "PORT": str(port), "HOST": "127.0.0.1",
        "CARNIVORE_STATE_DIR": str(base / "state"), "LOG_DIRECTORY": str(base / "logs"), "TMUX_TMPDIR": str(base / "tmux"),
        "TOTP_SECRET": "JBSWY3DPEHPK3PXP", "JWT_SECRET": "r204-throwaway-signing-key-not-a-secret-0123456789",
    })
    started = []
    yield {"base": base, "server": server, "env": env, "port": port, "socket": socket_name, "started": started}
    for proc in started:
        if proc.poll() is None:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(proc.pid, sig)
                except ProcessLookupError:
                    break
                try:
                    proc.wait(timeout=8)
                    break
                except subprocess.TimeoutExpired:
                    continue
    subprocess.run([str(TREE / "bin" / "tmux"), "-L", socket_name, "kill-server"], env={"TMUX_TMPDIR": str(base / "tmux"), "PATH": "/usr/bin:/bin"},
                   capture_output=True)
    shutil.rmtree(base, ignore_errors=True)


PIP_WORDS = {"pip", "pip3", "ensurepip"}


def _is_pip_command(command: str) -> bool:
    words = command.split()
    names = {os.path.basename(w) for w in words}
    return bool(PIP_WORDS & names) or any(a == "-m" and b in PIP_WORDS for a, b in zip(words, words[1:]))


class PipWatcher:

    def __init__(self, root_pid: int) -> None:
        self.root = root_pid
        self.seen: list = []
        self.samples = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _tree(self) -> list:
        rows = subprocess.run(["/bin/ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True).stdout.splitlines()
        parsed = {}
        for row in rows:
            parts = row.split(None, 2)
            if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
                parsed[int(parts[0])] = (int(parts[1]), parts[2])
        keep, grew = {self.root}, True
        while grew:
            grew = False
            for pid, (ppid, _) in parsed.items():
                if ppid in keep and pid not in keep:
                    keep.add(pid)
                    grew = True
        return [parsed[pid][1] for pid in keep if pid in parsed]

    def _run(self) -> None:
        while not self._stop.is_set():
            self.samples += 1
            self.seen += [c for c in self._tree() if _is_pip_command(c) and c not in self.seen]
            self._stop.wait(0.1)

    def __enter__(self) -> "PipWatcher":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join(timeout=5)


def _first_existing(*names: str) -> str:
    for name in names:
        if os.path.isfile(name):
            return name
    pytest.skip("no Homebrew-style tmux or python on this computer, so the profile cannot be shown denying one")


def _chosen_tmux(rig, env) -> str:
    probe = rig["server"] / "choose.py"
    probe.write_text("from src.core.tmux_discovery import tmux_argv_prefix\n"
                     f"print(tmux_argv_prefix({rig['socket']!r})[0])\n")
    chosen = _sandboxed([str(TREE / "python" / "bin" / "python3"), str(probe)], env, cwd=rig["server"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = chosen.communicate(timeout=60)
    return out.strip() or f"<no answer: {err[-200:]}>"


def test_the_profile_really_denies_homebrew(rig):
    brew = _first_existing("/opt/homebrew/bin/tmux", "/usr/local/bin/tmux", "/opt/local/bin/tmux")
    brew_python = _first_existing("/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/opt/local/bin/python3")
    direct = _sandboxed([brew_python, "-V"], rig["env"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert direct.wait(timeout=30) != 0, f"{brew_python} ran under the profile: Homebrew is not denied, so the boot check proves nothing"
    rig["env"]["R204_BREW_BIN"] = brew
    child = ("import os,subprocess,sys\n"
             "try:\n subprocess.run([os.environ['R204_BREW_BIN'],'-V'],check=True,capture_output=True)\n"
             "except (OSError, subprocess.CalledProcessError) as e:\n print('denied');sys.exit(0)\n"
             "print('RAN');sys.exit(1)\n")
    proc = _sandboxed([str(TREE / "python" / "bin" / "python3"), "-c", child], rig["env"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = proc.communicate(timeout=30)
    assert "denied" in out, f"a child process reached Homebrew under the profile: {out!r} {err[-200:]!r}"


def test_discovery_check_goes_red_when_pointed_at_homebrew(rig):
    brew = _first_existing("/opt/homebrew/bin/tmux", "/usr/local/bin/tmux", "/opt/local/bin/tmux")
    forced = {k: v for k, v in rig["env"].items() if k not in ("CARNIVORE_BUNDLED_TMUX", "CARNIVORE_TMUX_STAGE_DIR")}
    forced["PATH"] = os.path.dirname(brew) + ":/usr/bin:/bin"
    got = _chosen_tmux(rig, forced)
    assert os.path.realpath(got) != os.path.realpath(TREE / "bin" / "tmux"), "the control chose the bundled tmux; it cannot go red"



def test_pip_watcher_sees_a_pip_command_line(rig):
    assert _is_pip_command("/x/python3 -m pip install foo") and _is_pip_command("/usr/bin/pip3 --version")
    assert not _is_pip_command("/x/python3 -m src.main") and not _is_pip_command("/x/python3 /tmp/pipeline.py")
    decoy = subprocess.Popen(["/bin/sh", "-c", "sleep 2; true", "pip3"], start_new_session=True)
    try:
        with PipWatcher(os.getpid()) as watcher:
            time.sleep(1.0)
        assert watcher.samples >= 3 and any("pip3" in c for c in watcher.seen), watcher.seen
    finally:
        decoy.kill()
        decoy.wait()


def test_sandbox_really_denies_the_network(rig):
    code = ("import socket,sys\n"
            "s=socket.socket();s.bind(('127.0.0.1',0));s.listen()\n"
            "socket.create_connection(s.getsockname(),2)\n"
            "try:\n socket.create_connection(('1.1.1.1',53),3)\nexcept OSError as e:\n print('denied');sys.exit(0)\n"
            "print('REACHED');sys.exit(1)\n")
    proc = _sandboxed([str(TREE / "python" / "bin" / "python3"), "-c", code], rig["env"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = proc.communicate(timeout=30)
    assert "denied" in out, f"the sandbox did not deny outbound network (or could not be applied): {out!r} {err[-300:]!r}"


def test_engine_boots_healthy_on_the_payload_alone(rig):
    assert os.path.realpath(rig["env"]["PATH"].split(":")[0]) == str(TREE / "bin") and rig["env"]["PATH"].endswith("/usr/sbin:/sbin")
    assert rig["env"]["PYTHONNOUSERSITE"] == "1" and "PYTHONHOME" not in rig["env"]
    staged = Path(rig["env"]["CARNIVORE_BUNDLED_TMUX"])
    assert staged.is_file() and staged.is_relative_to(rig["base"] / "stage"), "the shell stages the bundled tmux before the boot"
    log = (rig["base"] / "engine.log").open("wb")
    python = str(TREE / "python" / "bin" / "python3")
    proc = _sandboxed([python, "-m", "src.main"], rig["env"], cwd=rig["server"], stdout=log, stderr=subprocess.STDOUT)
    rig["started"].append(proc)
    url = f"http://127.0.0.1:{rig['port']}/health"
    deadline = time.monotonic() + 90
    status = None
    with PipWatcher(proc.pid) as watcher:
        while time.monotonic() < deadline and proc.poll() is None:
            try:
                with urllib.request.urlopen(url, timeout=3) as response:
                    status = response.status
                    break
            except OSError:
                time.sleep(1)
        time.sleep(1.0)
    log.flush()
    tail = (rig["base"] / "engine.log").read_text(errors="replace")[-1500:]
    assert status == 200, f"/health did not answer 200 (exit {proc.poll()}):\n{tail}"

    opened = subprocess.run(["/usr/sbin/lsof", "-p", str(proc.pid), "-Fn"], capture_output=True, text=True).stdout
    assert str(TREE) in opened, "the engine process holds no file from the payload tree"
    assert "/opt/homebrew" not in opened and "/usr/local/" not in opened, "the engine opened a Homebrew file"
    assert "/opt/homebrew" not in tail
    assert watcher.samples >= 5 and not watcher.seen, f"pip ran during the boot ({watcher.samples} samples): {watcher.seen}"

    chosen = _chosen_tmux(rig, rig["env"])
    assert os.path.realpath(chosen) == os.path.realpath(staged), f"tmux chosen was {chosen!r}"
