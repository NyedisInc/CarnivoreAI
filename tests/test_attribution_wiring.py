
from __future__ import annotations

import os
import sys
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")

from src.core.db import connect, db_path_for  # noqa: E402
from src.core.db_models import (  # noqa: E402
    SESSION_ATTRIBUTION_DERIVED_DEEPEST,
    SESSION_ATTRIBUTION_NONE,
    SESSION_ATTRIBUTION_UNKNOWN,
    SESSION_ORIGIN_OBSERVED,
)
from src.core.session_attribution import backfill_attribution  # noqa: E402
from src.core.session_identity import record_instance  # noqa: E402
from src.core.session_store import needs_attention  # noqa: E402
from tests.s7_helpers import (  # noqa: E402
    TEST_SOCKET,
    insert_project,
    migrated_connection,
    session_row,
)


@pytest.fixture()
def conn(tmp_path):
    with closing(migrated_connection(tmp_path)):
        pass
    with closing(connect(db_path_for(tmp_path))) as connection:
        yield connection




def _seed_nine_and_nine(conn):
    home = str(Path.home())
    projects = {
        f"{home}": "console-msw4z3m5",
        f"{home}/Development": "Development",
        f"{home}/Development/CloudeCode": "CloudeCode",
        f"{home}/Development/ai-setup": "ai-setup",
        f"{home}/Development/claude-config-sync": "claude-config-sync-2",
        f"{home}/Development/scrolltest": "fs2",
        f"{home}/Development/ses_ec5bf2a3": "test pause",
        f"{home}/Development/ses_8704e610": "asd",
        f"{home}/Development/ses_c3737fbe": "Test",
    }
    ids = {}
    for root, name in projects.items():
        raw = root.replace(home, "~", 1) if root != home else home
        ids[root] = insert_project(conn, root, name, raw_path=raw)

    dirs = {
        "cloude_Test": f"{home}/Development/ses_c3737fbe",
        "cloude_asd": f"{home}/Development/ses_8704e610",
        "cloude_claude-config-sync-2": f"{home}/Development/claude-config-sync",
        "cloude_console-msw4z3m5": home,
        "cloude_fs2": f"{home}/Development/scrolltest",
        "cloude_fstest": f"{home}/Development/CloudeCode/src/core",
        "cloude_scrolltest": "~/Development/scrolltest",
        "cloude_ses_ec5bf2a3": f"{home}/Development/ses_ec5bf2a3",
        "cloude_test pause": "/opt/somewhere-else",
    }
    for index, (name, working_dir) in enumerate(dirs.items(), start=1):
        record_instance(
            conn, socket=TEST_SOCKET, name=name, epoch=1786900000 + index,
            origin=SESSION_ORIGIN_OBSERVED,
            project_attribution=SESSION_ATTRIBUTION_UNKNOWN,
            working_dir=working_dir,
        )
    return ids, dirs


def test_a_realistic_nine_and_nine_fixture_actually_resolves(conn):
    ids, _dirs = _seed_nine_and_nine(conn)
    home = str(Path.home())

    result = backfill_attribution(conn)

    assert result.considered == 9
    assert result.attributed_project == 8
    assert result.attributed_none == 1
    assert result.still_unknown == 0, (
        "a session defaulted to unknown over a fully-probed fixture, "
        "which is the exact state the live database was already in"
    )

    assert session_row(conn, "cloude_fstest")["project_id"] == (
        ids[f"{home}/Development/CloudeCode"])
    assert session_row(conn, "cloude_scrolltest")["project_id"] == (
        ids[f"{home}/Development/scrolltest"])
    assert session_row(conn, "cloude_console-msw4z3m5")["project_id"] == (
        ids[home])
    outside = session_row(conn, "cloude_test pause")
    assert outside["project_attribution"] == SESSION_ATTRIBUTION_NONE
    assert outside["project_id"] is None

    unknowns = [
        row for row in needs_attention(conn)
        if row["project_attribution"] == SESSION_ATTRIBUTION_UNKNOWN
    ]
    assert unknowns == []


