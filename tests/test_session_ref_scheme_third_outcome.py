
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from src.core.message_model_serialize import (
    AGENT_SCHEME,
    OPAQUE_SCHEME,
    SESSION_REF_SCHEMES,
    UUID_SCHEME,
    session_ref_scheme,
)
from src.core.message_scheme_repair import (
    NEW_CHECK,
    OLD_CHECK,
    SchemeRepairError,
    backfill_opaque_scheme,
    check_allows_opaque,
    misclassified_rows,
    relax_scheme_check,
    repair_session_ref_schemes,
    stored_table_sql,
)
from tests.archive_fixture import make_state_dir, writable

SESSION_SCHEME_OWN: str = "uuid"

LIVE_UUID: str = "d1b0f992-cd9d-4221-8044-46c08aa8790c"

LIVE_OPAQUE_REFS = ("audit", "journal")




def test_a_well_formed_uuid_is_the_uuid_scheme() -> None:
    assert session_ref_scheme(LIVE_UUID) == UUID_SCHEME
    assert session_ref_scheme(LIVE_UUID.upper()) == UUID_SCHEME


def test_both_agent_prefixes_are_the_agent_scheme() -> None:
    assert session_ref_scheme("agent:a7b0a2e") == AGENT_SCHEME
    assert session_ref_scheme("agent-a00fdb4") == AGENT_SCHEME


@pytest.mark.parametrize("ref", LIVE_OPAQUE_REFS)
def test_a_filename_stem_is_neither_scheme(ref: str) -> None:
    assert session_ref_scheme(ref) == OPAQUE_SCHEME


@pytest.mark.parametrize(
    "ref",
    [
        "361a0641bc5347c88931d3e75029ca22",
        "{d1b0f992-cd9d-4221-8044-46c08aa8790c}",
        "urn:uuid:d1b0f992-cd9d-4221-8044-46c08aa8790c",
        "2463c265-2a86-ed4b-2fe4-44a6f2384b2",
        "9ab7b75e-7591-f7e4-3e46-01837d245b5d6",
        "2463c265-2a86-ed4b-2fe4-44a6f2384b2g",
        "d1b0f992-cd9d-4221-8044-46c08aa8790c\n",
        " d1b0f992-cd9d-4221-8044-46c08aa8790c",
        "",
    ],
)
def test_uuid_ish_but_malformed_is_opaque_not_uuid(ref: str) -> None:
    assert session_ref_scheme(ref) == OPAQUE_SCHEME


def test_the_classifier_can_only_answer_the_declared_schemes() -> None:
    assert set(SESSION_REF_SCHEMES) == {UUID_SCHEME, AGENT_SCHEME, OPAQUE_SCHEME}
    for ref in (LIVE_UUID, "agent:x", "audit", "", "zzz"):
        assert session_ref_scheme(ref) in SESSION_REF_SCHEMES




def _v19_shaped(tmp_path: Path) -> Path:
    state_dir = make_state_dir(tmp_path)
    with closing(writable(state_dir)) as conn:
        sql = stored_table_sql(conn, "message_transcripts")
        assert NEW_CHECK in sql, "fixture precondition: migration already ran"
        with conn:
            conn.execute("PRAGMA writable_schema=ON")
            conn.execute(
                "UPDATE sqlite_master SET sql = ? WHERE type='table' "
                "AND name='message_transcripts'",
                (sql.replace(NEW_CHECK, OLD_CHECK),),
            )
            conn.execute("PRAGMA writable_schema=RESET")
    with closing(writable(state_dir)) as conn:
        assert OLD_CHECK in stored_table_sql(conn, "message_transcripts")
    return state_dir


def test_the_old_check_really_refuses_the_new_value(tmp_path: Path) -> None:
    state_dir = _v19_shaped(tmp_path)
    with closing(writable(state_dir)) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO message_transcripts (source_ref, session_ref, "
                "session_ref_scheme, line_ending, has_trailing_newline, "
                "content_sha256, raw_byte_length, ingested_at) "
                "VALUES ('r','audit',?,'LF',1,'s',1,'t')",
                (OPAQUE_SCHEME,),
            )


def test_the_relax_is_idempotent_and_reports_it(tmp_path: Path) -> None:
    state_dir = _v19_shaped(tmp_path)
    with closing(writable(state_dir)) as conn:
        assert check_allows_opaque(conn) is False
        with conn:
            assert relax_scheme_check(conn) is True
        assert check_allows_opaque(conn) is True
        with conn:
            assert relax_scheme_check(conn) is False
        assert check_allows_opaque(conn) is True


