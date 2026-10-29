
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from typing import Callable, Dict, List

import structlog

from src.core.db import (
    column_exists,
    ensure_install_id,
    get_meta,
    set_meta,
    table_exists,
)
from src.core.db_models import (
    DDL_SESSIONS_CLAUDE_UUID_PLAIN_INDEX_DROP,
    DDL_SESSIONS_CLAUDE_UUID_UNIQUE_INDEX,
    DDL_V1,
    DDL_V2,
    DDL_V3,
    DDL_V4,
    DDL_V5,
    DDL_V6,
    DDL_V7,
    DDL_V8,
    DDL_V14,
    DDL_V15_TRANSCRIPT_ARCHIVES_GROWTH_KIND,
    DDL_V15_TRANSCRIPT_ARCHIVES_PROJECT_ID,
    DDL_V15_TRANSCRIPT_ARCHIVES_PROJECT_INDEX,
    DDL_V15_TRANSCRIPT_ARCHIVES_PROJECT_ROOTED_AT,
    DDL_V15_TRANSCRIPT_ARCHIVES_PROJECT_ROOTED_BY,
    DDL_V15_TRANSCRIPT_ARCHIVES_SUPERSEDED_BY,
    DDL_V15_TRANSCRIPT_ARCHIVES_SUPERSEDED_BY_INDEX,
    DDL_V15_TRANSCRIPT_ROOT_DECISIONS_PROJECT_ID,
    DDL_V22_TRANSCRIPT_ARCHIVES_CONTENT_SHA_INDEX,
    DDL_V22_TRANSCRIPT_ARCHIVES_DEDUPE_KIND,
    DDL_V23_SESSIONS_LAST_WORK_AT,
    DDL_V24,
    DDL_V25_SESSIONS_KIND,
    DDL_V25_SESSIONS_KIND_BACKFILL,
    DDL_V26_SESSIONS_NOTIFICATION_POLICY_GENERATION,
    DDL_V26_SESSIONS_NOTIFICATIONS_MUTED,
    DDL_V27,
    DDL_V28,
    DDL_V30,
    META_CREATED_AT,
    META_PROJECT_TOMBSTONES_LEGACY_GAP,
    META_PROJECT_TOMBSTONES_SINCE,
    META_SCHEMA_VERSION,
    META_SESSIONS_CLAUDE_UUID_DUPLICATES,
)
from src.core.archive_overlay_ddl import DDL_V19
from src.core.message_activity import install_transcript_activity
from src.core.message_scheme_repair import repair_session_ref_schemes
from src.core.browser_sessions_ddl import DDL_V32
from src.core.session_group_style_ddl import DDL_V33
from src.core.layouts.ddl import DDL_V34
from src.core.blueprints_ddl import DDL_V35
from src.core.layouts.style_ddl import DDL_V36
from src.core.layouts.broadcast_ddl import DDL_V37
from src.core.item_settings_ddl import DDL_V38
from src.core.session_group_icon_ddl import DDL_V39, ICON_COLUMN
from src.core.federation.ddl import DDL_V43, apply_v44
from src.core.federation.ddl_peer_sessions import DDL_V45
from src.core.conversation_index.ddl import DDL_V46, PARENT_INDEX_V46, apply_v48
from src.core.lineage.ddl import apply_v49
from src.core.app_alerts.ddl import apply_v50
from src.core.db_ddl.pipeline import apply_v51, apply_v53
from src.core.db_ddl.search_index import apply_v52
from src.core.transcript_manifest.ddl import apply_v54
from src.core.db_ddl.search_index import apply_v55
from src.core.hosts.ddl import apply_v40, apply_v96
from src.core.launch_profiles.ddl import apply_v56
from src.core.crosstalk.ddl import apply_v57, apply_v94
from src.core.messaging.ddl import apply_v73, apply_v92
from src.core.descriptions.ddl import apply_v74
from src.core.companies.ddl import apply_v58, apply_v72
from src.core.project_pack.ddl import apply_v75
from src.core.swarm.ddl import apply_v59, apply_v60, apply_v62, apply_v63, apply_v64, apply_v65, apply_v66, apply_v67, apply_v68, apply_v69, apply_v70, apply_v71, rename_legacy
from src.core.pack.machines.ddl import apply_pack_machines
from src.core.pack.relay.ddl import apply_pack_relay
from src.core.pack.placement.ddl import apply_pack_placement
from src.core.project_colors.ddl import apply_v61, apply_v91, apply_v98
from src.core.pack.identity.ddl import apply_v80
from src.core.pack.span.ddl import apply_v82
from src.core.pack.transport.ddl import apply_pack_transport
from src.core.pack.migrate.ddl import apply_pack_migrate
from src.core.pack.move.ddl import apply_pack_move
from src.core.computers.ddl import apply_computer_links
from src.core.companion_shell.ddl import apply_v86
from src.core.pack.rollup_import.ddl import apply_v89
from src.core.pack.trust_carry.ddl import apply_v87, apply_v88
from src.core.flow_data.ddl import apply_mcp_surface, apply_v90
from src.core.exports.ddl import apply_v93
from src.core.skills.consent_via_ddl import (
    CONSENT_VIA_COLUMN,
    DDL_V41_ADD_CONSENT_VIA,
    INSTALLED_ITEMS_TABLE,
    widen_consent_check,
)
from src.core.skills.fork_mark_ddl import DDL_V42_ADD_FORKED, FORKED_COLUMN
from src.core.session_group_style_ddl import SESSION_GROUP_STYLES_TABLE
from src.core.migration_trail import utc_now
from src.core.session_family_backfill import run_backfill
from src.core.session_group_membership_migrate import carry_memberships

