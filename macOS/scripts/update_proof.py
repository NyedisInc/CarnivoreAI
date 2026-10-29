#!/usr/bin/env python3
"""N to N+1 auto-update proof for the Mac app (#660). Never run by tests or CI.

GATES (exit 3, nothing launched, unless all hold):
  1. Both builds are Developer ID signed (Squirrel.Mac refuses ad hoc) and carry the signed
     Info.plist purpose update-proof (release-build.sh stamps it from CARNIVORE_BUILD_PURPOSE):
     that purpose alone lets the packaged copy take the loopback feed below and install the
     X+1 update-proof build.
  2. CARNIVORE_PROOF_ISOLATION_VERIFIED=1: the operator accepts the isolation
     in docs/mac-auto-update.md, "Isolation", including its UNPROVEN list.
  3. Preflight: the copy's loopback port is free and no Squirrel ShipIt job for
     the bundle id is loaded. Any failed precondition is exit 3.

ISOLATION (evidence per path: docs/mac-auto-update.md): the copy gets a
whitelisted environment, HOME and CFFIXED_USER_HOME in a scratch home,
TMUX_TMPDIR and TMPDIR in the scratch dir, a pre-seeded server .env (free
loopback port, HOST 127.0.0.1) and config.json (relay off, no notification
destinations, own tmux socket name), CARNIVORE_SETTINGS_ENV_FILE (the server
then refuses every production Keychain item), CARNIVORE_LEDGER_KEEPALIVE=0,
and the switches --user-data-dir and --use-mock-keychain. The live state is
fingerprinted before launch and compared after; any change is a FAIL.

BUILDS: each release-build.sh run is its own process group. On timeout the
group gets SIGTERM, then up to 60 s for the signing scripts' EXIT trap to lock
and unlist the keychain, and SIGKILL only for what is still alive after that.

ENV VALUES
  CARNIVORE_PROOF_ISOLATION_VERIFIED=1   the gate above
  CARNIVORE_PROOF_BUILD_TIMEOUT_S        per build, default 5400 (90 minutes)
  CARNIVORE_PROOF_CLICK_WINDOW_S         wait for the click, default 3600
  CARNIVORE_PROOF_AUTO_INSTALL=1         unattended run: the copy's seeded config turns updates.auto_update on, so the
                                         app downloads X+1 and installs it at its first quiet moment (the same
                                         quitAndInstall as the tray click) with nobody clicking

Usage:
  CARNIVORE_PROOF_ISOLATION_VERIFIED=1 python3 macOS/scripts/update_proof.py
  CARNIVORE_PROOF_ISOLATION_VERIFIED=1 python3 macOS/scripts/update_proof.py --reuse <evidence dir>
--reuse skips both builds and re-runs only the launch-and-wait on an existing
evidence directory (a fresh scratch home and a fresh copy of the built X), so a
missed click costs no rebuild.

Output: PASS or FAIL with the evidence directory. Exit 0 pass, 1 fail, 3 gated.
"""

import base64
import functools
import http.server
import json
import os
import plistlib
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

MAC_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = MAC_DIR.parent
BUNDLE_ID = "ai.carnivore.menubar"
LIVE_PORT = 8000
SHIPIT_LABEL = BUNDLE_ID + ".ShipIt"
RELAUNCH_WAIT_S = 120
DEFAULT_BUILD_TIMEOUT_S = 5400
DEFAULT_CLICK_WINDOW_S = 3600
TERM_GRACE_S = 60
ENV_PASS = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "USER", "LOGNAME", "SHELL")
STABLE_FILES = ("config.json", ".env", "menubar-settings.json", ".version", ".deps-hash")


def bump_patch(version: str) -> str:
    major, minor, patch = (int(p) for p in version.split("."))
    return f"{major}.{minor}.{patch + 1}"


def app_version(app: Path) -> str:
    with open(app / "Contents" / "Info.plist", "rb") as fh:
        return plistlib.load(fh)["CFBundleShortVersionString"]


def safe_version(app: Path) -> str:
    try:
        return app_version(app)
    except (OSError, KeyError, plistlib.InvalidFileException):
        return ""


