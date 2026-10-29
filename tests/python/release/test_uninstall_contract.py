
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
UNINSTALL = "uninstall.sh"
OLD_UNINSTALL = "hosted/site/uninstall.sh"
NUKE = "nuke.sh"
COMMON = "scripts/upgrade_lib/upgrade_rollback_common.sh"
OLD_REF = "pre-R2-07"
OLD_DIR = REPO / "tests" / "fixtures" / "uninstall_contract_old"
BEGIN = "# --- uninstall contract: begin ---"
END = "# --- uninstall contract: end ---"
LABELS = ("ai.carnivore.menubar.engine", "ai.carnivore.menubar", "com.cloudecode.menubar")


def read(rel: str, ref: str | None = None) -> str:
    if ref is None:
        return (REPO / rel).read_text()
    return (OLD_DIR / Path(rel).name).read_text()


def code_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def contract_block(text: str) -> str:
    if BEGIN not in text or END not in text:
        return ""
    return text[text.index(BEGIN) : text.index(END) + len(END)]


def shellcheck_findings(path: Path) -> list[str]:
    exe = shutil.which("shellcheck")
    if exe is None:
        pytest.skip("shellcheck is not installed: the shellcheck check COULD NOT RUN (not a pass)")
    done = subprocess.run([exe, "-x", "-s", "bash", str(path)], cwd=path.parent, capture_output=True, text=True)
    if done.returncode == 2:
        raise AssertionError(f"shellcheck could not check {path}: {done.stderr}")
    return done.stdout.splitlines() if done.returncode else []