logger = structlog.get_logger()


def _step_v0_to_v1(conn: sqlite3.Connection) -> None:
    for statement in DDL_V1:
        conn.execute(statement)
    if not conn.execute(
        "SELECT 1 FROM meta WHERE key=?", (META_CREATED_AT,)
    ).fetchone():
        stamp = utc_now()
        set_meta(conn, META_CREATED_AT, stamp)
        set_meta(conn, META_PROJECT_TOMBSTONES_SINCE, stamp)
        set_meta(conn, META_PROJECT_TOMBSTONES_LEGACY_GAP, "0")
    ensure_install_id(conn)


def _step_v1_to_v2(conn: sqlite3.Connection) -> None:
    for statement in DDL_V2:
        conn.execute(statement)


def _step_v2_to_v3(conn: sqlite3.Connection) -> None:
    existing = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(sessions)")
    }
    if "tmux_session_id" in existing:
        return
    for statement in DDL_V3:
        conn.execute(statement)


def _step_v3_to_v4(conn: sqlite3.Connection) -> None:
    """Add ``projects.last_opened_at``, the launcher's ordering key.

    Description: feat/db-is-authoritative. Purely additive - one nullable
      column on ``projects``, no index - so a v3 reader that has not been
      upgraded keeps working against the same file and every existing row
      simply carries NULL.

      IDEMPOTENT BY INSPECTION, NOT BY THE STATEMENT, exactly as v2 -> v3
      is: SQLite's ``ALTER TABLE ADD COLUMN`` has no ``IF NOT EXISTS``, so
      PRAGMA table_info is read first and the step no-ops when the column
      is already there. That is what makes a retry after an INTERRUPTED
      trail entry safe by construction.

      A database that has never reached v3 has no ``projects`` table at
      all, which cannot happen here - the chain runs in order and v0 -> v1
      creates it - but the PRAGMA on a missing table returns no rows
      rather than raising, so the guard degrades to attempting the ALTER
      and surfacing SQLite's own error inside the caller's transaction
      rather than corrupting anything.
    Inputs: conn (sqlite3.Connection) - inside the caller's transaction.
    Output: None.
    Example: _step_v3_to_v4(conn)  # after _step_v2_to_v3
    """
    existing = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(projects)")
    }
    if "last_opened_at" in existing:
        return
    for statement in DDL_V4:
        conn.execute(statement)


def _step_v4_to_v5(conn: sqlite3.Connection) -> None:
    for statement in DDL_V5:
        conn.execute(statement)

    if get_meta(conn, META_PROJECT_TOMBSTONES_SINCE):
        return

    set_meta(conn, META_PROJECT_TOMBSTONES_SINCE, utc_now())
    set_meta(conn, META_PROJECT_TOMBSTONES_LEGACY_GAP, "1")


def _step_v5_to_v6(conn: sqlite3.Connection) -> None:
    existing = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(sessions)")
    }
    if "user_declined_at" in existing:
        return
    for statement in DDL_V6:
        conn.execute(statement)


def _step_v6_to_v7(conn: sqlite3.Connection) -> None:
    for statement in DDL_V7:
        conn.execute(statement)


def _step_v7_to_v8(conn: sqlite3.Connection) -> None:
    for statement in DDL_V8:
        conn.execute(statement)


_V9_CARRY_FORWARD = (
    "project_id",
    "working_dir",
    "legacy_session_id",
    "agent_type",
    "agent_family",
    "model",
    "claude_session_uuid",
    "parent_session_id",
    "fork_kind",
    "pinned_theme",
    "audio_enabled",
    "title",
    "adopted_at",
    "last_seen_running_at",
)