def test_the_backfill_probes_when_the_row_has_no_stored_directory(conn):
    home = str(Path.home())
    project_id = insert_project(conn, f"{home}/Development/CloudeCode", "CC")
    record_instance(
        conn, socket=TEST_SOCKET, name="cloude_needsprobe", epoch=99,
        origin=SESSION_ORIGIN_OBSERVED,
        project_attribution=SESSION_ATTRIBUTION_UNKNOWN,
    )
    assert session_row(conn, "cloude_needsprobe")["working_dir"] is None

    probed = {"cloude_needsprobe": f"{home}/Development/CloudeCode/src"}
    result = backfill_attribution(
        conn, working_dir_probe=lambda name: probed.get(name)
    )

    assert result.attributed_project == 1
    row = session_row(conn, "cloude_needsprobe")
    assert row["project_id"] == project_id
    assert row["working_dir"] == probed["cloude_needsprobe"], (
        "the probed directory must be stored so the next pass needs no "
        "tmux call"
    )


def test_the_backfill_never_writes_unknown_over_anything(conn):
    record_instance(
        conn, socket=TEST_SOCKET, name="cloude_blind", epoch=7,
        origin=SESSION_ORIGIN_OBSERVED,
        project_attribution=SESSION_ATTRIBUTION_UNKNOWN,
        now="2026-01-01T00:00:00Z",
    )
    before = session_row(conn, "cloude_blind")

    result = backfill_attribution(
        conn, working_dir_probe=lambda _name: None,
        now="2026-12-12T00:00:00Z",
    )

    assert result.still_unknown == 1
    assert result.written == 0
    after = session_row(conn, "cloude_blind")
    assert after["updated_at"] == before["updated_at"]
    assert after["project_attribution"] == SESSION_ATTRIBUTION_UNKNOWN


def test_the_backfill_never_overwrites_a_measured_attribution(conn):
    home = str(Path.home())
    insert_project(conn, f"{home}/Development", "Development")
    record_instance(
        conn, socket=TEST_SOCKET, name="cloude_settled", epoch=8,
        origin=SESSION_ORIGIN_OBSERVED,
        project_attribution=SESSION_ATTRIBUTION_NONE,
        working_dir=f"{home}/Development/thing",
    )
    result = backfill_attribution(conn)
    assert result.considered == 0
    row = session_row(conn, "cloude_settled")
    assert row["project_attribution"] == SESSION_ATTRIBUTION_NONE
    assert row["project_id"] is None


def test_the_probe_returns_none_rather_than_a_home_directory_guess():
    from src.core.tmux_session_cwd import probe_session_working_dir
    from tests.socket_guard import TEST_SOCKET_NAME

    assert probe_session_working_dir("", socket="nosuchsocket") is None
    assert probe_session_working_dir(
        "definitely-not-a-session-s7", socket=TEST_SOCKET_NAME
    ) is None


@pytest.fixture()
def tmux_session(tmp_path):
    import shutil
    import subprocess

    from tests.socket_guard import TEST_SOCKET_NAME

    if not shutil.which("tmux"):
        pytest.skip("tmux is not installed on this machine")

    created = []

    def _make(name: str, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["tmux", "-L", TEST_SOCKET_NAME, "new-session", "-d",
             "-s", name, "-c", str(directory)],
            check=True, capture_output=True,
        )
        created.append(name)

    yield _make

    for name in created:
        subprocess.run(
            ["tmux", "-L", TEST_SOCKET_NAME, "kill-session", "-t", f"={name}"],
            check=False, capture_output=True,
        )


def test_the_probe_reads_a_real_tmux_sessions_directory(tmux_session, tmp_path):
    from src.core.tmux_session_cwd import probe_session_working_dir
    from tests.socket_guard import TEST_SOCKET_NAME

    workdir = tmp_path / "s7probe-dir"
    tmux_session("s7probe", workdir)

    answer = probe_session_working_dir("s7probe", socket=TEST_SOCKET_NAME)
    assert answer is not None, "tmux answered but the probe returned None"
    assert Path(answer).name == "s7probe-dir", answer