def contract_failures(files: dict[str, str], ref: str | None = None) -> list[str]:
    out: list[str] = []
    blocks = {name: contract_block(files[name]) for name in (UNINSTALL, NUKE)}
    for name, blk in blocks.items():
        if not blk:
            out.append(f"{name}: no uninstall contract block")
            continue
        for label in LABELS:
            if label not in blk:
                out.append(f"{name}: does not name {label}")
        if 'bootout "gui/$uid/$label"' not in blk:
            out.append(f"{name}: no launchctl bootout")
        if "--unregister-login-service" not in blk:
            out.append(f"{name}: never asks the app to unregister the login service")
    if blocks[UNINSTALL] != blocks[NUKE] or not blocks[UNINSTALL]:
        out.append("the two scripts do not carry the same contract block")
    unin = files[UNINSTALL]
    body = unin[unin.index("stop_everything() {") :] if "stop_everything() {" in unin else ""
    if "contract_unregister_login_service run" not in body or body.index("contract_unregister_login_service run") > body.index("  stop_app"):
        out.append(f"{UNINSTALL}: the login service is not unregistered before the app is stopped")
    nk = files[NUKE]
    call = nk.find('contract_unregister_login_service "$CONTRACT_MODE"')
    if call < 0 or call > nk.find("# Stop server (find by configured port"):
        out.append(f"{NUKE}: the login service is not unregistered before the server is stopped")
    for name in (UNINSTALL, NUKE):
        text = files[name]
        callers = [ln for ln in code_lines(text.replace(contract_block(text), "")) if "contract_stop_tmux" in ln]
        if not callers:
            out.append(f"{name}: never stops tmux, so the ask is not implemented")
    if "--stop-tmux" not in files[UNINSTALL] or 'STOP_TMUX" != 1' not in files[UNINSTALL]:
        out.append(f"{UNINSTALL}: the tmux stop is not behind --stop-tmux")
    if "--stop-tmux" not in files[NUKE] or 'KILL_TMUX" != "true"' not in files[NUKE]:
        out.append(f"{NUKE}: the tmux stop is not behind --stop-tmux or CLOUDE_NUKE_KILL_TMUX")
    for name in (UNINSTALL, NUKE):
        for ln in code_lines(files[name]):
            if re.search(r"\btmux\b[^|#]*kill-server", ln) and "-L" not in ln and "say " not in ln:
                out.append(f"{name}: a tmux kill-server without -L: {ln.strip()}")
            if re.search(r"pkill|killall", ln) and "src" in ln and "main" in ln:
                out.append(f"{name}: a pattern kill of src.main: {ln.strip()}")
    main_body = unin[unin.index("main() {") :] if "main() {" in unin else ""
    if "contract_reset_tcc run" not in main_body or main_body.index("contract_reset_tcc run") > main_body.index("remove_everything"):
        out.append(f"{UNINSTALL}: privacy rows are reset after the app is deleted, when tccutil can no longer find it")
    if "(MacOS|Frameworks)" not in unin:
        out.append(f"{UNINSTALL}: the app kill pattern also matches the bundled tmux server under Contents/Resources/payload")
    if "Cloude Code|Carnivore" in nk or "nuke_identity_pids" not in nk:
        out.append(f"{NUKE}: the process kill is a machine-wide name match (it takes the agents inside the sessions), not an identity match")
    for name in (UNINSTALL, NUKE):
        if "Records for UID" not in blocks[name]:
            out.append(f"{name}: Background Items is reported as clean without proof the list was readable")
    for name in (UNINSTALL, NUKE):
        for ln in code_lines(files[name]):
            if "tccutil" in ln and re.search(r"\bAll\b", ln):
                out.append(f"{name}: tccutil reset All: {ln.strip()}")
            if re.search(r"\btccutil reset\b", ln) and "contract_say" not in ln and not ln.rstrip().split("</dev/null")[0].rstrip().endswith('"$id"'):
                out.append(f"{name}: a tccutil reset that does not end in a bundle id: {ln.strip()}")
        blk = blocks[name]
        ids = re.search(r'CONTRACT_TCC_BUNDLE_IDS="([^"]*)"', blk)
        if not ids or set(ids.group(1).split()) != {"ai.carnivore.menubar", "com.cloudecode.menubar"}:
            out.append(f"{name}: tccutil bundle ids are not exactly ours")
    out += project_reach_findings(files)
    out += shipped_source_findings(files[NUKE], ref)
    py = files[COMMON]
    body = py[py.index("resolve_python() {") :] if "resolve_python() {" in py else ""
    body = body[: body.index("\n}\n") + 3] if body else ""
    if "payload" not in body or "python3 on PATH" not in body and "command -v python3" not in body:
        out.append("resolve_python has no payload fallback")
    elif body.index("payload") > body.index("command -v python3"):
        out.append("resolve_python tries PATH before the payload python")
    if "no python found" not in body:
        out.append("resolve_python has no clear message when none exists")
    return out


def project_reach_findings(files: dict[str, str]) -> list[str]:
    out: list[str] = []
    destructive = re.compile(r"\b(rm|rmdir|unlink)\b|find\b.*-delete|\bnuke_path\b|\bsafe_remove\b")
    for name in (UNINSTALL, NUKE):
        text = files[name]
        lines = code_lines(text)
        for ln in lines:
            if destructive.search(ln) and re.search(r"(?i)projects?\b|PROJECTS_DIR|DEFAULT_WORKING_DIR|working_dir", ln):
                out.append(f"{name}: a delete line can reach projects: {ln.strip()}")
    for name in (UNINSTALL, NUKE):
        for ln in code_lines(files[name]):
            if re.match(r'\s*"[^"]*(carnivore-projects|cloude-projects)[^"]*"\s*$', ln) or re.match(
                r'\s*for\s+(?!keep\b)\w+\s+in\s+.*(carnivore-projects|cloude-projects)', ln
            ):
                out.append(f"{name}: a delete list names a projects folder: {ln.strip()}")
    return out