def _v9_merge_rename_splits(conn: sqlite3.Connection) -> int:
    groups = conn.execute(
        "SELECT tmux_socket, tmux_created_epoch, tmux_session_id "
        "FROM sessions "
        "WHERE tmux_session_id IS NOT NULL AND tmux_session_id != '' "
        "AND tmux_created_epoch IS NOT NULL "
        "GROUP BY tmux_socket, tmux_created_epoch, tmux_session_id "
        "HAVING COUNT(*) = 2"
    ).fetchall()

    merged = 0
    for group in groups:
        socket, epoch, sid = (
            group["tmux_socket"],
            group["tmux_created_epoch"],
            group["tmux_session_id"],
        )
        pair = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM sessions WHERE tmux_socket = ? "
                "AND tmux_created_epoch = ? AND tmux_session_id = ? "
                "ORDER BY id",
                (socket, epoch, sid),
            ).fetchall()
        ]
        living = [r for r in pair if r["lifecycle"] != "stopped"]
        corpses = [r for r in pair if r["lifecycle"] == "stopped"]
        if len(living) != 1 or len(corpses) != 1:
            continue
        survivor, corpse = living[0], corpses[0]

        sets, values = [], []
        for column in _V9_CARRY_FORWARD:
            if survivor.get(column) is None and corpse.get(column) is not None:
                sets.append(f"{column} = ?")
                values.append(corpse[column])
        if corpse.get("origin") == "created" and survivor.get("origin") != "created":
            sets.append("origin = ?")
            values.append("created")
        for flag in ("unread_auto", "unread_manual"):
            if int(corpse.get(flag) or 0) and not int(survivor.get(flag) or 0):
                sets.append(f"{flag} = 1")
        earlier = min(
            str(survivor.get("created_at") or ""),
            str(corpse.get("created_at") or ""),
        )
        if earlier and earlier != survivor.get("created_at"):
            sets.append("created_at = ?")
            values.append(earlier)

        if sets:
            values.append(int(survivor["id"]))
            conn.execute(
                f"UPDATE sessions SET {', '.join(sets)} WHERE id = ?", values
            )
        conn.execute("DELETE FROM sessions WHERE id = ?", (int(corpse["id"]),))
        merged += 1
    return merged


def _v9_backfill_labels(conn: sqlite3.Connection) -> int:
    from src.core.session_label import label_from_tmux_name

    rows = conn.execute(
        "SELECT id, tmux_name FROM sessions "
        "WHERE (title IS NULL OR title = '') AND tmux_name IS NOT NULL"
    ).fetchall()
    filled = 0
    for row in rows:
        label = label_from_tmux_name(row["tmux_name"])
        if not label:
            continue
        conn.execute(
            "UPDATE sessions SET title = ? WHERE id = ?",
            (label, int(row["id"])),
        )
        filled += 1
    return filled


def _step_v8_to_v9(conn: sqlite3.Connection) -> None:
    _v9_merge_rename_splits(conn)
    _v9_backfill_labels(conn)