def test_the_relaxed_check_is_still_enforced(tmp_path: Path) -> None:
    state_dir = _v19_shaped(tmp_path)
    with closing(writable(state_dir)) as conn:
        with conn:
            relax_scheme_check(conn)
        with conn:
            conn.execute(
                "INSERT INTO message_transcripts (source_ref, session_ref, "
                "session_ref_scheme, line_ending, has_trailing_newline, "
                "content_sha256, raw_byte_length, ingested_at) "
                "VALUES ('r','audit',?,'LF',1,'s',1,'t')",
                (OPAQUE_SCHEME,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO message_transcripts (source_ref, session_ref, "
                "session_ref_scheme, line_ending, has_trailing_newline, "
                "content_sha256, raw_byte_length, ingested_at) "
                "VALUES ('r2','x','not-a-scheme','LF',1,'s',1,'t')"
            )
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_an_unrecognised_check_refuses_rather_than_guessing(
    tmp_path: Path,
) -> None:
    state_dir = make_state_dir(tmp_path)
    with closing(writable(state_dir)) as conn:
        sql = stored_table_sql(conn, "message_transcripts")
        with conn:
            conn.execute("PRAGMA writable_schema=ON")
            conn.execute(
                "UPDATE sqlite_master SET sql = ? WHERE type='table' "
                "AND name='message_transcripts'",
                (sql.replace(NEW_CHECK, "CHECK (session_ref_scheme IN ('zz'))"),),
            )
            conn.execute("PRAGMA writable_schema=RESET")
        with pytest.raises(SchemeRepairError):
            relax_scheme_check(conn)




def _seed_mixed(conn: sqlite3.Connection) -> dict:
    ids = {}
    conn.execute(
        "INSERT OR IGNORE INTO message_hosts (id, machine_id, "
        "machine_id_scheme, display_name, first_seen_at) VALUES "
        "(1, 'm1', 'declared', 'h', '2026-01-01T00:00:00.000000Z')")
    conn.execute(
        "INSERT OR IGNORE INTO message_corpora (id, host_id, corpus_key, "
        "root_path, collected_at) VALUES "
        "(1, 1, 'c1', '/c', '2026-01-01T00:00:00.000000Z')")
    conn.execute(
        "INSERT OR IGNORE INTO message_projects (id, corpus_id, slug, "
        "first_seen_at) VALUES (1, 1, 'p1', '2026-01-01T00:00:00.000000Z')")
    rows = (
        ("audit", "audit", UUID_SCHEME),
        ("journal", "journal", UUID_SCHEME),
        ("real_uuid", LIVE_UUID, UUID_SCHEME),
        ("agent_colon", "agent:a7b0a2e", AGENT_SCHEME),
        ("agent_dash", "agent-a00fdb4", AGENT_SCHEME),
    )
    for name, ref, scheme in rows:
        cur = conn.execute(
            "INSERT INTO message_transcripts (source_ref, session_ref, "
            "session_ref_scheme, line_ending, has_trailing_newline, "
            "content_sha256, raw_byte_length, ingested_at, project_id) "
            "VALUES (?,?,?,'LF',1,?,1,'t',1)",
            (f"ref::{name}", ref, scheme, f"sha-{name}"),
        )
        ids[name] = int(cur.lastrowid)
    return ids


def test_the_backfill_moves_exactly_the_disagreeing_rows(
    tmp_path: Path,
) -> None:
    state_dir = _v19_shaped(tmp_path)
    with closing(writable(state_dir)) as conn:
        with conn:
            ids = _seed_mixed(conn)
        assert [r[0] for r in misclassified_rows(conn)] == [
            ids["audit"], ids["journal"]
        ]
        with conn:
            relax_scheme_check(conn)
            assert backfill_opaque_scheme(conn) == 2
        after = {
            int(r[0]): str(r[1])
            for r in conn.execute(
                "SELECT id, session_ref_scheme FROM message_transcripts"
            )
        }
    assert after[ids["audit"]] == OPAQUE_SCHEME
    assert after[ids["journal"]] == OPAQUE_SCHEME
    assert after[ids["real_uuid"]] == UUID_SCHEME
    assert after[ids["agent_colon"]] == AGENT_SCHEME
    assert after[ids["agent_dash"]] == AGENT_SCHEME


def test_the_backfill_is_idempotent(tmp_path: Path) -> None:
    state_dir = _v19_shaped(tmp_path)
    with closing(writable(state_dir)) as conn:
        with conn:
            _seed_mixed(conn)
        with conn:
            assert repair_session_ref_schemes(conn) == (True, 2)
        with conn:
            assert repair_session_ref_schemes(conn) == (False, 0)


def test_the_sessions_count_drops_by_exactly_the_rows_that_moved(
    tmp_path: Path,
) -> None:
    state_dir = _v19_shaped(tmp_path)
    with closing(writable(state_dir)) as conn:
        with conn:
            _seed_mixed(conn)
        sessions = (
            "SELECT COUNT(*) FROM message_transcripts "
            f"WHERE session_ref_scheme = '{SESSION_SCHEME_OWN}'"
        )
        total = "SELECT COUNT(*) FROM message_transcripts"
        before_sessions = conn.execute(sessions).fetchone()[0]
        before_total = conn.execute(total).fetchone()[0]
        with conn:
            _relaxed, moved = repair_session_ref_schemes(conn)
        assert before_sessions - conn.execute(sessions).fetchone()[0] == moved
        assert conn.execute(total).fetchone()[0] == before_total


def test_the_step_is_a_no_op_without_the_message_archive(
    tmp_path: Path,
) -> None:
    conn = sqlite3.connect(str(tmp_path / "bare.db"))
    with closing(conn):
        assert repair_session_ref_schemes(conn) == (False, 0)
        assert misclassified_rows(conn) == []
        assert check_allows_opaque(conn) is False