def shipped_source_findings(nuke_text: str, ref: str | None = None) -> list[str]:
    sourced = set(re.findall(r'^\s*source\s+"\$\{SCRIPT_DIR\}/([^"]+)"', nuke_text, re.M))
    sourced |= set(re.findall(r"\$\{SCRIPT_DIR\}/(scripts/[A-Za-z0-9_./-]+\.sh)", nuke_text))
    out: list[str] = []
    if not sourced:
        return ["nuke.sh sources nothing, so the shipped-list check proves nothing"]
    pkg = json.loads(read("macOS/package.json", ref))
    extra = {r["to"] for r in pkg["build"]["extraResources"]}
    allow = set(re.findall(r"\{ name: '([^']+)', isDir: false", read("macOS/bootstrap.js", ref)))
    m = re.search(r"SHIP_PATHS=\(([^)]*)\)", read("scripts/deploy-mini.sh", ref))
    ship = set(m.group(1).split()) if m else set()
    for rel in sorted(sourced | {"scripts/resolve-port.sh"}):
        for where, have in (("extraResources", extra), ("RESYNC_ALLOWLIST", allow), ("SHIP_PATHS", ship)):
            if rel not in have:
                out.append(f"nuke.sh needs {rel}, which {where} lacks")
    return out


@pytest.fixture(scope="module")
def current() -> dict[str, str]:
    return {name: read(name) for name in (UNINSTALL, NUKE, COMMON)}


def test_contract_holds(current: dict[str, str]) -> None:
    assert contract_failures(current) == []


def test_shellcheck_clean_on_both_scripts(tmp_path: Path) -> None:
    planted = tmp_path / "planted_uninstall_probe.sh"
    planted.write_text('#!/bin/bash\nrm $1\n')
    assert shellcheck_findings(planted), "shellcheck found nothing in a planted `rm $1`: the check cannot go red"
    assert shellcheck_findings(REPO / UNINSTALL) == []
    assert shellcheck_findings(REPO / NUKE) == []


def test_old_scripts_fail_the_contract() -> None:
    old = {UNINSTALL: read(OLD_UNINSTALL, OLD_REF), **{name: read(name, OLD_REF) for name in (NUKE, COMMON)}}
    failures = contract_failures(old, OLD_REF)
    for expected in (
        "uninstall.sh: no uninstall contract block".replace("uninstall.sh", UNINSTALL),
        f"{NUKE}: no uninstall contract block",
        "resolve_python has no payload fallback",
    ):
        assert expected in failures, (expected, failures)
    assert any("delete line can reach projects" in f or "names a projects folder" in f for f in failures), failures
    assert any("nuke.sh needs scripts/resolve-port.sh" in f for f in failures), failures


def test_the_ask_flag_is_the_only_road_to_tmux() -> None:
    uninstall = read(UNINSTALL)
    assert re.search(r"--stop-tmux\) STOP_TMUX=1", uninstall)
    stop = uninstall[uninstall.index("stop_tmux() {") :]
    assert stop.index('"$STOP_TMUX" != 1') < stop.index("contract_stop_tmux"), "the tmux stop is not behind the ask"
    nuke = read(NUKE)
    assert re.search(r"--stop-tmux\)\s+CLOUDE_NUKE_KILL_TMUX=true", nuke)
    tmux_section = nuke[nuke.index("# 2. tmux sessions") :]
    assert tmux_section.index('"$KILL_TMUX" != "true"') < tmux_section.index("contract_stop_tmux")



STUB_NAMES = ("launchctl", "tccutil", "sfltool")