def _step_v9_to_v10(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    if "claude_title" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN claude_title TEXT")


def _step_v10_to_v11(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    if "activity_state" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN activity_state TEXT")
    if "activity_state_at" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN activity_state_at TEXT")


def _v12_find_claude_uuid_duplicates(conn: sqlite3.Connection) -> List[Dict]:
    rows = conn.execute(
        "SELECT claude_session_uuid, GROUP_CONCAT(id) AS ids, COUNT(*) AS c "
        "FROM sessions "
        "WHERE claude_session_uuid IS NOT NULL "
        "GROUP BY claude_session_uuid "
        "HAVING COUNT(*) > 1 "
        "ORDER BY claude_session_uuid"
    ).fetchall()
    return [
        {
            "claude_session_uuid": row["claude_session_uuid"],
            "row_ids": [int(x) for x in str(row["ids"]).split(",")],
            "count": int(row["c"]),
        }
        for row in rows
    ]


def _step_v11_to_v12(conn: sqlite3.Connection) -> None:
    """Make ``ux_sessions_claude_uuid`` UNIQUE, unless the data disagrees.

      THREE OUTCOMES, NEVER TWO, AND NEITHER COLLAPSE IS SAFE HERE.
      Checked FIRST, before any DDL runs, via
      :func:`_v12_find_claude_uuid_duplicates`:

        duplicates found COULD NOT EVALUATE, not a failure of THIS step
                          and not silently ignored. Neither index
                          statement runs: ix_sessions_claude_uuid (v7)
                          stays exactly as it was, so the database is not
                          left with a dangling reference to an index that
                          was dropped without its replacement existing.
                          The exact uuid/row-id groups are recorded under
                          META_SESSIONS_CLAUDE_UUID_DUPLICATES so a human
                          can see precisely what to reconcile - never a
                          silently-picked winner, per this project's own
                          standing rule against inventing a verdict
                          nobody measured.

        CREATE UNIQUE INDEX itself fails despite the pre-check finding
                          nothing (a defensive branch, not one the tests
                          below expect to hit under normal SQLite
                          behaviour) - caught narrowly as
                          ``sqlite3.Error``, recorded the same way as a
                          found duplicate, and NOT re-raised.

      NEVER RAISES. This is the one property that matters most: the
      caller (db_steps.run_chain, driven from db_migration.ensure_db_
      migrated) commits every step from the database's current version up
      to CURRENT_SCHEMA_VERSION as ONE transaction. An exception here
      would roll back every step before it in the same run and drop the
      whole app into DEGRADED_MIGRATION_FAILED / read-only - exactly the
      "never block boot" posture db_migration.py already holds for every
      other step, and a live database holding a duplicate uuid is a
      finding to record, not a reason to take the app down.

      DROPPING AN INDEX IS NOT THE "ADDITIVE ONLY" RULE THIS FILE'S
      MODULE DOCSTRING WARNS AGAINST. That rule protects STORED DATA -
      tables, columns, rows a restore could not reconstruct. An index is
      derived, not stored fact (REVERSAL_SQL_V7's own comment says so),
      and this step only ever drops ix_sessions_claude_uuid on the branch
      where ux_sessions_claude_uuid has just been created to replace it -
      the column stays exactly as indexable as before, only faster and
      now constrained.

      IDEMPOTENT. Both DDL statements carry IF NOT EXISTS / IF EXISTS, so
      a retry after an INTERRUPTED trail entry re-runs cleanly whichever
      branch applies; the duplicate check is a pure SELECT and costs
      nothing to repeat.
    Inputs: conn (sqlite3.Connection) - inside the caller's transaction.
    Output: None.
    Example: _step_v11_to_v12(conn)  # after _step_v10_to_v11
    """
    duplicates = _v12_find_claude_uuid_duplicates(conn)
    if duplicates:
        set_meta(
            conn, META_SESSIONS_CLAUDE_UUID_DUPLICATES, json.dumps(duplicates)
        )
        logger.warning(
            "sessions_claude_uuid_unique_blocked",
            duplicate_uuid_count=len(duplicates),
            detail=(
                "one or more claude_session_uuid values are claimed by "
                "more than one sessions row; ux_sessions_claude_uuid was "
                "NOT created and ix_sessions_claude_uuid (plain) stays in "
                "place - see meta key "
                f"{META_SESSIONS_CLAUDE_UUID_DUPLICATES!r} for the exact "
                "uuid/row-id groups"
            ),
        )
        return

    try:
        conn.execute(DDL_SESSIONS_CLAUDE_UUID_UNIQUE_INDEX)
        conn.execute(DDL_SESSIONS_CLAUDE_UUID_PLAIN_INDEX_DROP)
    except sqlite3.Error as exc:
        set_meta(
            conn,
            META_SESSIONS_CLAUDE_UUID_DUPLICATES,
            json.dumps([{"error": f"{type(exc).__name__}: {exc}"}]),
        )
        logger.warning(
            "sessions_claude_uuid_unique_index_failed", error=str(exc)
        )
        return

    set_meta(conn, META_SESSIONS_CLAUDE_UUID_DUPLICATES, "[]")


def _step_v12_to_v13(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    if "claude_session_uuid_source" not in cols:
        conn.execute(
            "ALTER TABLE sessions ADD COLUMN claude_session_uuid_source TEXT"
        )
    conn.execute(
        "UPDATE sessions SET claude_session_uuid_source = 'hook' "
        "WHERE claude_session_uuid IS NOT NULL "
        "AND claude_session_uuid_source IS NULL"
    )


def _step_v13_to_v14(conn: sqlite3.Connection) -> None:
    for statement in DDL_V14:
        conn.execute(statement)


def _step_v14_to_v15(conn: sqlite3.Connection) -> None:
    archive_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(transcript_archives)")
    }
    if "superseded_by_archive_id" not in archive_cols:
        conn.execute(DDL_V15_TRANSCRIPT_ARCHIVES_SUPERSEDED_BY)
    if "growth_kind" not in archive_cols:
        conn.execute(DDL_V15_TRANSCRIPT_ARCHIVES_GROWTH_KIND)
    if "project_id" not in archive_cols:
        conn.execute(DDL_V15_TRANSCRIPT_ARCHIVES_PROJECT_ID)
    if "project_rooted_at" not in archive_cols:
        conn.execute(DDL_V15_TRANSCRIPT_ARCHIVES_PROJECT_ROOTED_AT)
    if "project_rooted_by" not in archive_cols:
        conn.execute(DDL_V15_TRANSCRIPT_ARCHIVES_PROJECT_ROOTED_BY)

    decision_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(transcript_root_decisions)")
    }
    if "project_id" not in decision_cols:
        conn.execute(DDL_V15_TRANSCRIPT_ROOT_DECISIONS_PROJECT_ID)

    conn.execute(DDL_V15_TRANSCRIPT_ARCHIVES_SUPERSEDED_BY_INDEX)
    conn.execute(DDL_V15_TRANSCRIPT_ARCHIVES_PROJECT_INDEX)




def _step_v15_to_v16(conn: sqlite3.Connection) -> None:
    return None


def _step_v16_to_v17(conn: sqlite3.Connection) -> None:
    return None


def _step_v17_to_v18(conn: sqlite3.Connection) -> None:
    return None


def _step_v18_to_v19(conn: sqlite3.Connection) -> None:
    for statement in DDL_V19:
        conn.execute(statement)


def _step_v19_to_v20(conn: sqlite3.Connection) -> None:
    """Admit the 'opaque' session_ref_scheme, and correct the rows.

      IT REWRITES NO TABLE. message_appearances references this table
      ON DELETE CASCADE and PRAGMA foreign_keys is a no-op inside the
      transaction every step runs in, so the standard rebuild recipe
      cannot be made safe here. The CHECK is edited in place instead -
      see src/core/message_scheme_repair.py for the full argument and
      the measurements behind it.
    """
    repair_session_ref_schemes(conn)


def _step_v20_to_v21(conn: sqlite3.Connection) -> None:
    install_transcript_activity(conn)


def _step_v21_to_v22(conn: sqlite3.Connection) -> None:
    conn.execute(DDL_V22_TRANSCRIPT_ARCHIVES_CONTENT_SHA_INDEX)
    if not column_exists(conn, "transcript_archives", "dedupe_kind"):
        conn.execute(DDL_V22_TRANSCRIPT_ARCHIVES_DEDUPE_KIND)


def _step_v22_to_v23(conn: sqlite3.Connection) -> None:
    if not table_exists(conn, "sessions"):
        return
    if not column_exists(conn, "sessions", "last_work_at"):
        conn.execute(DDL_V23_SESSIONS_LAST_WORK_AT)



def _step_v23_to_v24(conn: sqlite3.Connection) -> None:
    for statement in DDL_V24:
        conn.execute(statement)
    if not table_exists(conn, "session_group_members"):
        return
    if not table_exists(conn, "sessions"):
        return
    carried = carry_memberships(conn)
    outcomes: Dict[str, int] = {}
    for entry in carried:
        outcomes[entry.outcome] = outcomes.get(entry.outcome, 0) + 1
    logger.info(
        "session_group_membership_rekeyed",
        legacy_rows=len(carried),
        **outcomes,
    )


def _step_v24_to_v25(conn: sqlite3.Connection) -> None:
    if not table_exists(conn, "sessions"):
        return
    if not column_exists(conn, "sessions", "kind"):
        conn.execute(DDL_V25_SESSIONS_KIND)
    conn.execute(DDL_V25_SESSIONS_KIND_BACKFILL)

def _step_v25_to_v26(conn: sqlite3.Connection) -> None:
    """Add the durable notification mute and its policy generation.

      ``notification_policy_generation`` IS A COUNTER, NOT A CLOCK. It
      steps by one on every policy change, mute and unmute alike. A
      notification carries the generation it was queued under and the
      dispatcher refuses anything that is not the current one, which is
      what stops an alert queued before a mute from arriving after it and
      what stops a muted backlog from replaying on unmute. Two changes
      inside one clock tick are indistinguishable by timestamp; by
      counter they are not.

      NO BACKFILL, AND THAT IS THE POINT. Both columns are nullable with
      no SQL default, and NULL here is a definite answer rather than an
      unknown one: a mute can only ever be recorded in this column, so a
      row that has none has never been muted. Existing rows, new sessions
      and forks therefore all start unmuted without a single UPDATE.
      Compare v25's ``kind``, where the fact lived in a transcript the
      column could not see and NULL had to mean "never looked at".

      IDEMPOTENT: each ALTER is guarded by ``column_exists`` because
      SQLite's ADD COLUMN has no IF NOT EXISTS. A no-op on an install
      whose sessions table was never created (pre-v2).
    Inputs: conn (sqlite3.Connection) - inside the caller's transaction.
    Output: None.
    Example: _step_v25_to_v26(conn)  # after _step_v24_to_v25
    """
    if not table_exists(conn, "sessions"):
        return
    if not column_exists(conn, "sessions", "notifications_muted"):
        conn.execute(DDL_V26_SESSIONS_NOTIFICATIONS_MUTED)
    if not column_exists(
        conn, "sessions", "notification_policy_generation"
    ):
        conn.execute(DDL_V26_SESSIONS_NOTIFICATION_POLICY_GENERATION)



def _step_v26_to_v27(conn: sqlite3.Connection) -> None:
    for statement in DDL_V27:
        conn.execute(statement)

def _step_v27_to_v28(conn: sqlite3.Connection) -> None:
    for statement in DDL_V28:
        conn.execute(statement)


def _step_v28_to_v29(conn: sqlite3.Connection) -> None:
    """v28 -> v29: record the launched agent family on rows that lack one.

    Description: NO DDL. ``sessions.agent_family`` already exists; it
      simply never had a writer on the create path, which has written
      ``agent_family_source='launched'`` beside a NULL family since the
      column was added. The fix at the write site covers every new row;
      this pass repairs the ones already stored, by resolving each row's
      ``agent_type`` against the wrapper list config.json carries TODAY
      and writing what it resolves to. A row that resolves to nothing -
      a wrapper the user has since deleted - is LEFT NULL, because a
      guess written into a record cannot be told from a measurement
      afterwards.

      THE BODY LIVES IN ``src/core/session_family_backfill.py``, like
      ``carry_memberships`` does, because it needs the wrapper list and
      that is not in this database. Read that module before changing
      this step: it argues which resolver may be used and why a
      could-not-read config writes nothing at all.

      IDEMPOTENT BY ITS OWN WHERE CLAUSE - it reads only rows whose
      family is NULL and writes only onto rows whose family is NULL - so
      a re-run after an interrupted attempt finishes the remainder and
      no-ops on the rest. ADDITIVE in the sense the module docstring
      demands: it fills NULLs and overwrites nothing, the same shape as
      v25's ``kind`` backfill.
    Inputs: conn (sqlite3.Connection) - inside the caller's transaction.
    Output: None.
    Example: _step_v28_to_v29(conn)  # after _step_v27_to_v28
    """
    run_backfill(conn)


def _step_v29_to_v30(conn: sqlite3.Connection) -> None:
    for statement in DDL_V30:
        conn.execute(statement)


def _step_v30_to_v31(conn: sqlite3.Connection) -> None:
    return None


def _step_v31_to_v32(conn: sqlite3.Connection) -> None:
    for statement in DDL_V32:
        conn.execute(statement)


def _step_v32_to_v33(conn: sqlite3.Connection) -> None:
    for statement in DDL_V33:
        conn.execute(statement)


def _step_v33_to_v34(conn: sqlite3.Connection) -> None:
    for statement in DDL_V34:
        conn.execute(statement)


def _step_v34_to_v35(conn: sqlite3.Connection) -> None:
    for statement in DDL_V35:
        conn.execute(statement)


def _step_v35_to_v36(conn: sqlite3.Connection) -> None:
    for statement in DDL_V36:
        conn.execute(statement)


def _step_v36_to_v37(conn: sqlite3.Connection) -> None:
    for statement in DDL_V37:
        conn.execute(statement)


def _step_v37_to_v38(conn: sqlite3.Connection) -> None:
    for statement in DDL_V38:
        conn.execute(statement)


def _step_v38_to_v39(conn: sqlite3.Connection) -> None:
    create, add_icon = DDL_V39
    conn.execute(create)
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({SESSION_GROUP_STYLES_TABLE})")}
    if ICON_COLUMN not in cols:
        conn.execute(add_icon)


def _step_v39_to_v40(conn: sqlite3.Connection) -> None:
    apply_v40(conn, utc_now())


def _step_v40_to_v41(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({INSTALLED_ITEMS_TABLE})")}
    if cols and CONSENT_VIA_COLUMN not in cols:
        conn.execute(DDL_V41_ADD_CONSENT_VIA)


def _step_v41_to_v42(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({INSTALLED_ITEMS_TABLE})")}
    if not cols:
        return
    if FORKED_COLUMN not in cols:
        conn.execute(DDL_V42_ADD_FORKED)
    main = next((r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), "")
    old = os.path.join(os.path.dirname(main), "skill_watch.db") if main else ""
    if not old or not os.path.isfile(old):
        return
    try:
        with closing(sqlite3.connect(f"file:{old}?mode=ro", uri=True)) as watch:
            ids = [r[0] for r in watch.execute("SELECT install_id FROM forks")]
        conn.executemany(f"UPDATE {INSTALLED_ITEMS_TABLE} SET {FORKED_COLUMN} = 1 WHERE install_id = ?",
                         [(i,) for i in ids])
    except sqlite3.Error as exc:
        logger.warning("skill_fork_carry_over_failed", error_type=type(exc).__name__)


def _step_v42_to_v43(conn: sqlite3.Connection) -> None:
    for statement in DDL_V43:
        conn.execute(statement)


def _step_v43_to_v44(conn: sqlite3.Connection) -> None:
    apply_v44(conn)


def _step_v44_to_v45(conn: sqlite3.Connection) -> None:
    for statement in DDL_V45:
        conn.execute(statement)


def _step_v45_to_v46(conn: sqlite3.Connection) -> None:
    for statement in DDL_V46:
        if statement is PARENT_INDEX_V46 and not column_exists(conn, "conversation_index", "parent_conversation_id"):
            continue
        conn.execute(statement)


def _step_v46_to_v47(conn: sqlite3.Connection) -> None:
    pass


def _step_v47_to_v48(conn: sqlite3.Connection) -> None:
    apply_v48(conn)


def _step_v48_to_v49(conn: sqlite3.Connection) -> None:
    apply_v49(conn)


def _step_v49_to_v50(conn: sqlite3.Connection) -> None:
    apply_v50(conn)


def _step_v50_to_v51(conn: sqlite3.Connection) -> None:
    apply_v51(conn)


def _step_v51_to_v52(conn: sqlite3.Connection) -> None:
    apply_v52(conn)


def _step_v52_to_v53(conn: sqlite3.Connection) -> None:
    apply_v53(conn)


def _step_v53_to_v54(conn: sqlite3.Connection) -> None:
    apply_v54(conn)


def _step_v54_to_v55(conn: sqlite3.Connection) -> None:
    apply_v55(conn)


def _step_v55_to_v56(conn: sqlite3.Connection) -> None:
    apply_v56(conn)


def _step_v56_to_v57(conn: sqlite3.Connection) -> None:
    apply_v57(conn)


def _step_v57_to_v58(conn: sqlite3.Connection) -> None:
    apply_v58(conn)


def _step_v58_to_v59(conn: sqlite3.Connection) -> None:
    apply_v59(conn)


def _step_v59_to_v60(conn: sqlite3.Connection) -> None:
    apply_v60(conn)


def _step_v60_to_v61(conn: sqlite3.Connection) -> None:
    apply_v61(conn)


def _step_v61_to_v62(conn: sqlite3.Connection) -> None:
    apply_v62(conn)


def _step_v62_to_v63(conn: sqlite3.Connection) -> None:
    apply_v63(conn)


def _step_v63_to_v64(conn: sqlite3.Connection) -> None:
    apply_v64(conn)


def _step_v64_to_v65(conn: sqlite3.Connection) -> None:
    apply_v65(conn)


def _step_v65_to_v66(conn: sqlite3.Connection) -> None:
    apply_v66(conn)


def _step_v66_to_v67(conn: sqlite3.Connection) -> None:
    apply_v67(conn)


def _step_v67_to_v68(conn: sqlite3.Connection) -> None:
    apply_v68(conn)


def _step_v68_to_v69(conn: sqlite3.Connection) -> None:
    apply_v69(conn)


def _step_v69_to_v70(conn: sqlite3.Connection) -> None:
    apply_v70(conn)


def _step_v70_to_v71(conn: sqlite3.Connection) -> None:
    apply_v71(conn)


def _step_v71_to_v72(conn: sqlite3.Connection) -> None:
    apply_v72(conn)


def _step_v72_to_v73(conn: sqlite3.Connection) -> None:
    apply_v73(conn)


def _step_v73_to_v74(conn: sqlite3.Connection) -> None:
    apply_v74(conn)


def _step_v74_to_v75(conn: sqlite3.Connection) -> None:
    apply_v75(conn)


def _step_v75_to_v76(conn: sqlite3.Connection) -> None:
    rename_legacy(conn)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "crosstalk_messages" in tables:
        conn.execute("UPDATE crosstalk_messages SET source = 'swarm' WHERE source = 'pack'")
    if "crosstalk_contacts" in tables:
        conn.execute("UPDATE crosstalk_contacts SET source = 'swarm' WHERE source = 'pack'")
    if "swarm_agents" in tables and "launch_profile" in {r[1] for r in conn.execute("PRAGMA table_info(swarm_agents)")}:
        conn.execute("UPDATE swarm_agents SET launch_profile = 'swarm-upper' WHERE launch_profile = 'pack-upper'")


def _step_v76_to_v77(conn: sqlite3.Connection) -> None:
    apply_pack_machines(conn)


def _step_v77_to_v78(conn: sqlite3.Connection) -> None:
    apply_pack_relay(conn)


def _step_v78_to_v79(conn: sqlite3.Connection) -> None:
    apply_pack_placement(conn)


def _step_v79_to_v80(conn: sqlite3.Connection) -> None:
    apply_v80(conn)


def _step_v80_to_v81(conn: sqlite3.Connection) -> None:
    apply_pack_transport(conn)


def _step_v81_to_v82(conn: sqlite3.Connection) -> None:
    apply_v82(conn)


def _step_v83_to_v84(conn: sqlite3.Connection) -> None:
    apply_pack_move(conn)


def _step_v82_to_v83(conn: sqlite3.Connection) -> None:
    apply_pack_migrate(conn)


def _step_v84_to_v85(conn: sqlite3.Connection) -> None:
    apply_computer_links(conn)


def _step_v85_to_v86(conn: sqlite3.Connection) -> None:
    apply_v86(conn)


def _step_v86_to_v87(conn: sqlite3.Connection) -> None:
    apply_v87(conn)


def _step_v87_to_v88(conn: sqlite3.Connection) -> None:
    apply_v88(conn)


def _step_v88_to_v89(conn: sqlite3.Connection) -> None:
    apply_v89(conn)


def _step_v89_to_v90(conn: sqlite3.Connection) -> None:
    apply_v89(conn)
    apply_v90(conn)


def _step_v90_to_v91(conn: sqlite3.Connection) -> None:
    apply_v91(conn)


def _step_v91_to_v92(conn: sqlite3.Connection) -> None:
    apply_v92(conn)


def _step_v92_to_v93(conn: sqlite3.Connection) -> None:
    apply_v93(conn)


def _step_v93_to_v94(conn: sqlite3.Connection) -> None:
    apply_v94(conn)


def _step_v94_to_v95(conn: sqlite3.Connection) -> None:
    apply_mcp_surface(conn)


def _step_v95_to_v96(conn: sqlite3.Connection) -> None:
    apply_v96(conn)


def _step_v96_to_v97(conn: sqlite3.Connection) -> None:
    widen_consent_check(conn)


def _step_v97_to_v98(conn: sqlite3.Connection) -> None:
    apply_v98(conn)


# CURRENT_SCHEMA_VERSION
STEPS: Dict[int, Callable[[sqlite3.Connection], None]] = {
    0: _step_v0_to_v1,
    1: _step_v1_to_v2,
    2: _step_v2_to_v3,
    3: _step_v3_to_v4,
    4: _step_v4_to_v5,
    5: _step_v5_to_v6,
    6: _step_v6_to_v7,
    7: _step_v7_to_v8,
    8: _step_v8_to_v9,
    9: _step_v9_to_v10,
    10: _step_v10_to_v11,
    11: _step_v11_to_v12,
    12: _step_v12_to_v13,
    13: _step_v13_to_v14,
    14: _step_v14_to_v15,
    15: _step_v15_to_v16,
    16: _step_v16_to_v17,
    17: _step_v17_to_v18,
    18: _step_v18_to_v19,
    19: _step_v19_to_v20,
    20: _step_v20_to_v21,
    21: _step_v21_to_v22,
    22: _step_v22_to_v23,
    23: _step_v23_to_v24,
    24: _step_v24_to_v25,
    25: _step_v25_to_v26,
    26: _step_v26_to_v27,
    27: _step_v27_to_v28,
    28: _step_v28_to_v29,
    29: _step_v29_to_v30,
    30: _step_v30_to_v31,
    31: _step_v31_to_v32,
    32: _step_v32_to_v33,
    33: _step_v33_to_v34,
    34: _step_v34_to_v35,
    35: _step_v35_to_v36,
    36: _step_v36_to_v37,
    37: _step_v37_to_v38,
    38: _step_v38_to_v39,
    39: _step_v39_to_v40,
    40: _step_v40_to_v41,
    41: _step_v41_to_v42,
    42: _step_v42_to_v43,
    43: _step_v43_to_v44,
    44: _step_v44_to_v45,
    45: _step_v45_to_v46,
    46: _step_v46_to_v47,
    47: _step_v47_to_v48,
    48: _step_v48_to_v49,
    49: _step_v49_to_v50,
    50: _step_v50_to_v51,
    51: _step_v51_to_v52,
    52: _step_v52_to_v53,
    53: _step_v53_to_v54,
    54: _step_v54_to_v55,
    55: _step_v55_to_v56,
    56: _step_v56_to_v57,
    57: _step_v57_to_v58,
    58: _step_v58_to_v59,
    59: _step_v59_to_v60,
    60: _step_v60_to_v61,
    61: _step_v61_to_v62,
    62: _step_v62_to_v63,
    63: _step_v63_to_v64,
    64: _step_v64_to_v65,
    65: _step_v65_to_v66,
    66: _step_v66_to_v67,
    67: _step_v67_to_v68,
    68: _step_v68_to_v69,
    69: _step_v69_to_v70,
    70: _step_v70_to_v71,
    71: _step_v71_to_v72,
    72: _step_v72_to_v73,
    73: _step_v73_to_v74,
    74: _step_v74_to_v75,
    75: _step_v75_to_v76,
    76: _step_v76_to_v77,
    77: _step_v77_to_v78,
    78: _step_v78_to_v79,
    79: _step_v79_to_v80,
    80: _step_v80_to_v81,
    81: _step_v81_to_v82,
    82: _step_v82_to_v83,
    83: _step_v83_to_v84,
    84: _step_v84_to_v85,
    85: _step_v85_to_v86,
    86: _step_v86_to_v87,
    87: _step_v87_to_v88,
    88: _step_v88_to_v89,
    89: _step_v89_to_v90,
    90: _step_v90_to_v91,
    91: _step_v91_to_v92,
    92: _step_v92_to_v93,
    93: _step_v93_to_v94,
    94: _step_v94_to_v95,
    95: _step_v95_to_v96,
    96: _step_v96_to_v97,
    97: _step_v97_to_v98,
}


def run_chain(conn: sqlite3.Connection, from_version: int, to_version: int) -> List[str]:
    applied: List[str] = []
    for version in range(from_version, to_version):
        step = STEPS.get(version)
        if step is None:
            raise KeyError(
                f"no migration step registered for schema v{version} -> "
                f"v{version + 1}"
            )
        step(conn)
        applied.append(f"{version}->{version + 1}")
    set_meta(conn, META_SCHEMA_VERSION, str(to_version))
    return applied
