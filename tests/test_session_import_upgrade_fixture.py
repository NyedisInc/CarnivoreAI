
from __future__ import annotations

import json
import os
import sys
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.db import connect, db_path_for, get_meta
from src.core.db_migration import ensure_db_migrated
from src.core.db_models import (
    META_SESSION_IMPORT_UNATTRIBUTED,
    SESSION_ORIGIN_CREATED,
    SESSION_ORIGIN_OBSERVED,
)
from src.core.session_import import run_first_run_import
from src.core.session_store import list_sessions
from src.core.tmux_listing import TmuxListing

LIVE_NAMES = [
    "cloude_Test",
    "cloude_asd",
    "cloude_claude-config-sync-2",
    "cloude_scrolltest",
    "cloude_test pause",
    "cloude_fs2",
    "cloude_fstest",
    "cloude_ses_ec5bf2a3",
    "cloude_ses_3529a738",
]

PIPE_FILES = [
    "tmux_ses_3529a738.pipe",
    "tmux_ses_ec5bf2a3.pipe",
    "tmux_ext_cloude_ses_ec5bf2a3.pipe",
    "tmux_ext_cloude_console-msw4z3m5.pipe",
    "tmux_ext_cloude_fs2.pipe",
    "tmux_ext_cloude_fstest.pipe",
    "tmux_ext_cloude_Test.pipe",
    "tmux_ext_cloude_asd.pipe",
    "tmux_ext_cloude_claude-config-sync-2.pipe",
    "tmux_ext_cloude_scrolltest.pipe",
    "tmux_ext_cloude_test_pause.pipe",
]


@pytest.fixture()
def upgrade(tmp_path):
    ensure_db_migrated(tmp_path, 4, "0.8.2")
    logs = tmp_path / "logs"
    logs.mkdir()
    for name in PIPE_FILES:
        (logs / name).write_text("")
    with closing(connect(db_path_for(tmp_path))) as conn:
        yield conn, logs


FIXTURE_SOCKET = "cloudefixture"


def _run(conn, logs):
    return run_first_run_import(
        conn,
        socket=FIXTURE_SOCKET,
        listing=TmuxListing.answered(
            [
                {"name": n, "created_at_epoch": 1755000000 + i, "window_count": 1}
                for i, n in enumerate(LIVE_NAMES)
            ]
        ),
        owned_tmux_names=set(),
        log_dir=logs,
    )


def test_the_upgrade_fixture_leaves_ZERO_sessions_silently_external(upgrade):
    conn, logs = upgrade
    _run(conn, logs)
    rows = {r["tmux_name"]: r for r in list_sessions(conn)}
    assert len(rows) == 9

    records = json.loads(get_meta(conn, META_SESSION_IMPORT_UNATTRIBUTED))
    asked = {r["tmux_name"] for r in records}

    silently_external = [
        name
        for name, row in rows.items()
        if row["origin"] == SESSION_ORIGIN_OBSERVED and name not in asked
    ]
    assert silently_external == [], (
        "these sessions were written external and the user was never asked "
        f"about them: {silently_external}"
    )


def test_the_two_sessions_with_a_created_pipe_are_proved_OURS(upgrade):
    conn, logs = upgrade
    _run(conn, logs)
    rows = {r["tmux_name"]: r for r in list_sessions(conn)}
    ours = {n for n, r in rows.items() if r["origin"] == SESSION_ORIGIN_CREATED}
    assert ours == {"cloude_ses_3529a738", "cloude_ses_ec5bf2a3"}
    for name in ours:
        assert rows[name]["lifecycle_source"] == "import:created_pipe"


def test_the_readopted_session_is_decided_by_the_CREATED_pipe(upgrade):
    conn, logs = upgrade
    _run(conn, logs)
    row = [r for r in list_sessions(conn) if r["tmux_name"] == "cloude_ses_ec5bf2a3"][0]
    assert row["origin"] == SESSION_ORIGIN_CREATED
    assert row["lifecycle_source"] == "import:created_pipe"


def test_the_other_seven_are_ASKED_ABOUT_not_decided(upgrade):
    conn, logs = upgrade
    _run(conn, logs)
    records = json.loads(get_meta(conn, META_SESSION_IMPORT_UNATTRIBUTED))
    assert sorted(r["tmux_name"] for r in records) == sorted(
        [
            "cloude_Test",
            "cloude_asd",
            "cloude_claude-config-sync-2",
            "cloude_scrolltest",
            "cloude_test pause",
            "cloude_fs2",
            "cloude_fstest",
        ]
    )
    for rec in records:
        assert set(rec) == {"tmux_name", "epoch", "hints", "reason"}
        assert rec["reason"] == "no_admissible_evidence"


