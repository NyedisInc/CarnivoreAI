
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
NUKE_SH = REPO_ROOT / "nuke.sh"

SANDBOX_PORT = 45219

BYSTANDERS = {
    "home/Documents/keep-me.txt": "user document",
    "home/Library/Application Support/SomeOtherApp/data.db": "other app",
    "home/Library/LaunchAgents/com.example.other.plist": "other agent",
    "tmp/unrelated.log": "someone else's log",
    "install/README.md": "repo file",
    "install/src/main.py": "source file",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if p.is_symlink():
            out[rel] = "link:" + os.readlink(p)
        elif p.is_dir():
            out[rel] = "dir"
        else:
            out[rel] = _sha256(p)
    return out


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _port_is_free(port: int) -> bool:
    proc = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True, check=False
    )
    return proc.stdout.strip() == ""


def _resolved_port(install: Path) -> str:
    proc = subprocess.run(
        ["bash", "-c", 'source "$1/scripts/resolve-port.sh" && resolve_port "$1"', "resolver", str(install)],
        capture_output=True, text=True, check=False,
    )
    return proc.stdout.strip()


@pytest.fixture()
def sandbox(tmp_path: Path) -> dict:
    root = tmp_path / "sbx"
    install = root / "install"
    home = root / "home"
    tmp = root / "tmp"
    state = root / "state"
    stubs = root / "stubs"

    install.mkdir(parents=True)
    shutil.copy2(NUKE_SH, install / "nuke.sh")
    (install / "scripts").mkdir()
    shutil.copy2(REPO_ROOT / "scripts" / "resolve-port.sh", install / "scripts")
    shutil.copytree(
        REPO_ROOT / "scripts" / "upgrade_lib", install / "scripts" / "upgrade_lib"
    )
    assert _sha256(install / "nuke.sh") == _sha256(NUKE_SH), (
        "the sandbox copy of nuke.sh must be byte-identical to the real one; "
        "a test of an edited script proves nothing about the shipped script"
    )

    _write(
        install / ".env",
        "\n".join(
            [
                f"PORT={SANDBOX_PORT}",
                f"CLOUDE_STATE_DIR={state}",
                f"LOG_DIRECTORY={home / 'Library' / 'Logs' / 'cloude-code'}",
                f"DEFAULT_WORKING_DIR={root / 'projects'}",
                "",
            ]
        ),
    )
    _write(install / "config.json", json.dumps({"session": {"tmux_socket_name": "carnivore"}}))
    _write(install / "totp-qr.png", "png")
    _write(install / "session_metadata.json", "{}")
    _write(install / ".env.tmp", "tmp")
    _write(install / "venv" / "bin" / "python3", "#!/bin/sh\n")

    _write(state / "cloude.db", "sqlite")
    _write(state / "refresh_tokens.db", "tokens")
    _write(state / "migration_trail.jsonl", "{}\n")

    _write(home / "Library" / "LaunchAgents" / "com.cloudecode.menubar.plist", "plist")
    _write(home / "Library" / "Application Support" / "cloude-code-menubar" / "x", "x")
    _write(home / "Library" / "Application Support" / "Cloude Code" / "legacy", "x")

    for name in (
        "cloudecode-server.log",
        "cloudecode-menubar.log",
        "cloudecode-menubar-error.log",
        "electron-test.log",
        "cloudecode-nuke.log",
    ):
        _write(tmp / name, name)
    _write(tmp / "cloude-app-extract" / "payload", "x")

    _write(home / "Library" / "Logs" / "cloude-code" / "server.log", "log")
    _write(root / "projects" / "proj" / "file.txt", "work")

    for rel, content in BYSTANDERS.items():
        _write(root / rel, content)

    stubs.mkdir()

    poison = root / "poison-path"
    poison.mkdir()
    (poison / "python3").write_text("#!/bin/sh\nexit 3\n")
    (poison / "python3").chmod(0o755)

    tmux_stub = stubs / "tmux-record"
    tmux_log = root / "tmux-argv.txt"
    tmux_stub.write_text(f'#!/bin/sh\necho "$*" >> "{tmux_log}"\nexit 0\n')
    tmux_stub.chmod(0o755)

    scrubbed = {f"{prefix}{suffix}" for prefix in ("CARNIVORE_", "CLOUDE_", "CLOUDECODE_") for suffix in ("PAYLOAD_PYTHON", "APP_BUNDLE")}
    env = {k: v for k, v in os.environ.items() if k not in scrubbed and k != "TMUX"}
    env.update(
        {
            "CARNIVORE_APP_BUNDLE": str(root / "no-real-app" / "Carnivore.app"),
            "CLOUDE_NUKE_APP": str(root / "no-real-app" / "Carnivore.app"),
            "HOME": str(home),
            "PATH": f"{stubs}:{env['PATH']}",
            "CLOUDE_NUKE_HOME": str(home),
            "CLOUDE_NUKE_TMP_DIR": str(tmp),
            "CLOUDE_NUKE_LAUNCHCTL": "/usr/bin/true",
            "TMUX_TMPDIR": str(root / "tmux-tmp"),
            "CLOUDE_NUKE_TMUX_BIN": str(tmux_stub),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    env.pop("CLOUDE_STATE_DIR", None)
    env.pop("CLOUDE_NUKE_KILL_TMUX", None)
    env.pop("CLOUDE_NUKE_TMUX_SOCKET", None)

    return {
        "root": root,
        "install": install,
        "home": home,
        "tmp": tmp,
        "state": state,
        "env": env,
        "tmux_stub": tmux_stub,
        "tmux_log": tmux_log,
        "poison_path": poison,
    }


def _run_nuke(
    sbx: dict, *args: str, stdin: str = "NUKE\n", allow_busy_port: bool = False
) -> subprocess.CompletedProcess:
    resolved = _resolved_port(sbx["install"])
    if resolved != str(SANDBOX_PORT):
        pytest.fail(
            f"the port resolver answers {resolved!r} for {sbx['install']}, not {SANDBOX_PORT}: nuke.sh would act on "
            "the wrong port (8000 is the live app's). Not run."
        )
    if not (sbx["install"] / "config.json").is_file():
        pytest.fail(f"{sbx['install']}/config.json is missing: nuke.sh would fall back to the live 'cloude' tmux socket. Not run.")
    if not allow_busy_port and not _port_is_free(SANDBOX_PORT):
        pytest.skip(
            f"CANNOT DETERMINE: port {SANDBOX_PORT} has a live listener, so "
            "running nuke.sh would kill a real process. Not run."
        )
    return subprocess.run(
        [str(sbx["install"] / "nuke.sh"), *args],
        cwd=sbx["install"],
        env=sbx["env"],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )




def test_nuke_removes_state_directory_and_auth_tokens(sandbox):
    before = _manifest(sandbox["root"])
    assert "state/refresh_tokens.db" in before

    result = _run_nuke(sandbox)
    after = _manifest(sandbox["root"])

    assert result.returncode == 0, result.stderr
    assert not sandbox["state"].exists(), (
        "the state directory survived the nuke - cloude.db and "
        "refresh_tokens.db are still on disk after a reported full reset"
    )
    for gone in (
        "state",
        "state/cloude.db",
        "state/refresh_tokens.db",
        "state/migration_trail.jsonl",
    ):
        assert gone not in after


def test_nuke_removes_every_declared_target(sandbox):
    _run_nuke(sandbox)
    after = _manifest(sandbox["root"])

    expected_gone = [
        "install/.env",
        "install/config.json",
        "install/totp-qr.png",
        "install/session_metadata.json",
        "install/.env.tmp",
        "install/venv",
        "home/Library/LaunchAgents/com.cloudecode.menubar.plist",
        "home/Library/Application Support/cloude-code-menubar",
        "home/Library/Application Support/Cloude Code",
        "tmp/cloudecode-server.log",
        "tmp/cloudecode-menubar.log",
        "tmp/cloudecode-menubar-error.log",
        "tmp/electron-test.log",
        "tmp/cloudecode-nuke.log",
        "tmp/cloude-app-extract",
        "home/Library/Logs/cloude-code",
    ]
    survived = [t for t in expected_gone if t in after]
    assert not survived, f"targets survived the nuke: {survived}"
    assert "projects/proj/file.txt" in after, "nuke removed the projects folder"


def test_nuke_touches_nothing_it_did_not_declare(sandbox):
    before = _manifest(sandbox["root"])
    _run_nuke(sandbox)
    after = _manifest(sandbox["root"])

    for rel in BYSTANDERS:
        assert rel in after, f"bystander destroyed: {rel}"
        assert after[rel] == before[rel], f"bystander modified: {rel}"


def test_dry_run_deletes_nothing(sandbox):
    before = _manifest(sandbox["root"])
    result = _run_nuke(sandbox, "--dry-run", stdin="")
    after = _manifest(sandbox["root"])
    assert result.returncode == 0, result.stderr
    assert after == before
    assert "would remove" in result.stdout


def test_unresolvable_state_dir_fails_loudly_and_deletes_nothing(sandbox):
    before = _manifest(sandbox["root"])
    env = dict(sandbox["env"])
    env["PATH"] = f'{sandbox["poison_path"]}:{env["PATH"]}'

    sandbox["env"] = env
    result = _run_nuke(sandbox, "--skip-confirm")
    after = _manifest(sandbox["root"])
    assert result.returncode != 0
    assert "NOTHING has been deleted" in result.stderr
    assert after == before


def test_tmux_socket_is_not_killed_by_default(sandbox):
    env = dict(sandbox["env"])
    env["CLOUDE_NUKE_TMUX_BIN"] = str(sandbox["tmux_stub"])
    sandbox["env"] = env
    result = _run_nuke(sandbox)
    assert "CANNOT DETERMINE" in result.stdout
    assert "kill-server" in result.stdout
    assert not sandbox["tmux_log"].exists(), "tmux was invoked despite the default"


def test_tmux_kill_is_opt_in_and_uses_the_configured_socket(sandbox):
    env = dict(sandbox["env"])
    env["CLOUDE_NUKE_KILL_TMUX"] = "true"
    env["CLOUDE_NUKE_TMUX_BIN"] = str(sandbox["tmux_stub"])
    sandbox["env"] = env
    _run_nuke(sandbox)
    argv = sandbox["tmux_log"].read_text()
    assert "-L carnivore kill-server" in argv, argv



MAIN_JS = REPO_ROOT / "macOS" / "tray-menu" / "actions" / "uninstall.js"
CONFIRM_JS = REPO_ROOT / "macOS" / "nuke-confirm.js"


def test_gui_nuke_requires_typing_the_word():
    main_src = MAIN_JS.read_text()
    assert "promptForNukeConfirmation" in main_src
    assert "'NUKE IT'" not in main_src
    assert "buttons: ['Cancel', 'NUKE IT']" not in main_src

    confirm_src = CONFIRM_JS.read_text()
    assert "input.value !== ${JSON.stringify(word)}" in confirm_src
    assert "word: 'NUKE'" in confirm_src
    assert "id=\"go\" disabled" in confirm_src
    assert "win.on('closed', () => finish(false))" in confirm_src


def test_gui_warning_names_what_is_destroyed_and_nothing_it_does_not():
    confirm_src = CONFIRM_JS.read_text()
    assert "refresh tokens" in confirm_src
    assert "Cloudflare" not in confirm_src
    assert "DNS records" not in confirm_src


def test_nuke_then_fresh_install_is_genuinely_fresh(sandbox):
    from src.core.setup_state import evaluate_setup_state

    _run_nuke(sandbox)

    state = evaluate_setup_state(sandbox["install"] / "config.json", None, None)
    assert not state.is_complete, "setup wizard would not engage after a nuke"
    assert state.status == "incomplete"

    for leftover in ("cloude.db", "refresh_tokens.db", "migration_trail.jsonl"):
        assert not (sandbox["state"] / leftover).exists()
    assert not (sandbox["install"] / "config.json").exists()
    assert not (sandbox["install"] / ".env").exists()
    assert not (sandbox["install"] / "venv").exists()




def _spawn(argv0: str, *args: str, cwd: Path | None = None) -> subprocess.Popen:
    return subprocess.Popen(
        ["bash", "-c", 'exec -a "$0 $*" sleep 60', argv0, *args], cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def _alive(proc: subprocess.Popen) -> bool:
    return proc.poll() is None


def test_default_nuke_stops_this_install_only_and_spares_agents(sandbox):
    home, install = sandbox["home"], sandbox["install"]
    support = home / "Library" / "Application Support" / "Carnivore Menubar"
    electron = install / "macOS/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron"
    survivors = [
        _spawn("claude", "--dangerously-skip-permissions", f'--mcp-config={{"args":["{support}/server/mcp.py"]}}'),
        _spawn("/bin/sh", "-c", f"cat >> '{home}/Library/Application Support/Carnivore/tmux_carnivore_x.pipe'"),
        _spawn(str(home / "Library/Application Support/Carnivore Menubar/server/venv/bin/python3"), "-m", "mcp_bridge"),
    ]
    victims = [_spawn(str(electron), "."), _spawn("python3", "-m", "src.main", cwd=install)]
    bystander_server = _spawn("python3", "-m", "src.main", cwd=sandbox["tmp"])
    try:
        time.sleep(0.5)
        assert all(_alive(p) for p in survivors + victims + [bystander_server])
        result = _run_nuke(sandbox)
        assert result.returncode == 0, result.stderr
        time.sleep(0.5)
        assert not [p for p in victims if _alive(p)], "the install's own electron and server must be stopped"
        assert all(_alive(p) for p in survivors), "an agent, MCP bridge or pipe reader was killed by name"
        assert _alive(bystander_server), "a src.main server of another folder was killed"
    finally:
        for proc in survivors + victims + [bystander_server]:
            proc.kill()
            proc.wait()


def _set_env_line(sbx: dict, key: str, value: str) -> None:
    env_file = sbx["install"] / ".env"
    lines = [ln for ln in env_file.read_text().splitlines() if not ln.startswith(f"{key}=")]
    env_file.write_text("\n".join(lines + [f"{key}={value}", ""]))


@pytest.mark.parametrize("value", ["{home}/carnivore-projects", "{home}/carnivore-projects/logs", '"~/carnivore-projects"', "{home}", '"~"', "{root}/elsewhere", "{home}/Library/Logs", "{root}"])
def test_log_directory_can_never_reach_projects_or_home(sandbox, value):
    home, root = sandbox["home"], sandbox["root"]
    _write(home / "carnivore-projects" / "logs" / "keep.py", "work")
    _write(root / "elsewhere" / "keep.txt", "other")
    _set_env_line(sandbox, "LOG_DIRECTORY", value.format(home=home, root=root))
    before = _manifest(root)
    result = _run_nuke(sandbox)
    after = _manifest(root)
    assert "was NOT deleted" in result.stdout, result.stdout
    for rel in ("home/carnivore-projects/logs/keep.py", "root_keep"):
        if rel in before:
            assert after.get(rel) == before[rel]
    assert after["home/carnivore-projects/logs/keep.py"] == before["home/carnivore-projects/logs/keep.py"]
    assert after["home/Documents/keep-me.txt"] == before["home/Documents/keep-me.txt"]
    assert after["elsewhere/keep.txt"] == before["elsewhere/keep.txt"]


def test_state_directory_inside_projects_is_refused(sandbox):
    home = sandbox["home"]
    _write(home / "carnivore-projects" / "p" / "work.py", "work")
    _set_env_line(sandbox, "CLOUDE_STATE_DIR", str(home / "carnivore-projects"))
    before = _manifest(sandbox["root"])
    result = _run_nuke(sandbox)
    assert result.returncode == 1 and "protected" in result.stderr, result.stderr
    assert _manifest(sandbox["root"]) == before


def test_a_socket_that_is_not_ours_is_never_killed(sandbox):
    env_text = (sandbox["install"] / ".env").read_text()
    for name in ("default", "sbx"):
        (sandbox["install"] / ".env").write_text(env_text)
        _write(sandbox["install"] / "config.json", json.dumps({"session": {"tmux_socket_name": name}}))
        sandbox["env"] = {**sandbox["env"], "CLOUDE_NUKE_TMUX_BIN": str(sandbox["tmux_stub"])}
        result = _run_nuke(sandbox, "--stop-tmux")
        assert "not one of ours" in result.stdout, result.stdout
        assert not sandbox["tmux_log"].exists()


def _system_env(sbx: dict) -> dict:
    root, stubs = sbx["root"], sbx["root"] / "stubs"
    log = root / "system-calls.log"
    app = root / "apps" / "Carnivore.app"
    exe = app / "Contents" / "MacOS" / "Carnivore"
    _write(exe, f'#!/bin/sh\necho "APP $*" >> "{log}"\n')
    exe.chmod(0o755)
    _write(app / "Contents" / "Info.plist", "<plist><dict><key>CFBundleShortVersionString</key>\n<string>1.16.4</string></dict></plist>\n")
    _write(sbx["home"] / "Library/Application Support/Carnivore Menubar/engine-host.json", '{"strategy": "launchd-agent"}')
    for name in ("launchctl", "tccutil", "sfltool"):
        _write(stubs / name, f'#!/bin/sh\necho "{name} $*" >> "{log}"\nexit 113\n')
        (stubs / name).chmod(0o755)
    env = {k: v for k, v in sbx["env"].items() if k not in ("CLOUDE_NUKE_HOME", "CLOUDE_NUKE_LAUNCHCTL")}
    env["CLOUDE_NUKE_APP"] = str(app)
    return env


def test_system_steps_run_only_with_the_flag(sandbox):
    sandbox["env"] = _system_env(sandbox)
    log = sandbox["root"] / "system-calls.log"
    env_text = (sandbox["install"] / ".env").read_text()
    bare = _run_nuke(sandbox, "--skip-confirm")
    calls = log.read_text() if log.exists() else ""
    assert bare.returncode == 0, bare.stderr
    assert "APP " not in calls and "tccutil" not in calls and "sfltool" not in calls, calls

    log.unlink(missing_ok=True)
    sandbox["env"] = _system_env(sandbox)
    packaged = sandbox["home"] / "Library/Application Support/Carnivore Menubar/server"
    shutil.move(str(sandbox["install"]), str(packaged))
    sandbox["install"] = packaged
    (packaged / ".env").write_text(env_text)
    _write(packaged / "config.json", json.dumps({"session": {"tmux_socket_name": "carnivore"}}))
    flagged = _run_nuke(sandbox, "--skip-confirm", "--system")
    calls = log.read_text().splitlines()
    assert "APP --unregister-login-service" in calls, (flagged.stdout, calls)
    tcc = [c for c in calls if c.startswith("tccutil ")]
    assert len(tcc) == 16 and all(c.split()[-1] in ("ai.carnivore.menubar", "com.cloudecode.menubar") for c in tcc), tcc
    assert not [c for c in calls if c.startswith("sfltool")], "a regular user must be told the sudo command, not have sfltool run"
    assert "sudo sfltool dumpbtm" in flagged.stdout
    boots = [c for c in calls if c.startswith("launchctl bootout") and c.endswith("ai.carnivore.menubar")]
    assert boots
    assert flagged.stdout.index("Removing application state") < flagged.stdout.index("Removing macOS LaunchAgent")


_LISTENER_SRC = (
    "import socket,sys,time\n"
    "s=socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
    "s.bind(('127.0.0.1', int(sys.argv[1]))); s.listen(5); print('up', flush=True)\n"
    "c=[]\n"
    "s.settimeout(60)\n"
    "try:\n"
    "    c.append(s.accept()[0]); time.sleep(60)\n"
    "except OSError:\n"
    "    pass\n"
)
_CLIENT_SRC = (
    "import socket,sys,time\n"
    "c=socket.create_connection(('127.0.0.1', int(sys.argv[1]))); print('up', flush=True); time.sleep(60)\n"
)


def test_port_step_never_stops_a_foreign_listener_or_a_connected_client(sandbox):
    listener = subprocess.Popen([sys.executable, "-c", _LISTENER_SRC, str(SANDBOX_PORT)], stdout=subprocess.PIPE, text=True)
    client = None
    try:
        assert listener.stdout.readline().strip() == "up"
        client = subprocess.Popen([sys.executable, "-c", _CLIENT_SRC, str(SANDBOX_PORT)], stdout=subprocess.PIPE, text=True)
        assert client.stdout.readline().strip() == "up"
        result = _run_nuke(sandbox, "--skip-confirm", allow_busy_port=True)
        assert result.returncode == 0, result.stderr
        assert _alive(listener), "a foreign listener on the install's port was killed"
        assert _alive(client), "a client connected to the install's port was killed"
        assert f"left alone: PID {listener.pid} listens on port {SANDBOX_PORT}" in result.stdout, result.stdout
    finally:
        for proc in (listener, client):
            if proc is not None:
                proc.kill()
                proc.wait()


@pytest.mark.parametrize("cwd_is_install", [False, True])
def test_port_step_stops_a_listener_only_by_identity_never_by_its_name(sandbox, cwd_is_install):
    cwd = sandbox["install"] if cwd_is_install else sandbox["tmp"]
    listener = subprocess.Popen([sys.executable, "-c", _LISTENER_SRC, str(SANDBOX_PORT), "-m", "src.main"], stdout=subprocess.PIPE, text=True, cwd=cwd)
    client = None
    try:
        assert listener.stdout.readline().strip() == "up"
        client = subprocess.Popen([sys.executable, "-c", _CLIENT_SRC, str(SANDBOX_PORT)], stdout=subprocess.PIPE, text=True)
        assert client.stdout.readline().strip() == "up"
        result = _run_nuke(sandbox, "--skip-confirm", allow_busy_port=True)
        assert result.returncode == 0, result.stderr
        time.sleep(0.5)
        assert _alive(client), "a client connected to the install's port was killed"
        if cwd_is_install:
            assert not _alive(listener), "this install's own engine was left running"
        else:
            assert _alive(listener), "a src.main listener of another folder was killed by its name"
            assert f"left alone: PID {listener.pid} listens on port {SANDBOX_PORT}" in result.stdout, result.stdout
    finally:
        for proc in (listener, client):
            if proc is not None:
                proc.kill()
                proc.wait()


def test_a_checkout_nuke_leaves_the_shared_per_user_folders_alone(sandbox):
    home, install = sandbox["home"], sandbox["install"]
    keep = [
        home / "Library/Application Support/Carnivore Menubar/server/marker",
        home / "Library/Application Support/Carnivore/carnivore.db",
        home / "Library/Application Support/cloude-code-menubar/x",
        home / "Library/LaunchAgents/ai.carnivore.menubar.plist",
        home / "Library/LaunchAgents/com.cloudecode.menubar.plist",
    ]
    for path in keep:
        _write(path, "live")
    env_file = install / ".env"
    env_file.write_text("\n".join(ln for ln in env_file.read_text().splitlines() if not ln.startswith("CLOUDE_STATE_DIR=")) + "\n")
    launchctl_log = sandbox["root"] / "launchctl.log"
    _write(sandbox["root"] / "stubs" / "launchctl", f'#!/bin/sh\necho "$*" >> "{launchctl_log}"\nexit 1\n')
    (sandbox["root"] / "stubs" / "launchctl").chmod(0o755)
    sandbox["env"] = {**{k: v for k, v in sandbox["env"].items() if k not in ("CLOUDE_NUKE_HOME", "CLOUDE_NUKE_LAUNCHCTL")}}
    result = _run_nuke(sandbox, "--skip-confirm")
    assert result.returncode == 0, result.stderr
    assert not (install / ".env").exists() and not (install / "venv").exists(), "the checkout's own files must still go"
    assert [str(p) for p in keep if not p.exists()] == [], "a shared per-user folder was deleted by a checkout's nuke"
    assert not launchctl_log.exists(), "a checkout's nuke touched launchd"


@pytest.fixture()
def real_app_in_process_env(monkeypatch):
    for name in ("CARNIVORE_PAYLOAD_PYTHON", "CLOUDE_PAYLOAD_PYTHON", "CLOUDECODE_PAYLOAD_PYTHON"):
        monkeypatch.setenv(name, "/Applications/Carnivore.app/Contents/Resources/payload/payload-arm64/python/bin/python3")
    for name in ("CARNIVORE_APP_BUNDLE", "CLOUDE_APP_BUNDLE", "CLOUDECODE_APP_BUNDLE", "CLOUDE_NUKE_APP"):
        monkeypatch.setenv(name, "/Applications/Carnivore.app")


def test_sandbox_env_cannot_reach_the_real_app(real_app_in_process_env, sandbox):
    env, root = sandbox["env"], str(sandbox["root"])
    for name in env:
        assert "PAYLOAD_PYTHON" not in name, name
    for name in ("CARNIVORE_APP_BUNDLE", "CLOUDE_NUKE_APP"):
        assert env[name].startswith(root), (name, env[name])
    assert not any(v.startswith("/Applications/Carnivore.app") for v in env.values()), "a sandbox variable still names the real app"