def build_purpose(app: Path) -> str:
    with open(app / "Contents" / "Info.plist", "rb") as fh:
        return plistlib.load(fh).get("CarnivoreBuildPurpose", "")


def require_proof_build(app: Path) -> None:
    purpose = build_purpose(app)
    if purpose != "update-proof":
        raise PermissionError(f"{app} has build purpose {purpose or 'none'}, not update-proof")


def is_developer_id(app: Path) -> bool:
    r = subprocess.run(["codesign", "-dv", "--verbose=2", str(app)],
                       capture_output=True, text=True)
    return "Authority=Developer ID Application" in r.stderr


def env_seconds(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    return int(raw) if raw.isdigit() and int(raw) > 0 else default



def terminate_group(pgid: int, grace_s: float, leader: "subprocess.Popen | None" = None) -> bool:
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return False
    deadline = time.time() + grace_s
    while time.time() < deadline:
        if leader is not None:
            leader.poll()
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return False
        time.sleep(0.2)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return False
    return True


def run_build(args: list, timeout_s: float, grace_s: float = TERM_GRACE_S) -> int:
    env = {**os.environ, "CARNIVORE_BUILD_PURPOSE": "update-proof"}
    proc = subprocess.Popen(args, cwd=MAC_DIR, start_new_session=True, env=env)
    try:
        return proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        killed = terminate_group(proc.pid, grace_s, proc)
        proc.wait()
        raise TimeoutError("build exceeded %ss; SIGTERM sent to its group%s" % (
            timeout_s, ", SIGKILL after the grace" if killed else ", it exited on SIGTERM"))


def build(version_override: str | None, out: Path) -> Path:
    args = [str(MAC_DIR / "scripts" / "release-build.sh"),
            f"-c.directories.output={out}", "--publish", "never"]
    if version_override:
        args.append(f"-c.extraMetadata.version={version_override}")
    code = run_build(args, env_seconds("CARNIVORE_PROOF_BUILD_TIMEOUT_S", DEFAULT_BUILD_TIMEOUT_S))
    if code != 0:
        raise subprocess.CalledProcessError(code, args)
    return out / "mac-universal" / "Carnivore.app"



def port_busy(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def free_port() -> int:
    while True:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        if port != LIVE_PORT:
            return port


def run_text(cmd: list) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout


def preflight(port: int) -> list:
    bad = []
    if port == LIVE_PORT or port_busy(port):
        bad.append(f"port {port} is busy or is the live port")
    jobs = [ln for ln in run_text(["launchctl", "list"]).splitlines()
            if SHIPIT_LABEL in ln]
    if jobs:
        bad.append("a Squirrel ShipIt job for %s is loaded (an update is in flight): %s"
                   % (BUNDLE_ID, jobs[0].strip()))
    return bad


def paths_for(work: Path) -> dict:
    home = work / "home"
    user_data = home / "Library" / "Application Support" / "Carnivore Menubar"
    return {"home": home, "user_data": user_data, "server": user_data / "server",
            "state": home / "Library" / "Application Support" / "Carnivore",
            "tmux": work / "tmux", "tmp": work / "tmp",
            "socket": work / "tmux" / f"tmux-{os.getuid()}" / "proofcopy"}


def copy_env(work: Path, port: int, feed_url: str) -> dict:
    p = paths_for(work)
    env = {k: os.environ[k] for k in ENV_PASS if k in os.environ}
    env.update(
        HOME=str(p["home"]), CFFIXED_USER_HOME=str(p["home"]),
        TMUX_TMPDIR=str(p["tmux"]), TMPDIR=str(p["tmp"]),
        CARNIVORE_UPDATE_FEED_URL=feed_url,
        CARNIVORE_STATE_DIR=str(p["state"]),
        CARNIVORE_SETTINGS_ENV_FILE=str(p["server"] / ".env"),
        CARNIVORE_LEDGER_KEEPALIVE="0",
        PORT=str(port), HOST="127.0.0.1")
    return env


def copy_argv(exe: Path, work: Path) -> list:
    return [str(exe), f"--user-data-dir={paths_for(work)['user_data']}", "--use-mock-keychain"]


MARKER_NAME = ".carnivore-proof-marker.json"
MARKER_LOG = "marker-applied.log"


def write_marker(work: Path, port: int) -> Path:
    p = paths_for(work)
    marker = work / "Applications" / MARKER_NAME
    body = {"home": str(p["home"]), "user_data": str(p["user_data"]), "state": str(p["state"]),
            "tmux": str(p["tmux"]), "tmp": str(p["tmp"]), "settings_env": str(p["server"] / ".env"),
            "port": port, "host": "127.0.0.1"}
    marker.unlink(missing_ok=True)
    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(body, fh)
    return marker


def unhonored_strays(strays: list, work: Path) -> list:
    log = work / "Applications" / MARKER_LOG
    honored = set()
    if log.is_file():
        for ln in log.read_text().splitlines():
            parts = ln.split()
            if len(parts) == 3 and parts[0].isdigit() and parts[2] == "applied":
                honored.add(int(parts[0]))
    return [pid for pid in strays if pid not in honored]


def seed_home(work: Path, port: int) -> None:
    p = paths_for(work)
    for key in ("server", "state", "tmux", "tmp"):
        p[key].mkdir(parents=True, exist_ok=True)
    (p["home"] / "carnivore-projects").mkdir(exist_ok=True)
    (p["home"] / "Library" / "Logs" / "cloude-code").mkdir(parents=True, exist_ok=True)
    subs = {"HOST": "127.0.0.1", "PORT": str(port),
            "TOTP_SECRET": base64.b32encode(os.urandom(20)).decode(),
            "JWT_SECRET": secrets.token_hex(32),
            "DEFAULT_WORKING_DIR": str(p["home"] / "carnivore-projects"),
            "LOG_DIRECTORY": str(p["home"] / "Library" / "Logs" / "cloude-code"),
            "CARNIVORE_STATE_DIR": str(p["state"])}
    lines = []
    for line in (REPO_DIR / ".env.example").read_text().split("\n"):
        key = line.split("=", 1)[0]
        lines.append(f"{key}={subs[key]}" if key in subs and "=" in line else line)
    env_path = p["server"] / ".env"
    env_path.write_text("\n".join(lines))
    env_path.chmod(0o600)
    cfg = json.loads((REPO_DIR / "config.example.json").read_text())
    cfg.setdefault("session", {})["tmux_socket_name"] = "proofcopy"
    cfg.pop("notifications", None)
    cfg["relay"] = {"enabled": False}
    if os.environ.get("CARNIVORE_PROOF_AUTO_INSTALL") == "1":
        cfg["updates"] = {**cfg.get("updates", {}), "auto_update": True}
    cfg.setdefault("server_prefs", {})["bind_host"] = "127.0.0.1"
    (p["server"] / "config.json").write_text(json.dumps(cfg, indent=2) + "\n")
    (p["server"] / "config.json").chmod(0o600)



def dir_fingerprint(root: Path, depth: int = 1, dir_mtimes: bool = True) -> dict:
    out: dict = {}
    if not root.is_dir():
        return {"<missing>": "1"}
    for entry in sorted(root.iterdir()):
        try:
            st = entry.stat()
        except OSError:
            continue
        if entry.is_dir():
            out[entry.name + "/"] = str(int(st.st_mtime)) if dir_mtimes else ""
            if depth > 0:
                for k, v in dir_fingerprint(entry, depth - 1, dir_mtimes).items():
                    out[f"{entry.name}/{k}"] = v
        elif entry.name in STABLE_FILES:
            out[entry.name] = f"{int(st.st_mtime)}:{st.st_size}"
        else:
            out[entry.name] = ""
    return out


def live_fingerprint(home: Path | None = None) -> dict:
    home = home or Path.home()
    support = home / "Library" / "Application Support"
    agents = home / "Library" / "LaunchAgents"
    snap = {
        "userData": dir_fingerprint(support / "Carnivore Menubar"),
        "stateDir": dir_fingerprint(support / "Carnivore", dir_mtimes=False),
        "launchAgentFiles": {f.name: str(int(f.stat().st_mtime)) for f in sorted(agents.glob("*"))
                             if re.search("carnivore|cloude", f.name, re.I)} if agents.is_dir() else {},
        "port8000Pid": run_text(["lsof", "-nP", f"-iTCP:{LIVE_PORT}", "-sTCP:LISTEN", "-t"]).strip(),
        "tmuxCloude": run_text(["tmux", "-L", "cloude", "list-sessions", "-F", "#{session_name}"]).strip(),
        "launchctl": sorted(ln.strip() for ln in run_text(["launchctl", "list"]).splitlines()
                            if re.search("carnivore|cloude", ln, re.I) and not ln.strip().endswith(SHIPIT_LABEL)),
    }
    app = Path("/Applications/Carnivore.app/Contents/Info.plist")
    snap["installedApp"] = f"{int(app.stat().st_mtime)}" if app.exists() else "absent"
    return snap


def fingerprint_diff(before: dict, after: dict) -> list:
    lines = []
    for section in sorted(set(before) | set(after)):
        b, a = before.get(section), after.get(section)
        if b == a:
            continue
        if isinstance(b, dict) and isinstance(a, dict):
            for k in sorted(set(b) | set(a)):
                if b.get(k) != a.get(k):
                    lines.append(f"{section}: {k}: {b.get(k)!r} -> {a.get(k)!r}")
        else:
            lines.append(f"{section}: {b!r} -> {a!r}")
    return lines



def find_strays(app: Path, group: int) -> list:
    needle = str(app) + "/Contents/MacOS/"
    pids = []
    for ln in run_text(["ps", "-axo", "pid=,pgid=,command="]).splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+)\s+(.*)", ln)
        if m and needle in m.group(3) and int(m.group(2)) != group:
            pids.append(int(m.group(1)))
    return pids


def await_relaunch(app: Path, group: int, work: Path, strays: list) -> list:
    end = time.time() + RELAUNCH_WAIT_S
    while time.time() < end:
        strays = find_strays(app, group) or strays
        if strays and not unhonored_strays(strays, work):
            break
        time.sleep(0.5)
    return strays


def remove_shipit_job() -> None:
    try:
        subprocess.run(["launchctl", "remove", SHIPIT_LABEL], capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        pass


def stop_tmux_in(work: Path) -> None:
    sock = paths_for(work)["socket"]
    if sock.exists() and sock.resolve().is_relative_to(work.resolve()):
        subprocess.run(["tmux", "-S", str(sock), "kill-server"], capture_output=True, timeout=20)


def launch_copy(x_app: Path, work: Path, env: dict) -> subprocess.Popen:
    log = open(work / "copy.log", "ab")
    return subprocess.Popen(copy_argv(x_app / "Contents" / "MacOS" / "Carnivore", work),
                            env=env, start_new_session=True, stdout=log, stderr=log)


def prepare(work: Path, reuse: bool) -> tuple:
    x_version = json.loads((MAC_DIR / "package.json").read_text())["version"]
    y_version = bump_patch(x_version)
    if reuse:
        x_built = work / "x" / "mac-universal" / "Carnivore.app"
        if not x_built.is_dir() or not (work / "feed" / "latest-mac.yml").is_file():
            raise FileNotFoundError(f"{work} has no built x/ app or feed/latest-mac.yml to reuse")
        require_proof_build(x_built)
        return app_version(x_built), y_version, x_built, work / "feed"
    x_built = build(None, work / "x")
    y_built = build(y_version, work / "y")
    require_proof_build(x_built)
    require_proof_build(y_built)
    if not (is_developer_id(x_built) and is_developer_id(y_built)):
        raise PermissionError("builds are not Developer ID signed, an update cannot be proved")
    feed_dir = work / "feed"
    feed_dir.mkdir()
    for f in (work / "y").iterdir():
        if f.name.endswith(("-mac.zip", "-mac.zip.blockmap")) or f.name == "latest-mac.yml":
            shutil.copy2(f, feed_dir)
    return x_version, y_version, x_built, feed_dir


def main(argv: list | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    reuse = Path(argv[argv.index("--reuse") + 1]) if "--reuse" in argv else None
    if os.environ.get("CARNIVORE_PROOF_ISOLATION_VERIFIED") != "1":
        print("gated: set CARNIVORE_PROOF_ISOLATION_VERIFIED=1 after reading the Isolation section "
              "of docs/mac-auto-update.md", file=sys.stderr)
        return 3
    port = free_port()
    bad = preflight(port)
    if bad:
        print("gated: " + "; ".join(bad), file=sys.stderr)
        return 3
    work = reuse.resolve() if reuse else Path(
        os.path.realpath(tempfile.mkdtemp(prefix="cup-", dir="/tmp")))
    try:
        x_version, y_version, x_built, feed_dir = prepare(work, reuse is not None)
    except (PermissionError, FileNotFoundError) as exc:
        print(f"gated: {exc} (evidence dir {work})", file=sys.stderr)
        return 3
    except (TimeoutError, subprocess.CalledProcessError) as exc:
        print(f"FAIL: build did not finish: {exc} (evidence dir {work})")
        return 1

    class Handler(http.server.SimpleHTTPRequestHandler):
        requested: list = []

        def do_GET(self):
            Handler.requested.append(self.path)
            super().do_GET()

    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Handler, directory=str(feed_dir)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    feed_url = f"http://127.0.0.1:{server.server_address[1]}"

    for key in ("home", "tmux", "tmp"):
        shutil.rmtree(paths_for(work)[key], ignore_errors=True)
    x_app = work / "Applications" / "Carnivore.app"
    shutil.rmtree(x_app.parent, ignore_errors=True)
    x_app.parent.mkdir()
    shutil.copytree(x_built, x_app, symlinks=True)
    seed_home(work, port)
    write_marker(work, port)
    bad = preflight(port)
    if bad:
        server.shutdown()
        print("gated: " + "; ".join(bad), file=sys.stderr)
        return 3
    before = live_fingerprint()
    proc = launch_copy(x_app, work, copy_env(work, port, feed_url))
    window = env_seconds("CARNIVORE_PROOF_CLICK_WINDOW_S", DEFAULT_CLICK_WINDOW_S)
    deadline = time.time() + window
    print(f"READY: copy of X={x_version} running (pid {proc.pid}, port {port}, feed {feed_url}); "
          f"waiting for your click on 'Restart to Update to {y_version}' in the tray "
          f"once it reads 'updates: {y_version} ready'. Click window closes at "
          f"{datetime.fromtimestamp(deadline):%H:%M:%S} ({window}s). Evidence {work}", flush=True)
    ok, why = False, "no update seen before the click window closed"
    strays: list = []
    try:
        while time.time() < deadline:
            time.sleep(0.5)
            got_zip = any(p.endswith("-mac.zip") for p in Handler.requested)
            strays = find_strays(x_app, proc.pid) or strays
            if got_zip and safe_version(x_app) == y_version:
                ok, why = True, ""
                strays = await_relaunch(x_app, proc.pid, work, strays)
                if not strays:
                    ok, why = False, f"the bundle is {y_version} but ShipIt did not relaunch it within {RELAUNCH_WAIT_S}s"
                break
            if proc.poll() is not None and not got_zip:
                why = f"the copy exited ({proc.returncode}) before downloading; see {work}/copy.log"
                break
    finally:
        terminate_group(proc.pid, 20, proc)
        for pid in strays:
            _stop_pid(pid)
        stop_tmux_in(work)
        server.shutdown()
        remove_shipit_job()
    loose = unhonored_strays(strays, work)
    if ok and loose:
        ok, why = False, ("ShipIt relaunched the updated app OUTSIDE the isolated environment "
                          f"(pids {loose}, no applied line in {MARKER_LOG}); it ran against the real home and was stopped")
    diff = fingerprint_diff(before, live_fingerprint())
    if diff:
        ok = False
        why = (why + "; " if why else "") + "live state changed during the run"
        print("LIVE STATE CHANGED:\n  " + "\n  ".join(diff))
    print(f"feed requests: {Handler.requested}")
    print(("PASS" if ok else "FAIL") + f": {x_version} -> {safe_version(x_app) or 'unreadable'}"
          + (f" ({why})" if why else "") + f" (evidence {work})")
    return 0 if ok else 1


def _stop_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(50):
            time.sleep(0.2)
            os.kill(pid, 0)
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return


if __name__ == "__main__":
    sys.exit(main())
