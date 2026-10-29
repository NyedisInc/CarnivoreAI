
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import socket
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("update_proof", REPO / "macOS" / "scripts" / "update_proof.py")
up = importlib.util.module_from_spec(_spec)
sys.modules["update_proof"] = up
_spec.loader.exec_module(up)


def test_copy_env_and_argv_are_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDE_STATE_DIR", "/live/state")
    monkeypatch.setenv("CLOUDECODE_SESSION_ID", "live-session")
    monkeypatch.setenv("HOME", "/Users/live")
    env = up.copy_env(tmp_path, 51234, "http://127.0.0.1:9")
    assert "CLOUDE_STATE_DIR" not in env and "CLOUDECODE_SESSION_ID" not in env
    for key in ("HOME", "CFFIXED_USER_HOME", "TMUX_TMPDIR", "TMPDIR",
                "CARNIVORE_STATE_DIR", "CARNIVORE_SETTINGS_ENV_FILE"):
        assert Path(env[key]).is_relative_to(tmp_path), key
    assert env["CARNIVORE_LEDGER_KEEPALIVE"] == "0"
    assert env["PORT"] == "51234" and env["HOST"] == "127.0.0.1"
    argv = up.copy_argv(tmp_path / "Carnivore", tmp_path)
    assert "--use-mock-keychain" in argv
    assert f"--user-data-dir={up.paths_for(tmp_path)['user_data']}" in argv


def test_launch_uses_own_group_and_seed_keeps_port_off_live(tmp_path, monkeypatch):
    seen = {}

    class FakePopen:
        def __init__(self, argv, **kw):
            seen["argv"], seen["kw"] = argv, kw

    monkeypatch.setattr(up.subprocess, "Popen", FakePopen)
    app = tmp_path / "Carnivore.app"
    up.launch_copy(app, tmp_path, {"HOME": "x"})
    assert seen["kw"]["start_new_session"] is True and seen["kw"]["env"] == {"HOME": "x"}
    up.seed_home(tmp_path, 51234)
    server = up.paths_for(tmp_path)["server"]
    env_text = (server / ".env").read_text()
    assert "\nPORT=51234" in "\n" + env_text and "PORT=8000" not in env_text
    assert "HOST=127.0.0.1" in env_text and (server / ".env").stat().st_mode & 0o077 == 0
    assert '"enabled": false' in (server / "config.json").read_text()


def test_seed_turns_auto_update_on_only_when_asked(tmp_path, monkeypatch):
    monkeypatch.delenv("CARNIVORE_PROOF_AUTO_INSTALL", raising=False)
    up.seed_home(tmp_path / "plain", 51234)
    plain = json.loads((up.paths_for(tmp_path / "plain")["server"] / "config.json").read_text())
    assert plain.get("updates", {}).get("auto_update") is not True
    monkeypatch.setenv("CARNIVORE_PROOF_AUTO_INSTALL", "1")
    up.seed_home(tmp_path / "auto", 51234)
    auto = json.loads((up.paths_for(tmp_path / "auto")["server"] / "config.json").read_text())
    assert auto["updates"]["auto_update"] is True and auto["relay"] == {"enabled": False}


def test_build_timeout_sigterms_group_then_sigkills_only_after_grace(tmp_path):
    marker = tmp_path / "trap-ran"
    polite = ["python3", "-c",
              f"import signal,time,sys\nsignal.signal(signal.SIGTERM,lambda *a:(open({str(marker)!r},'w').close(),sys.exit(0)))\ntime.sleep(60)"]
    up.MAC_DIR = tmp_path
    try:
        up.run_build(polite, 1, grace_s=5)
    except TimeoutError as exc:
        assert "exited on SIGTERM" in str(exc)
    assert marker.exists()
    stubborn = ["python3", "-c", "import signal,time\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\ntime.sleep(60)"]
    t0 = time.time()
    try:
        up.run_build(stubborn, 1, grace_s=2)
    except TimeoutError as exc:
        assert "SIGKILL after the grace" in str(exc)
    assert time.time() - t0 >= 3


def test_preflight_refuses_a_busy_port(monkeypatch):
    monkeypatch.setattr(up, "run_text", lambda cmd: "")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        assert any("busy" in b for b in up.preflight(s.getsockname()[1]))
    assert any("live port" in b for b in up.preflight(up.LIVE_PORT))
    monkeypatch.setattr(up, "run_text", lambda cmd: "123\t0\tai.carnivore.menubar.ShipIt\n")
    assert any("ShipIt" in b for b in up.preflight(up.free_port()))


