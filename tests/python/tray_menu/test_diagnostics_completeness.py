
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_diagc_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_diagc_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

pytest.importorskip("fastapi")

# ruff: noqa: E402
from src.config import settings
from src.core.diagnostics import builder, launchd_facts, log_tails, tmux_facts
from src.core.server_log import breadcrumb, locate

FAKE_SECRET = "gh" + "p_" + "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5"


@pytest.fixture()
def home(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "home"
    root.mkdir()
    monkeypatch.setenv("HOME", str(root))
    monkeypatch.setattr(log_tails, "LEGACY_TMP_GLOB", str(tmp_path / "no-such-*.log"))
    monkeypatch.setattr(locate.own_log_path, "__wrapped__", locate.own_log_path.__wrapped__)
    locate.own_log_path.cache_clear()
    return root



def _fake_tmux(answers: dict):
    calls: list = []

    def run(argv):
        calls.append(argv)
        return answers.get((argv[2], argv[3]))

    run.calls = calls
    return run


def test_tmux_names_pid_and_dead_panes_on_both_sockets():
    run = _fake_tmux({
        ("carnivore", "list-sessions"): "carnivore_abc\nmy-own-session\n",
        ("carnivore", "display-message"): "4242\n",
        ("carnivore", "list-panes"): "carnivore_abc 1\nmy-own-session 1\n",
        ("cloude", "list-sessions"): "cloude_old\ncloude_dead\n",
        ("cloude", "display-message"): "777\n",
        ("cloude", "list-panes"): "cloude_old 0\ncloude_dead 1\n",
    })
    sockets = {s["socket"]: s for s in tmux_facts.collect(run, "tmux", "cloude")}
    assert set(sockets) == {"cloude", "carnivore"}
    assert sockets["carnivore"]["sessions"] == ["carnivore_abc"]
    assert sockets["carnivore"]["other_session_count"] == 1 and sockets["carnivore"]["server_pid"] == 4242
    assert sockets["carnivore"]["dead_pane_sessions"] == ["carnivore_abc"]
    assert sockets["cloude"]["sessions"] == ["cloude_dead", "cloude_old"]
    assert sockets["cloude"]["dead_pane_sessions"] == ["cloude_dead"]


def test_tmux_with_no_server_reads_null_and_only_read_commands_are_built():
    run = _fake_tmux({})
    for row in tmux_facts.collect(run, "tmux", None):
        assert row["sessions"] is None and row["server_pid"] is None
    assert run.calls and all(argv[1] == "-L" and argv[3] in tmux_facts.READ_ONLY_SUBCOMMANDS for argv in run.calls)
    with pytest.raises(ValueError):
        tmux_facts.tmux_argv("tmux", "x", "new-session")
    with pytest.raises(ValueError):
        tmux_facts.tmux_argv("tmux", "x", "start-server")



def test_tail_is_capped_to_whole_lines_and_redacted(tmp_path):
    log = tmp_path / "a.log"
    log.write_text("".join(f"line {i:05d} filler filler filler\n" for i in range(5000)) + f"token {FAKE_SECRET}\n")
    out = log_tails.collect("server", None, builder.redact_whole, str, specs=[log_tails.LogSpec("a", log, "t")],
                            per_log=2048)
    entry = out["logs"][0]
    assert entry["status"] == "ok" and entry["truncated"] and len(entry["text"].encode()) <= 2048
    assert FAKE_SECRET not in entry["text"] and entry["text"].startswith("line ")
    assert out["cap_bytes_per_log"] == 2048


def test_redactor_failure_drops_only_that_logs_text(tmp_path):
    bad, good = tmp_path / "bad.log", tmp_path / "good.log"
    bad.write_text("BOOM\n")
    good.write_text("fine\n")

    def redact(text: str) -> str:
        if "BOOM" in text:
            raise RuntimeError("detector down")
        return text

    specs = [log_tails.LogSpec("bad", bad, "t"), log_tails.LogSpec("good", good, "t")]
    logs = log_tails.collect("server", None, redact, str, specs=specs)["logs"]
    assert logs[0]["text"] is None and logs[0]["status"] == "dropped_redaction_failed"
    assert logs[1]["text"] == "fine\n"


def test_total_cap_skips_later_logs(tmp_path):
    specs = []
    for name in "abc":
        path = tmp_path / f"{name}.log"
        path.write_text("0123456789\n" * 10)
        specs.append(log_tails.LogSpec(name, path, "t"))
    logs = log_tails.collect("server", None, str, str, specs=specs, per_log=1000, total=100, min_tail=50)["logs"]
    assert [e["status"] for e in logs][-1] == "skipped_total_cap"


def test_a_symlinked_or_missing_log_is_refused_not_followed(tmp_path):
    target = tmp_path / "secret.txt"
    target.write_text("private")
    link = tmp_path / "server.log"
    link.symlink_to(target)
    assert log_tails.read_tail(link, 100)["status"] == "refused"
    assert log_tails.read_tail(tmp_path / "nope.log", 100)["status"] == "missing"


def test_a_private_key_body_cut_at_its_head_is_not_shipped(tmp_path):
    log = tmp_path / "k.log"
    key = "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAAB3NzaC1lZDI1NTE5AAAA\n-----END OPENSSH PRIVATE KEY-----\n"
    log.write_text("pad\n" * 10 + key + "after\n")
    start = log.read_text().index("AAAAB3")
    tail = log_tails.read_tail(log, len(log.read_text()) - start)
    assert "AAAAB3" not in tail["text"] and "after" in tail["text"]


def test_known_logs_cover_menubar_new_and_legacy_paths(home, tmp_path, monkeypatch):
    legacy = tmp_path / "carnivore-menubar.log"
    legacy.write_text("hi\n")
    monkeypatch.setattr(log_tails, "LEGACY_TMP_GLOB", str(tmp_path / "carnivore-menubar*.log"))
    names = {s.name for s in log_tails.known_logs("server", None)}
    assert {"menubar.log", "menubar-error.log", "carnivore-menubar.log", "startup-errors.log", "launchd.log"} <= names


def test_a_hard_linked_log_is_refused(tmp_path):
    original = tmp_path / "other.txt"
    original.write_text("private\n")
    planted = tmp_path / "carnivore-menubar.log"
    os.link(original, planted)
    assert log_tails.read_tail(planted, 100)["status"] == "refused"


def test_tmp_glob_filters_by_owner_before_the_cap(home, tmp_path, monkeypatch):
    victim = tmp_path / "victim.txt"
    victim.write_text("x\n")
    for n in range(5):
        (tmp_path / f"carnivore-menubar-a{n}.log").symlink_to(victim)
    (tmp_path / "carnivore-menubar-z1.log").write_text("one\n")
    (tmp_path / "carnivore-menubar-z2.log").write_text("two\n")
    monkeypatch.setattr(log_tails, "LEGACY_TMP_GLOB", str(tmp_path / "carnivore-menubar*.log"))
    names = {s.name for s in log_tails.known_logs("server", None)}
    assert {"carnivore-menubar-z1.log", "carnivore-menubar-z2.log"} <= names
    assert not any(n.startswith("carnivore-menubar-a") for n in names)


def test_worst_case_bundle_serializes_under_the_tray_buffer(home, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "state_dir_override", str(tmp_path / "st"))
    (tmp_path / "st").mkdir()
    monkeypatch.setattr(builder, "_run", lambda argv: None)
    nasty = ("\x01\"\\\n" * 9 + "\u4e2d\U0001f600\n") * 12000
    logs = home / "Library" / "Logs" / "Carnivore"
    logs.mkdir(parents=True)
    for name in log_tails.MENUBAR_LOG_NAMES:
        (logs / name).write_text(nasty * 2)
    for name in ("startup-errors.log",):
        target = locate.default_log_path().parent
        target.mkdir(parents=True, exist_ok=True)
        (target / name).write_text(nasty * 2)
    target = locate.default_log_path()
    target.write_text(nasty * 2)
    bundle = builder.build_bundle(mode="offline")
    size = len(json.dumps(bundle, indent=2, sort_keys=True))
    assert size < 8 * 1024 * 1024
    assert sum(1 for e in bundle["logs"]["logs"] if e["text"]) >= 2



def test_offline_diagnostics_reads_the_breadcrumb_and_server_mode_does_not(home, monkeypatch):
    dev = locate.dev_log_file()
    dev.parent.mkdir(parents=True)
    dev.write_text('{"event": "dev boot"}\n')
    state = home / "state"
    state.mkdir()
    crumb = {"path": str(dev), "pid": os.getpid(), "started_at": None, "writer": 1}
    (state / breadcrumb.BREADCRUMB_NAME).write_text(json.dumps(crumb))
    (state / breadcrumb.BREADCRUMB_NAME).chmod(0o600)
    seen = []
    real = breadcrumb.read_breadcrumb
    monkeypatch.setattr(breadcrumb, "read_breadcrumb", lambda *a, **k: seen.append(1) or real(*a, **k))
    offline = log_tails._server_log_specs("offline", state)
    assert seen and offline[0].path == dev and offline[0].source.startswith("breadcrumb:")
    seen.clear()
    log_tails._server_log_specs("server", state)
    assert seen == []


def test_a_poisoned_breadcrumb_falls_back_without_reading_the_named_file(home):
    state = home / "state"
    state.mkdir()
    (state / breadcrumb.BREADCRUMB_NAME).write_text(json.dumps({"path": "/etc/passwd", "pid": 1}))
    (state / breadcrumb.BREADCRUMB_NAME).chmod(0o600)
    specs = log_tails._server_log_specs("offline", state)
    assert all(str(s.path) != "/etc/passwd" and not s.source.startswith("breadcrumb") for s in specs)



def test_dev_log_path_is_accepted(home):
    dev = locate.dev_log_file()
    assert dev.parts[-4:] == ("Logs", "Carnivore", "dev", "server.log")
    assert locate.validated_log_path(str(dev)) == dev
    assert locate.validated_log_path(str(dev.parent / "other.log")) is None
    assert locate.validated_log_path(str(dev.parent / ".." / "dev" / "server.log")) is None


def test_dev_log_symlink_is_refused(home, tmp_path):
    real = tmp_path / "elsewhere"
    real.mkdir()
    (real / "server.log").write_text("x\n")
    dev = locate.dev_log_file()
    dev.parent.parent.mkdir(parents=True)
    dev.parent.symlink_to(real)
    assert locate.validated_log_path(str(dev)) is None
    dev.parent.unlink()
    dev.parent.mkdir()
    dev.symlink_to(real / "server.log")
    assert locate.validated_log_path(str(dev)) is None
    with pytest.raises(breadcrumb.BreadcrumbRefused):
        breadcrumb.open_log_nofollow(dev)



PRINT = (
    "gui/501/ai.carnivore.menubar = {\n\tactive count = 6\n\tpath = /Users/x/Library/LaunchAgents/a.plist\n"
    "\tstate = running\n\n\tprogram = /Applications/Carnivore.app/Contents/MacOS/Carnivore\n\targuments = {\n"
    "\t\t/Applications/Carnivore.app/Contents/MacOS/Carnivore\n\t}\n\n\tstdout path = /tmp/carnivore-menubar.log\n"
    "\tinherited environment = {\n\t\tSECRET_TOKEN => hunter2\n\t\tstate => nested\n\t}\n\n\truns = 3\n\tpid = 812\n"
    "\tlast exit code = (never exited)\n}\n"
)


def test_launchd_print_parse_keeps_only_top_level_fields_and_no_environment():
    parsed = launchd_facts.parse_launchctl_print(PRINT)
    assert parsed["state"] == "running" and parsed["pid"] == 812 and parsed["runs"] == 3
    assert parsed["last_exit_code"] == "(never exited)"
    assert "hunter2" not in json.dumps(parsed) and parsed["stdout_path"] == "/tmp/carnivore-menubar.log"


def test_launchd_summary_with_plist_and_job(home):
    import plistlib

    agents = home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    with open(agents / "ai.carnivore.menubar.plist", "wb") as handle:
        plistlib.dump({"Label": "ai.carnivore.menubar", "ProgramArguments": ["/Applications/Carnivore.app/x", "--a"],
                       "StandardOutPath": "/tmp/o.log", "EnvironmentVariables": {"TOKEN": "hunter2"}}, handle)
    seen = []
    out = launchd_facts.collect(lambda argv: seen.append(argv) or PRINT, uid=501)
    assert seen == [["launchctl", "print", "gui/501/ai.carnivore.menubar"]]
    assert out["plist"]["program"] == "/Applications/Carnivore.app/x" and out["loaded"] is True
    assert out["plist"]["stdout_path"] == "/tmp/o.log" and "hunter2" not in json.dumps(out)


def test_plist_must_be_a_small_regular_file(home):
    agents = home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    name = "ai.carnivore.menubar.plist"
    (agents / name).mkdir()
    assert launchd_facts.read_plist_summary(agents / name) == {"present": False}
    (agents / name).rmdir()
    (agents / name).write_bytes(b"x" * (launchd_facts.MAX_PLIST_BYTES + 1))
    assert launchd_facts.read_plist_summary(agents / name) == {"present": False}


def test_launchd_absent_job_and_plist_read_as_absent(home):
    out = launchd_facts.collect(lambda argv: None, uid=501)
    assert out["plist"] == {"present": False} and out["loaded"] is False and out["job"] == {}



def test_config_drops_non_allow_listed_keys_entirely(home, tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"session": {}, "mcp": {}, "totp_secret": "x", "weird_private_key": 1}))
    monkeypatch.setattr(settings, "auth_config_file", str(config))
    out = builder._config_keys()
    assert out == {"keys": ["mcp", "session"], "dropped_key_count": 2}
    assert "totp_secret" not in json.dumps(out)


def test_bundle_has_the_new_sections_and_home_is_shortened(home, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "state_dir_override", str(tmp_path / "st"))
    (tmp_path / "st").mkdir()
    monkeypatch.setattr(builder, "_run", lambda argv: None)
    log = home / "Library" / "Logs" / "Carnivore" / "menubar.log"
    log.parent.mkdir(parents=True)
    log.write_text(f"started in {home}/proj with {FAKE_SECRET}\n")
    bundle = builder.build_bundle(mode="offline")
    assert {"tmux", "launchd", "logs"} <= set(bundle)
    text = json.dumps(bundle)
    assert FAKE_SECRET not in text and str(home) not in text
    menubar = next(e for e in bundle["logs"]["logs"] if e["name"] == "menubar.log")
    assert "~/proj" in menubar["text"]