class Sandbox:

    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.apps = root / "apps"
        self.stubs = root / "stubs"
        self.log = root / "calls.log"
        for folder in (self.home, self.apps, self.stubs):
            folder.mkdir(parents=True)
        self.log.write_text("")
        for name in STUB_NAMES:
            self.stub(name, 'case "$1" in print) exit 113 ;; esac')
        (root / "block.sh").write_text(contract_block(read(UNINSTALL)))

    def stub(self, name: str, body: str = "", folder: Path | None = None) -> Path:
        path = (folder or self.stubs) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'#!/bin/bash\nprintf \'{name} %s\\n\' "$*" >> "{self.log}"\n{body}\n')
        path.chmod(0o755)
        return path

    def app(self, folder: Path, version: str, exit_code: int = 0) -> Path:
        self.stub("Carnivore", f"exit {exit_code}", folder / "Contents/MacOS")
        (folder / "Contents/Info.plist").write_text(
            f"<plist><dict>\n<key>CFBundleShortVersionString</key>\n<string>{version}</string>\n</dict></plist>\n"
        )
        self.stub("tmux", 'case "$*" in *list-sessions*) echo "no server running" >&2; exit 1 ;; esac', folder / "Contents/Resources/payload/payload-arm64/bin")
        return folder

    def job(self, registered: bool = True) -> None:
        path = self.home / "Library/Application Support/Carnivore Menubar/engine-host.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"strategy": "launchd-agent"}' if registered else '{"strategy": "detached"}')

    def run(self, call: str) -> subprocess.CompletedProcess[str]:
        env = {"HOME": str(self.home), "PATH": ":".join([str(self.stubs), *filter(None, [os.environ.get("AUDIT_SHIM_DIR")]), "/usr/bin", "/bin"]), "TMUX": ""}
        script = f'source "{self.root}/block.sh"; CONTRACT_APP="{self.apps}/Carnivore.app"; CONTRACT_HOME="{self.home}"; uname() {{ echo arm64; }}; {call}'
        return subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines()