def test_the_probe_will_not_prefix_match_a_different_session(
    tmux_session, tmp_path
):
    from src.core.tmux_session_cwd import probe_session_working_dir
    from tests.socket_guard import TEST_SOCKET_NAME

    tmux_session("s7prefix2", tmp_path / "wrong-session-dir")

    answer = probe_session_working_dir("s7prefix", socket=TEST_SOCKET_NAME)
    assert answer is None, (
        "the probe prefix-matched a different session and returned "
        f"{answer!r}. tmux targets are patterns unless prefixed with '='"
    )


def test_a_failed_probe_returns_none_and_not_a_directory(
    tmux_session, tmp_path
):
    from src.core.tmux_session_cwd import probe_session_working_dir
    from tests.socket_guard import TEST_SOCKET_NAME

    tmux_session("s7alive", tmp_path / "alive")

    answer = probe_session_working_dir("s7absent", socket=TEST_SOCKET_NAME)
    assert answer is None
    assert answer != str(Path.home()), (
        "the probe fell back to the home directory. His projects table "
        "has a project rooted at the home directory, so that guess would "
        "attribute every failed probe to a real project"
    )


def test_a_name_carrying_a_tmux_target_separator_is_refused(
    tmux_session, tmp_path
):
    from src.core.tmux_session_cwd import probe_session_working_dir
    from tests.socket_guard import TEST_SOCKET_NAME

    tmux_session("s7sep", tmp_path / "some-other-sessions-dir")

    answer = probe_session_working_dir("s7sep:0", socket=TEST_SOCKET_NAME)
    assert answer is None, (
        "a name containing a tmux target separator was formatted into a "
        f"target and resolved to another session, returning {answer!r}"
    )


def test_a_probe_that_times_out_answers_none_rather_than_guessing(
    tmux_session, tmp_path
):
    from src.core.tmux_session_cwd import probe_session_working_dir
    from tests.socket_guard import TEST_SOCKET_NAME

    tmux_session("s7timeout", tmp_path / "timeout-dir")

    answer = probe_session_working_dir(
        "s7timeout", socket=TEST_SOCKET_NAME, timeout=0.000001
    )
    assert answer is None, (
        f"a timed-out probe returned {answer!r} instead of admitting it "
        "could not determine the working directory"
    )
    assert answer != str(Path.home())


def test_the_import_call_site_actually_passes_a_working_dir_probe():
    import ast

    tree = ast.parse((ROOT / "src" / "core" / "boot" / "first_run.py").read_text())
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "run_first_run_import"
    ]
    assert calls, "run_first_run_import is not called from the first-run boot step at all"
    for call in calls:
        probe = [kw for kw in call.keywords if kw.arg == "working_dir_probe"]
        assert probe, (
            "run_first_run_import is called without working_dir_probe. "
            "That is the live bug: every session imports with working_dir "
            "NULL and project_attribution 'unknown'"
        )
        value = probe[0].value
        assert not (isinstance(value, ast.Constant) and value.value is None), (
            "working_dir_probe is passed as a literal None, which is the "
            "same as not passing it"
        )


def test_the_import_attributes_nothing_without_a_probe_and_resolves_with_one(
    conn, tmp_path
):
    from src.core.session_import import run_first_run_import
    from tests.s7_helpers import listing_of, listing_row

    home = str(Path.home())
    insert_project(conn, f"{home}/Development/CloudeCode", "CloudeCode")
    listing = listing_of([listing_row("cloude_cc", 4242)])

    result = run_first_run_import(
        conn, listing=listing, socket=TEST_SOCKET,
        working_dir_probe=None,
    )
    assert result.sessions_imported == 1
    blind = session_row(conn, "cloude_cc")
    assert blind["project_attribution"] == SESSION_ATTRIBUTION_UNKNOWN
    assert blind["project_id"] is None
    assert blind["working_dir"] is None

    repaired = backfill_attribution(
        conn,
        working_dir_probe=lambda _n: f"{home}/Development/CloudeCode/src",
    )
    assert repaired.attributed_project == 1
    seeing = session_row(conn, "cloude_cc")
    assert seeing["project_attribution"] == SESSION_ATTRIBUTION_DERIVED_DEEPEST
    assert seeing["project_id"] is not None