def test_main_exits_3_without_launching_when_gated(monkeypatch):
    monkeypatch.setattr(up, "build", lambda *a: (_ for _ in ()).throw(AssertionError("built")))
    monkeypatch.delenv("CARNIVORE_PROOF_ISOLATION_VERIFIED", raising=False)
    assert up.main([]) == 3
    monkeypatch.setenv("CARNIVORE_PROOF_ISOLATION_VERIFIED", "1")
    monkeypatch.setattr(up, "preflight", lambda port: ["port busy"])
    assert up.main([]) == 3


def test_fingerprint_compare_reports_a_change(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "run_text", lambda cmd: "")
    support = tmp_path / "Library" / "Application Support"
    (support / "Carnivore Menubar" / "server").mkdir(parents=True)
    (support / "Carnivore Menubar" / "server" / ".env").write_text("A=1")
    before = up.live_fingerprint(tmp_path)
    assert up.fingerprint_diff(before, up.live_fingerprint(tmp_path)) == []
    (support / "Carnivore Menubar" / "server" / ".env").write_text("A=22")
    os.utime(support / "Carnivore Menubar" / "server" / ".env", (1, 1))
    (support / "Carnivore" / "x").mkdir(parents=True)
    diff = up.fingerprint_diff(before, up.live_fingerprint(tmp_path))
    assert any(".env" in d for d in diff) and any("stateDir" in d for d in diff)


def test_fingerprint_ignores_live_churn_and_the_updates_own_shipit_job(tmp_path, monkeypatch):
    launchctl = ["-\t0\tai.carnivore.menubar"]
    monkeypatch.setattr(up, "run_text", lambda cmd: "\n".join(launchctl) if cmd[:1] == ["launchctl"] else "")
    state = tmp_path / "Library" / "Application Support" / "Carnivore"
    (state / "cplugs").mkdir(parents=True)
    before = up.live_fingerprint(tmp_path)
    os.utime(state / "cplugs", (1, 1))
    launchctl.append("75237\t0\tai.carnivore.menubar.ShipIt")
    assert up.fingerprint_diff(before, up.live_fingerprint(tmp_path)) == []
    launchctl.append("9\t0\tai.carnivore.other")
    (state / "cplugs" / "new").write_text("x")
    diff = up.fingerprint_diff(before, up.live_fingerprint(tmp_path))
    assert any("ai.carnivore.other" in d for d in diff) and any("cplugs/new" in d for d in diff)



LIVE_HOME = "/Users/live"
NODE_RUN = r"""
const os = require('os');
const { applyProofMarker } = require(process.argv[1]);
const calls = [];
const app = { setPath: (k, v) => calls.push(['setPath', k, v]),
              commandLine: { appendSwitch: (k, v) => calls.push(['switch', k, v === undefined ? null : v]) } };
const exe = process.argv[2];
const roots = [require('fs').realpathSync(process.argv[3])];
const uid = process.argv[4] === 'other' ? process.getuid() + 1 : process.getuid();
const r = applyProofMarker(app, { exePath: exe, roots, uid });
console.log(JSON.stringify({ r, home: os.homedir(), env: process.env, calls }));
"""


def _relaunch(work: Path, uid: str = "me") -> dict:
    if not shutil.which("node"):
        pytest.skip("node not installed: COULD NOT RUN, not a pass")
    exe = work / "Applications" / "Carnivore.app" / "Contents" / "MacOS" / "Carnivore"
    env = {"PATH": os.environ["PATH"], "HOME": LIVE_HOME}
    out = subprocess.run(["node", "-e", NODE_RUN, str(REPO / "macOS" / "proof-marker.js"),
                          str(exe), str(work), uid], env=env, capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _plist(purpose: str | None) -> str:
    key = f"<key>CarnivoreBuildPurpose</key>\n<string>{purpose}</string>\n" if purpose else ""
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>'
            f'<key>LSUIElement</key><true/>\n{key}</dict></plist>\n')


def _marker(work: Path, purpose: str | None = "update-proof") -> Path:
    contents = work / "Applications" / "Carnivore.app" / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "Info.plist").write_text(_plist(purpose))
    return up.write_marker(work, 51234)


