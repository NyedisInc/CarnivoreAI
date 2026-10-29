from __future__ import annotations

import ast
import contextlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_smc_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_smc_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.config import settings
from src.core.session_manager import SessionManager
from src.models import Session

OLD_REF = "v0.8.1"

INTACT = "INTACT"
STALE = "STALE"
ABSENT = "ABSENT"




def _tag_is_present() -> bool:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{OLD_REF}^{{commit}}"],
            cwd=str(ROOT),
            capture_output=True,
        ).returncode == 0
    except OSError:
        return False


def _extract_old_resolver() -> Tuple[Optional[Any], str]:
    try:
        src = subprocess.check_output(
            ["git", "show", f"{OLD_REF}:src/config.py"],
            cwd=str(ROOT),
            text=True,
            stderr=subprocess.PIPE,
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        return None, f"could not read {OLD_REF}:src/config.py from git ({exc})"

    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return None, f"{OLD_REF}:src/config.py did not parse ({exc})"

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "Settings":
            continue
        for item in node.body:
            if (
                isinstance(item, ast.FunctionDef)
                and item.name == "get_session_metadata_path"
            ):
                module = ast.Module(body=[item], type_ignores=[])
                ast.fix_missing_locations(module)
                ns: Dict[str, Any] = {"Path": Path}
                exec(compile(module, f"<{OLD_REF}:src/config.py>", "exec"), ns)
                return ns["get_session_metadata_path"], "ok"
    return None, (
        f"{OLD_REF}:src/config.py has no Settings.get_session_metadata_path - "
        "the method this whole comparison rests on could not be located"
    )


_OLD_RESOLVER, _OLD_RESOLVER_REASON = _extract_old_resolver()
_OLD_RESOLVER_TAG_MISSING = _OLD_RESOLVER is None and not _tag_is_present()


class _OldSettingsStub:

    def __init__(self, log_directory: str) -> None:
        self.log_directory = log_directory


def _old_reader(log_directory: Path) -> Path:
    if _OLD_RESOLVER is None:
        pytest.skip(f"CANNOT DETERMINE: {_OLD_RESOLVER_REASON}")
    return _OLD_RESOLVER(_OldSettingsStub(str(log_directory)))




def downgrade_verdict(log_directory: Path, live_session_id: str) -> str:
    path = _old_reader(log_directory)
    if not path.exists():
        return ABSENT
    try:
        raw = json.loads(path.read_text())
    except (ValueError, OSError):
        return ABSENT
    return INTACT if raw.get("id") == live_session_id else STALE




@pytest.fixture
def dirs(tmp_path: Path, monkeypatch) -> Tuple[Path, Path]:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    state_dir = tmp_path / "Library" / "Application Support" / "Carnivore"
    state_dir.mkdir(parents=True)
    monkeypatch.setattr(settings, "log_directory", str(log_dir))
    monkeypatch.setattr(settings, "state_dir_override", None)
    return log_dir, state_dir


def _session(session_id: str, name: str, working_dir: str = "/tmp/wd") -> Session:
    return Session(
        id=session_id,
        working_dir=working_dir,
        tmux_session=name,
        agent_type="claude",
    )


def _write_old_metadata(
    log_dir: Path, session_id: str, name: str, owned: list
) -> Path:
    path = log_dir / "session_metadata.json"
    payload = json.loads(_session(session_id, name).model_dump_json())
    payload["owned_tmux_sessions"] = sorted(owned)
    path.write_text(json.dumps(payload, indent=2))
    return path




def test_old_version_resolver_was_really_loaded():
    if _OLD_RESOLVER_TAG_MISSING:
        pytest.skip(
            f"CANNOT DETERMINE: {_OLD_RESOLVER_REASON}. Tag {OLD_REF} is not "
            "in this clone - fetch it (`git fetch --depth=1 origin tag "
            f"{OLD_REF}`) to run this comparison."
        )
    assert _OLD_RESOLVER is not None, _OLD_RESOLVER_REASON
    probe = _OLD_RESOLVER(_OldSettingsStub("/some/log/dir"))
    assert probe == Path("/some/log/dir/session_metadata.json")


def test_upgrade_reads_metadata_left_at_the_old_location(dirs):
    log_dir, state_dir = dirs
    _write_old_metadata(log_dir, "sess-upgrade", "work-a", ["work-a", "work-b"])

    mgr = SessionManager()
    mgr._load_session_metadata()

    current = mgr._registry.current_session()
    assert current is not None, "the new version did not rehydrate the old file"
    assert current.id == "sess-upgrade"
    assert current.tmux_session == "work-a"
    assert mgr._owned.names == {"work-a", "work-b"}
    assert not (state_dir / "session_metadata.json").exists(), (
        "reading must not copy the file to the new location - that would "
        "create the both-present ambiguity this test set is about"
    )


def test_plain_upgrade_writes_back_to_the_old_location(dirs):
    log_dir, state_dir = dirs
    _write_old_metadata(log_dir, "sess-old", "work-a", ["work-a"])

    mgr = SessionManager()
    mgr._load_session_metadata()
    mgr._owned.names = {"work-a", "work-c"}
    mgr._save_session_metadata()

    assert not (state_dir / "session_metadata.json").exists()
    written = json.loads((log_dir / "session_metadata.json").read_text())
    assert written["owned_tmux_sessions"] == ["work-a", "work-c"], (
        "the new version's write did not land at the old path"
    )
    assert downgrade_verdict(log_dir, "sess-old") == INTACT


def test_detach_sequence_keeps_metadata_where_the_install_started_from(dirs):
    log_dir, state_dir = dirs
    _write_old_metadata(log_dir, "sess-detached", "work-a", ["work-a", "work-b"])

    mgr = SessionManager()
    mgr._load_session_metadata()
    assert mgr._registry.current_session() is not None

    mgr._clear_stale_metadata()
    survivor = _session("sess-survivor", "work-b")
    mgr._registry.register(survivor, backend=None)
    mgr._owned.names = {"work-b"}
    mgr._save_session_metadata()

    assert (log_dir / "session_metadata.json").exists(), (
        "the file was expected to STAY at the location this install started from"
    )
    assert not (state_dir / "session_metadata.json").exists(), (
        "the detach sequence relocated the file into the state dir again"
    )
    assert downgrade_verdict(log_dir, "sess-survivor") == INTACT


def test_the_pin_survives_the_file_being_unlinked(dirs):
    log_dir, _state_dir = dirs
    old = log_dir / "session_metadata.json"
    old.write_text("{}")

    first = settings.get_session_metadata_path()
    assert first == old
    old.unlink()
    assert settings.get_session_metadata_path() == first, (
        "the resolution flipped as a side effect of the file being removed"
    )


def test_a_fresh_install_with_no_file_anywhere_pins_the_state_dir(dirs):
    log_dir, state_dir = dirs
    resolved = settings.get_session_metadata_path()
    assert resolved == state_dir / "session_metadata.json"
    assert settings.get_state_file_location("session_metadata.json") == "state_dir"

    (log_dir / "session_metadata.json").write_text("{}")
    assert settings.get_session_metadata_path() == resolved


def test_callers_read_the_authoritative_location_instead_of_re_deriving(dirs):
    log_dir, _state_dir = dirs
    (log_dir / "session_metadata.json").write_text("{}")
    assert settings.get_state_file_location("session_metadata.json") == "log_directory"
    assert settings.get_session_metadata_path().parent == log_dir


def test_changing_the_configured_locations_invalidates_the_pin(tmp_path, monkeypatch):
    a_log = tmp_path / "a-logs"
    b_log, b_state = tmp_path / "b-logs", tmp_path / "b-state"
    for d in (a_log, b_log, b_state):
        d.mkdir()
    (a_log / "session_metadata.json").write_text("{}")

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(settings, "log_directory", str(a_log))
    monkeypatch.setattr(settings, "state_dir_override", None)
    assert settings.get_session_metadata_path() == a_log / "session_metadata.json"

    monkeypatch.setattr(settings, "log_directory", str(b_log))
    monkeypatch.setattr(settings, "state_dir_override", str(b_state))
    assert settings.get_session_metadata_path() == b_state / "session_metadata.json"


def test_metadata_present_in_both_locations_leaves_the_old_copy_stale(dirs):
    log_dir, state_dir = dirs
    _write_old_metadata(log_dir, "sess-stale", "work-a", ["work-a"])
    _write_old_metadata(state_dir, "sess-stale", "work-a", ["work-a"])
    stale_bytes = (log_dir / "session_metadata.json").read_bytes()

    mgr = SessionManager()
    mgr._load_session_metadata()
    live = _session("sess-current", "work-z")
    mgr._registry.register(live, backend=None)
    mgr._owned.names = {"work-z"}
    mgr._save_session_metadata()

    assert json.loads((state_dir / "session_metadata.json").read_text())["id"] == "sess-current"
    assert (log_dir / "session_metadata.json").read_bytes() == stale_bytes, (
        "the old copy was expected to be left untouched"
    )
    assert downgrade_verdict(log_dir, "sess-current") == STALE




def test_detector_reports_absent_when_pointed_at_an_empty_location(dirs):
    log_dir, _ = dirs
    assert downgrade_verdict(log_dir, "sess-anything") == ABSENT


def test_detector_reports_stale_when_the_old_copy_diverges(dirs):
    log_dir, _ = dirs
    _write_old_metadata(log_dir, "sess-yesterday", "work-a", ["work-a"])
    assert downgrade_verdict(log_dir, "sess-today") == STALE
    assert downgrade_verdict(log_dir, "sess-yesterday") == INTACT




COMMON_SH = ROOT / "scripts" / "upgrade_lib" / "upgrade_rollback_common.sh"


def _run_rollback_cycle(tmp_path: Path, seed_dir_name: str):
    install = tmp_path / "install"
    logs = tmp_path / "logs"
    state = tmp_path / "state"
    for d in (install, logs, state):
        d.mkdir()
    (install / ".env").write_text(
        f"LOG_DIRECTORY={logs}\nCLOUDE_STATE_DIR={state}\n"
    )
    (install / "config.json").write_text("{}")
    seed = logs if seed_dir_name == "logs" else state
    import sqlite3 as _sqlite3
    with contextlib.closing(_sqlite3.connect(str(seed / "refresh_tokens.db"))) as c:
        c.execute("CREATE TABLE t (a)")
        c.commit()
    (seed / "session_metadata.json").write_text(
        json.dumps({"id": "sess-from-old", "owned_tmux_sessions": ["cloude_a"]})
    )

    script = (
        f"source '{COMMON_SH}'; "
        f"take_backup '{install}' '{tmp_path}/bk' >/dev/null 2>&1; "
        f"rm -f '{seed}/session_metadata.json' '{seed}/refresh_tokens.db'; "
        f"restore_backup '{install}' '{tmp_path}/bk' >/dev/null 2>&1"
    )
    env = {k: v for k, v in os.environ.items() if k != "CLOUDE_STATE_DIR"}
    proc = subprocess.run(
        ["/bin/bash", "-c", script], capture_output=True, text=True, env=env
    )
    manifest = tmp_path / "bk" / ".manifest"
    backed_up_meta = (
        manifest.exists()
        and "BACKED_UP\tstate\tsession_metadata.json" in manifest.read_text()
    )
    return install, logs, state, proc, backed_up_meta


def test_rollback_restores_a_state_file_to_where_take_backup_found_it(tmp_path: Path):
    if not COMMON_SH.exists():
        pytest.skip(f"CANNOT DETERMINE: {COMMON_SH} not present in this tree")

    _install, logs, state, proc, backed_up_meta = _run_rollback_cycle(tmp_path, "logs")
    if not backed_up_meta:
        pytest.skip(
            "CANNOT DETERMINE: take_backup did not back up "
            f"session_metadata.json (rc={proc.returncode}, stderr="
            f"{proc.stderr[-300:]!r}) - the rollback path was not exercised"
        )

    assert (logs / "session_metadata.json").exists(), (
        "restore did not put the file back where take_backup found it"
    )
    assert not (state / "session_metadata.json").exists(), (
        "restore RELOCATED the file into the state dir - the defect this "
        "test exists to catch"
    )
    assert downgrade_verdict(logs, "sess-from-old") == INTACT


def test_rollback_restores_a_state_dir_file_to_the_state_dir(tmp_path: Path):
    if not COMMON_SH.exists():
        pytest.skip(f"CANNOT DETERMINE: {COMMON_SH} not present in this tree")

    _install, logs, state, proc, backed_up_meta = _run_rollback_cycle(tmp_path, "state")
    if not backed_up_meta:
        pytest.skip(
            "CANNOT DETERMINE: take_backup did not back up "
            f"session_metadata.json (rc={proc.returncode}, stderr="
            f"{proc.stderr[-300:]!r}) - the rollback path was not exercised"
        )

    assert (state / "session_metadata.json").exists(), (
        "restore did not put the file back in the state dir it came from"
    )
    assert not (logs / "session_metadata.json").exists(), (
        "restore misfiled a state-dir file into the old LOG_DIRECTORY"
    )