def test_what_the_OLD_import_did_to_the_same_fixture(upgrade):
    from src.core.session_store import observed_origin_for

    old = [observed_origin_for(n, set()) for n in LIVE_NAMES]
    assert old == [SESSION_ORIGIN_OBSERVED] * 9

    conn, logs = upgrade
    _run(conn, logs)
    rows = list_sessions(conn)
    new_observed = [r for r in rows if r["origin"] == SESSION_ORIGIN_OBSERVED]
    assert len(new_observed) == 7
    assert len(rows) - len(new_observed) == 2




def test_the_live_installs_re_run_promotes_nothing_and_asks_about_five(upgrade):
    from src.core.db import set_meta, transaction
    from src.core.db_models import (
        META_IMPORTED_FROM_JSON_RESULT,
        SESSION_ORIGIN_ADOPTED,
    )
    from src.core.session_identity import record_instance
    from src.core.session_import import (
        IMPORT_RERUN_COMPLETED,
        RESULT_KEY_SESSIONS_STAGE,
    )

    conn, logs = upgrade
    observed_names = [
        "cloude_Test",
        "cloude_asd",
        "cloude_claude-config-sync-2",
        "cloude_scrolltest",
        "cloude_test pause",
    ]
    with transaction(conn):
        for i, name in enumerate(LIVE_NAMES):
            record_instance(
                conn,
                socket=FIXTURE_SOCKET,
                name=name,
                epoch=1755000000 + i,
                origin=(
                    SESSION_ORIGIN_OBSERVED
                    if name in observed_names
                    else SESSION_ORIGIN_ADOPTED
                ),
                now="2026-08-18T18:41:13Z",
            )
        set_meta(
            conn,
            META_IMPORTED_FROM_JSON_RESULT,
            json.dumps({RESULT_KEY_SESSIONS_STAGE: "2026-08-18T18:41:13.152941Z"}),
        )

    result = _run(conn, logs)
    assert result.outcome == IMPORT_RERUN_COMPLETED
    assert result.promoted == 0

    rows = {r["tmux_name"]: r for r in list_sessions(conn)}
    assert len(rows) == 9, "the re-run must not INSERT a row"
    assert {n for n, r in rows.items() if r["origin"] == SESSION_ORIGIN_ADOPTED} == (
        set(LIVE_NAMES) - set(observed_names)
    )

    records = json.loads(get_meta(conn, META_SESSION_IMPORT_UNATTRIBUTED))
    assert sorted(r["tmux_name"] for r in records) == sorted(observed_names)


def test_POSITIVE_CONTROL_the_same_re_run_DOES_promote_when_evidence_exists(
    upgrade,
):
    from src.core.db import set_meta, transaction
    from src.core.db_models import (
        META_IMPORTED_FROM_JSON_RESULT,
        SESSION_ORIGIN_ADOPTED,
    )
    from src.core.session_identity import record_instance
    from src.core.session_import import (
        IMPORT_RERUN_COMPLETED,
        RESULT_KEY_SESSIONS_STAGE,
    )

    conn, logs = upgrade
    observed_names = [
        "cloude_Test",
        "cloude_asd",
        "cloude_claude-config-sync-2",
        "cloude_scrolltest",
        "cloude_ses_3529a738",
    ]
    with transaction(conn):
        for i, name in enumerate(LIVE_NAMES):
            record_instance(
                conn,
                socket=FIXTURE_SOCKET,
                name=name,
                epoch=1755000000 + i,
                origin=(
                    SESSION_ORIGIN_OBSERVED
                    if name in observed_names
                    else SESSION_ORIGIN_ADOPTED
                ),
                now="2026-08-18T18:41:13Z",
            )
        set_meta(
            conn,
            META_IMPORTED_FROM_JSON_RESULT,
            json.dumps({RESULT_KEY_SESSIONS_STAGE: "2026-08-18T18:41:13.152941Z"}),
        )

    result = _run(conn, logs)
    assert result.outcome == IMPORT_RERUN_COMPLETED
    assert result.promoted == 1

    rows = {r["tmux_name"]: r for r in list_sessions(conn)}
    assert rows["cloude_ses_3529a738"]["origin"] == SESSION_ORIGIN_CREATED
    assert rows["cloude_ses_3529a738"]["lifecycle_source"] == (
        "import:rerun:created_pipe"
    )

    records = json.loads(get_meta(conn, META_SESSION_IMPORT_UNATTRIBUTED))
    assert sorted(r["tmux_name"] for r in records) == sorted(
        set(observed_names) - {"cloude_ses_3529a738"}
    )