def test_relaunch_under_marker_reads_proof_home_and_unsafe_markers_are_refused(tmp_path):
    work = tmp_path / "ok"
    marker = _marker(work)
    assert marker.parent == work / "Applications" and oct(marker.stat().st_mode & 0o777) == "0o600"
    body = json.loads(marker.read_text())
    assert all(Path(v).is_relative_to(work) for k, v in body.items() if k not in ("port", "host"))
    got = _relaunch(work)
    p = up.paths_for(work)
    assert got["r"]["applied"] is True and got["home"] == str(p["home"])
    assert got["env"]["TMUX_TMPDIR"] == str(p["tmux"]) and got["env"]["CARNIVORE_STATE_DIR"] == str(p["state"])
    assert ["setPath", "userData", str(p["user_data"])] in got["calls"]
    assert ["switch", "use-mock-keychain", None] in got["calls"]
    assert LIVE_HOME not in json.dumps({k: got["env"][k] for k in got["env"] if k != "PATH"})
    assert up.unhonored_strays([os.getpid()], work) == [os.getpid()]
    assert " applied" in (work / "Applications" / up.MARKER_LOG).read_text()

    def refused(name, mutate, uid="me"):
        w = tmp_path / name
        m = _marker(w)
        mutate(m, w)
        g = _relaunch(w, uid)
        assert g["r"]["applied"] is False and g["home"] == LIVE_HOME, (name, g["r"])

    def patch(key, val):
        def f(m, w):
            d = json.loads(m.read_text())
            d[key] = val
            m.write_text(json.dumps(d))
        return f

    def symlink(m, w):
        real = w / "real.json"
        m.rename(real)
        m.symlink_to(real)

    refused("outside", patch("home", LIVE_HOME))
    refused("dotdot", patch("state", str(tmp_path / "ok" / ".." / "elsewhere")))
    refused("sibling", patch("tmp", str(tmp_path / "sibling")))
    refused("badport", patch("port", 80))
    refused("extra", patch("evil", "x"))
    refused("notjson", lambda m, w: m.write_text("{"))
    refused("symlink", symlink)
    refused("worldw", lambda m, w: m.chmod(0o666))
    refused("otheruid", lambda m, w: None, uid="other")
    def final_symlink(m, w):
        outside = tmp_path / "outside-dir"
        outside.mkdir(exist_ok=True)
        link = w / "h"
        link.symlink_to(outside)
        d = json.loads(m.read_text())
        d["home"] = str(link)
        m.write_text(json.dumps(d))

    refused("finalsymlink", final_symlink)
    none = tmp_path / "none"
    (none / "Applications" / "Carnivore.app" / "Contents" / "MacOS").mkdir(parents=True)
    g = _relaunch(none)
    assert g["r"] == {"applied": False, "reason": None} and g["home"] == LIVE_HOME


def test_only_a_proof_build_reads_a_marker_and_a_bad_path_never_stops_startup(tmp_path):
    for name, purpose in (("release", "release"), ("keyless", None), ("vmtest", "vm-test")):
        work = tmp_path / name
        _marker(work, purpose)
        g = _relaunch(work)
        assert g["r"] == {"applied": False, "reason": None} and g["home"] == LIVE_HOME, (name, g["r"])
        assert not (work / "Applications" / up.MARKER_LOG).exists(), name
    work = tmp_path / "enotdir"
    m = _marker(work)
    (work / "afile").write_text("x")
    body = json.loads(m.read_text())
    body["tmp"] = str(work / "afile" / "y" / "z")
    m.write_text(json.dumps(body))
    g = _relaunch(work)
    assert g["r"]["applied"] in (True, False)


def test_the_home_directory_is_not_an_allowed_evidence_root(tmp_path):
    if not shutil.which("node"):
        pytest.skip("node not installed: COULD NOT RUN, not a pass")
    out = subprocess.run(["node", "-e", "const m=require(process.argv[1]);console.log('x')", str(REPO / "macOS" / "proof-marker.js")],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    src = (REPO / "macOS" / "proof-marker.js").read_text()
    assert "os.userInfo().homedir" not in src


def test_unhonored_strays_accepts_only_logged_pids(tmp_path):
    (tmp_path / "Applications").mkdir()
    (tmp_path / "Applications" / up.MARKER_LOG).write_text("42 2026-10-22T10:00:00.000Z applied\n43 t refused: x\n")
    assert up.unhonored_strays([42, 43, 44], tmp_path) == [43, 44]


def test_a_build_without_the_update_proof_purpose_is_gated(tmp_path):
    import plistlib
    app = tmp_path / "Carnivore.app"
    (app / "Contents").mkdir(parents=True)
    for purpose, ok in (("update-proof", True), ("release", False), ("vm-test", False), (None, False)):
        info = {"CFBundleShortVersionString": "1.0.0"}
        if purpose is not None:
            info["CarnivoreBuildPurpose"] = purpose
        (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps(info))
        if ok:
            up.require_proof_build(app)
        else:
            with pytest.raises(PermissionError):
                up.require_proof_build(app)