@pytest.fixture()
def sbx(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


@pytest.mark.parametrize("where", ["apps/Carnivore.app", "home/Applications/Carnivore.app", "home/.Trash/Carnivore 2.app"])
def test_unregister_finds_the_bundle_wherever_it_is(sbx: Sandbox, where: str) -> None:
    sbx.app(sbx.root / where, "1.16.4")
    sbx.job()
    out = sbx.run("CONTRACT_SYSTEM=1; contract_unregister_login_service run")
    assert any(c == "Carnivore --unregister-login-service" for c in sbx.calls()), (out.stdout, sbx.calls())
    assert "the app unregistered it" in out.stdout


def test_unregister_finds_the_bundle_from_the_login_job_itself(sbx: Sandbox) -> None:
    odd = sbx.app(sbx.root / "elsewhere/Carnivore Copy.app", "1.16.4")
    sbx.stub("launchctl", f'case "$1" in print) echo "    program = {odd}/Contents/MacOS/Carnivore"; exit 0 ;; esac')
    sbx.run("CONTRACT_SYSTEM=1; contract_unregister_login_service run")
    assert "Carnivore --unregister-login-service" in sbx.calls()


def test_unregister_runs_the_app_only_when_it_can_help(sbx: Sandbox) -> None:
    sbx.app(sbx.apps / "Carnivore.app", "1.16.3")
    sbx.job()
    old = sbx.run("CONTRACT_SYSTEM=1; contract_unregister_login_service run")
    assert "Carnivore --unregister-login-service" not in sbx.calls() and "cannot unregister it" in old.stdout
    sbx.app(sbx.apps / "Carnivore.app", "1.16.4")
    sbx.job(registered=False)
    detached = sbx.run("CONTRACT_SYSTEM=1; contract_unregister_login_service run")
    assert "Carnivore --unregister-login-service" not in sbx.calls() and "no engine login job" in detached.stdout
    assert any(c.startswith("launchctl bootout") and c.endswith("ai.carnivore.menubar.engine") for c in sbx.calls())


def test_unregister_reports_a_failure_as_a_failure(sbx: Sandbox) -> None:
    sbx.app(sbx.apps / "Carnivore.app", "1.16.4", exit_code=1)
    sbx.job()
    out = sbx.run("CONTRACT_SYSTEM=1; contract_unregister_login_service run")
    assert "could NOT unregister" in out.stdout and "unregistered it" not in out.stdout.replace("could NOT unregister", "")


def test_background_items_is_never_read_as_a_regular_user(sbx: Sandbox) -> None:
    out = sbx.run("CONTRACT_SYSTEM=1; contract_record_background_items")
    assert not [c for c in sbx.calls() if c.startswith("sfltool")]
    assert "sudo sfltool dumpbtm" in out.stdout


def test_privacy_rows_end_in_exactly_one_of_our_ids_and_count_per_id(sbx: Sandbox) -> None:
    sbx.stub("tccutil", 'case "$3" in com.cloudecode.menubar) exit 70 ;; esac')
    out = sbx.run("CONTRACT_SYSTEM=1; contract_reset_tcc run")
    tcc = [c for c in sbx.calls() if c.startswith("tccutil ")]
    assert len(tcc) == 16 and {c.split()[-1] for c in tcc} == {"ai.carnivore.menubar", "com.cloudecode.menubar"}
    assert all(c.split()[1] == "reset" and "All" not in c.split() for c in tcc)
    assert "ai.carnivore.menubar: 8 reset, 0 refused" in out.stdout and "com.cloudecode.menubar: 0 reset, 8 refused" in out.stdout


def test_stop_tmux_uses_the_bundled_tmux_checks_the_result_and_refuses_foreign_sockets(sbx: Sandbox) -> None:
    sbx.app(sbx.apps / "Carnivore.app", "1.16.4")
    out = sbx.run("contract_stop_tmux run cloude")
    assert "tmux -L cloude kill-server" in sbx.calls() and "has no server left" in out.stdout
    before = len(sbx.calls())
    refused = sbx.run("contract_stop_tmux run default")
    assert len(sbx.calls()) == before and "not one of ours" in refused.stdout
    sbx.stub("tmux", "exit 0", sbx.apps / "Carnivore.app/Contents/Resources/payload/payload-arm64/bin")
    still = sbx.run("contract_stop_tmux run carnivore")
    assert "still has sessions" in still.stdout and "may still be running" in still.stdout


def test_text_pins_for_the_review_fixes() -> None:
    nuke = read(NUKE)
    assert "eval" not in "\n".join(code_lines(nuke)), "LOG_DIRECTORY must never be eval'd"
    assert '--system)       SYSTEM_STEPS=true' in nuke and '"$SYSTEM_STEPS" = "true"' in nuke
    assert nuke.index("contract_unregister_agents", nuke.index(END)) > nuke.index("# 7. This script's own log"), "the LaunchAgent bootout must come last (S4)"
    tray = (REPO / "macOS/tray-menu/actions/uninstall.js").read_text()
    assert "['--skip-confirm', '--system']" in tray and "showErrorBox('Carnivore: uninstall stopped'" in tray
    assert tray.index("!(await unregisterLoginService(ctx))") < tray.index("trashItem(bundle)")
    uninstall = read(UNINSTALL)
    assert "CONTRACT_SYSTEM=1\nCONTRACT_HOME=\"$HOME\"\nCONTRACT_LAUNCHCTL=launchctl" in uninstall, "N4: the three inputs are assigned, not inherited"


def test_every_review_finding_has_a_covering_test() -> None:
    covers = {
        "B1": "tests/test_nuke_sandbox.py::test_default_nuke_stops_this_install_only_and_spares_agents",
        "B3": "tests/test_nuke_sandbox.py::test_log_directory_can_never_reach_projects_or_home",
        "B3b": "tests/test_nuke_sandbox.py::test_state_directory_inside_projects_is_refused",
        "B4": "tests/python/release/test_uninstall_contract.py::test_unregister_finds_the_bundle_wherever_it_is",
        "S2": "tests/python/release/test_uninstall_contract.py::test_background_items_is_never_read_as_a_regular_user",
        "S3": "tests/python/release/test_uninstall_contract.py::test_unregister_runs_the_app_only_when_it_can_help",
        "S4": "tests/python/release/test_uninstall_contract.py::test_text_pins_for_the_review_fixes",
        "S5": "tests/test_nuke_sandbox.py::test_system_steps_run_only_with_the_flag",
        "S6": "tests/python/release/test_uninstall_contract.py::test_privacy_rows_end_in_exactly_one_of_our_ids_and_count_per_id",
        "S8": "tests/test_nuke_sandbox.py::test_a_socket_that_is_not_ours_is_never_killed",
    }
    for finding, ref in covers.items():
        path, name = ref.split("::")
        assert re.search(rf"^def {name}\b", (REPO / path).read_text(), re.M), (finding, ref)
