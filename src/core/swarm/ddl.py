
from __future__ import annotations

import re
import sqlite3
from typing import Tuple

DDL_V59: Tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS swarm_agents (
        id                 INTEGER PRIMARY KEY,
        slug               TEXT NOT NULL,
        rank               TEXT NOT NULL CHECK (rank IN ('alpha','company','project','feature','task')),
        parent_id          INTEGER REFERENCES swarm_agents(id),
        display_name       TEXT NOT NULL,
        persona            TEXT,
        job                TEXT NOT NULL,
        naming_family      TEXT,
        naming_state       TEXT CHECK (naming_state IN ('none','proposed','approved')),
        repo_dir           TEXT NOT NULL,
        memory_scope       TEXT NOT NULL CHECK (memory_scope IN ('project','local')),
        project_id         INTEGER REFERENCES projects(id) ON DELETE SET NULL,
        company_id         INTEGER REFERENCES companies(id) ON DELETE SET NULL,
        session_row_id     INTEGER UNIQUE REFERENCES sessions(id),
        harness            TEXT NOT NULL DEFAULT 'claude' CHECK (harness IN ('claude','codex')),
        launch_profile     TEXT,
        model              TEXT NOT NULL DEFAULT 'opus',
        effort             TEXT NOT NULL CHECK (effort IN ('low','medium','high','xhigh','max')),
        effort_reason      TEXT,
        goal               TEXT,
        task_type          TEXT,
        origin_message_ref TEXT,
        character_seed     INTEGER NOT NULL,
        color_slot         INTEGER NOT NULL CHECK (color_slot BETWEEN 1 AND 8),
        thread_key         TEXT NOT NULL,
        state              TEXT NOT NULL DEFAULT 'asleep'
                           CHECK (state IN ('asleep','waking','awake','sleeping','torn_down')),
        turn_authority     TEXT CHECK (turn_authority IN ('owner','data')),
        turn_opened_at     TEXT,
        created_at         TEXT NOT NULL,
        updated_at         TEXT NOT NULL,
        torn_down_at       TEXT,
        CHECK (rank <> 'alpha' OR parent_id IS NULL),
        CHECK (harness = 'claude' OR rank IN ('feature','task'))
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS swarm_agents_repo_slug ON swarm_agents(repo_dir, slug) "
    "WHERE torn_down_at IS NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS swarm_agents_thread_key ON swarm_agents(thread_key) "
    "WHERE torn_down_at IS NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS swarm_agents_one_alpha ON swarm_agents(rank) "
    "WHERE rank = 'alpha' AND torn_down_at IS NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS swarm_agents_one_per_project ON swarm_agents(project_id) "
    "WHERE rank = 'project' AND torn_down_at IS NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS swarm_agents_one_per_company ON swarm_agents(company_id) "
    "WHERE rank = 'company' AND torn_down_at IS NULL",
    "CREATE INDEX IF NOT EXISTS swarm_agents_parent ON swarm_agents(parent_id)",
    """CREATE TABLE IF NOT EXISTS swarm_wakes (
        id                INTEGER PRIMARY KEY,
        agent_id          INTEGER NOT NULL REFERENCES swarm_agents(id),
        started_at        TEXT NOT NULL,
        ended_at          TEXT,
        reason            TEXT CHECK (reason IN
                          ('owner_message','crosstalk','question','learning','spawn','manual','trust')),
        mode              TEXT CHECK (mode IN ('fresh','resume')),
        authority         TEXT CHECK (authority IN ('owner','data')),
        conversation_uuid TEXT,
        tmux_name         TEXT,
        tmux_epoch        TEXT,
        end_reason        TEXT CHECK (end_reason IN ('sleep','auto_sleep','died','teardown','failed'))
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS swarm_one_open_wake ON swarm_wakes(agent_id) WHERE ended_at IS NULL",
    """CREATE TABLE IF NOT EXISTS swarm_deliveries (
        id                INTEGER PRIMARY KEY,
        agent_id          INTEGER NOT NULL REFERENCES swarm_agents(id),
        wake_id           INTEGER REFERENCES swarm_wakes(id),
        authority         TEXT NOT NULL CHECK (authority IN ('owner','data')),
        source            TEXT CHECK (source IN ('owner_chat','huddle_tell','crosstalk','send_message',
                          'send_keys','swarm_question','swarm_answer','learning','report','wake_prompt')),
        source_ref        TEXT,
        owner_message_ref TEXT,
        delivered_at      TEXT NOT NULL,
        CHECK ((authority = 'owner') = (owner_message_ref IS NOT NULL))
    )""",
    "CREATE INDEX IF NOT EXISTS swarm_deliveries_agent ON swarm_deliveries(agent_id, delivered_at)",
    """CREATE TABLE IF NOT EXISTS swarm_repo_visibility (
        repo_dir    TEXT PRIMARY KEY,
        remote_url  TEXT,
        visibility  TEXT CHECK (visibility IN ('public','private','local','unknown')),
        checked_at  TEXT,
        approved_at TEXT,
        card_ref    TEXT
    )""",
)

V59_COLUMNS: Tuple[Tuple[str, str, str], ...] = ()


def apply_v59(conn: sqlite3.Connection) -> None:
    rename_legacy(conn)
    for statement in DDL_V59:
        conn.execute(statement)


V60_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("swarm_repo_visibility", "remote_fingerprint",
     "ALTER TABLE swarm_repo_visibility ADD COLUMN remote_fingerprint TEXT"),
)


def apply_v60(conn: sqlite3.Connection) -> None:
    rename_legacy(conn)
    for table, column, statement in V60_COLUMNS:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present and column not in present:
            conn.execute(statement)


DDL_V62: Tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS swarm_reports (
        id              INTEGER PRIMARY KEY,
        agent_id        INTEGER NOT NULL REFERENCES swarm_agents(id),
        parent_id       INTEGER NOT NULL REFERENCES swarm_agents(id),
        task_type       TEXT,
        summary         TEXT NOT NULL CHECK (length(summary) <= 4000),
        state           TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','accepted','rejected')),
        child_card_ref  TEXT,
        parent_card_ref TEXT,
        created_at      TEXT NOT NULL,
        decided_at      TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS swarm_reports_parent ON swarm_reports(parent_id, state)",
)


def apply_v62(conn: sqlite3.Connection) -> None:
    rename_legacy(conn)
    for statement in DDL_V62:
        conn.execute(statement)


DDL_V63: Tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS swarm_facts (
        id                 TEXT PRIMARY KEY,
        agent_id           INTEGER NOT NULL REFERENCES swarm_agents(id),
        rel_path           TEXT NOT NULL,
        title              TEXT NOT NULL,
        scope              TEXT NOT NULL CHECK (scope IN ('craft','project')),
        origin             TEXT NOT NULL CHECK (origin IN ('owner','agent','handwritten')),
        owner_message_ref  TEXT,
        taught_at          TEXT NOT NULL,
        taught_by_agent_id INTEGER REFERENCES swarm_agents(id),
        sha256             TEXT,
        state              TEXT NOT NULL DEFAULT 'live' CHECK (state IN ('live','held','killed')),
        killed_at          TEXT,
        CHECK ((origin = 'owner') = (owner_message_ref IS NOT NULL))
    )""",
    "CREATE INDEX IF NOT EXISTS swarm_facts_agent ON swarm_facts(agent_id, state)",
    "CREATE VIRTUAL TABLE IF NOT EXISTS swarm_fact_fts USING fts5("
    "doc_key UNINDEXED, agent_id UNINDEXED, title, body, tokenize = 'porter unicode61')",
    """CREATE TABLE IF NOT EXISTS swarm_questions (
        id                INTEGER PRIMARY KEY,
        text              TEXT NOT NULL,
        state             TEXT NOT NULL DEFAULT 'routing'
                          CHECK (state IN ('routing','open','answered','reopened','closed')),
        card_ref          TEXT,
        answer_text       TEXT,
        answered_by       TEXT,
        answer_message_ref TEXT,
        created_at        TEXT NOT NULL,
        answered_at       TEXT
    )""",
    "CREATE VIRTUAL TABLE IF NOT EXISTS swarm_question_fts USING fts5("
    "question_id UNINDEXED, text, tokenize = 'porter unicode61')",
    """CREATE TABLE IF NOT EXISTS swarm_question_askers (
        question_id          INTEGER NOT NULL REFERENCES swarm_questions(id),
        agent_id             INTEGER NOT NULL REFERENCES swarm_agents(id),
        crosstalk_message_id TEXT,
        asked_at             TEXT NOT NULL,
        PRIMARY KEY (question_id, agent_id)
    )""",
    """CREATE TABLE IF NOT EXISTS swarm_question_hops (
        id          INTEGER PRIMARY KEY,
        question_id INTEGER NOT NULL REFERENCES swarm_questions(id),
        agent_id    INTEGER NOT NULL REFERENCES swarm_agents(id),
        coverage    REAL,
        outcome     TEXT NOT NULL CHECK (outcome IN ('answered','passed','no_hit','timeout','skipped')),
        at          TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS swarm_question_hops_q ON swarm_question_hops(question_id)",
    """CREATE TABLE IF NOT EXISTS swarm_receipts (
        id                  INTEGER PRIMARY KEY,
        question_id         INTEGER NOT NULL REFERENCES swarm_questions(id),
        answering_agent_id  INTEGER REFERENCES swarm_agents(id),
        kind                TEXT NOT NULL CHECK (kind IN ('owner_fact','agent_fact','judgment')),
        fact_ids            TEXT NOT NULL DEFAULT '[]',
        rendered            TEXT NOT NULL,
        created_at          TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS swarm_receipts_question ON swarm_receipts(question_id)",
    """CREATE TABLE IF NOT EXISTS swarm_learning (
        id                  INTEGER PRIMARY KEY,
        agent_id            INTEGER NOT NULL REFERENCES swarm_agents(id),
        question_id         INTEGER REFERENCES swarm_questions(id),
        kind                TEXT NOT NULL CHECK (kind IN ('sealed_answer','discovery','skip_level','conflict')),
        text                TEXT NOT NULL,
        owner_message_ref   TEXT,
        scope_stamp         TEXT CHECK (scope_stamp IS NULL OR scope_stamp IN ('craft','project')),
        state               TEXT NOT NULL DEFAULT 'queued'
                            CHECK (state IN ('queued','delivered','stamped','dropped')),
        created_at          TEXT NOT NULL,
        delivered_wake_id   INTEGER REFERENCES swarm_wakes(id)
    )""",
    "CREATE INDEX IF NOT EXISTS swarm_learning_agent ON swarm_learning(agent_id, state)",
)


def apply_v63(conn: sqlite3.Connection) -> None:
    rename_legacy(conn)
    for statement in DDL_V63:
        conn.execute(statement)


DDL_V64: Tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS swarm_promotions (
        id               INTEGER PRIMARY KEY,
        agent_id         INTEGER NOT NULL REFERENCES swarm_agents(id),
        project_id       INTEGER,
        task_type        TEXT NOT NULL,
        from_rank        TEXT NOT NULL CHECK (from_rank IN ('task','feature')),
        to_rank          TEXT NOT NULL CHECK (to_rank IN ('task','feature')),
        commit_sha       TEXT,
        seed_rel_path    TEXT,
        receipt_card_ref TEXT,
        created_at       TEXT NOT NULL,
        flipped_back_at  TEXT,
        flip_commit_sha  TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS swarm_promotions_agent ON swarm_promotions(agent_id)",
    "CREATE INDEX IF NOT EXISTS swarm_promotions_type ON swarm_promotions(project_id, task_type)",
    """CREATE TABLE IF NOT EXISTS swarm_project_settings (
        project_id          INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
        promotion_threshold INTEGER NOT NULL DEFAULT 5 CHECK (promotion_threshold BETWEEN 1 AND 100)
    )""",
)


def apply_v64(conn: sqlite3.Connection) -> None:
    rename_legacy(conn)
    for statement in DDL_V64:
        conn.execute(statement)


DDL_V65: Tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS swarm_suggestions (
        id          INTEGER PRIMARY KEY,
        by_agent_id INTEGER NOT NULL REFERENCES swarm_agents(id),
        kind        TEXT NOT NULL CHECK (kind IN ('company','project')),
        name        TEXT NOT NULL,
        reason      TEXT NOT NULL,
        company_id  INTEGER REFERENCES companies(id) ON DELETE SET NULL,
        card_ref    TEXT,
        state       TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','approved','declined')),
        created_at  TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS swarm_suggestions_state ON swarm_suggestions(state, company_id)",
)

V65_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("companies", "accounts", "ALTER TABLE companies ADD COLUMN accounts TEXT NOT NULL DEFAULT '{}'"),
    ("companies", "hq_project_id",
     "ALTER TABLE companies ADD COLUMN hq_project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL"),
)


def apply_v65(conn: sqlite3.Connection) -> None:
    rename_legacy(conn)
    for table, column, statement in V65_COLUMNS:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present and column not in present:
            conn.execute(statement)
    for statement in DDL_V65:
        conn.execute(statement)


V66_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("swarm_suggestions", "owner_message_ref", "ALTER TABLE swarm_suggestions ADD COLUMN owner_message_ref TEXT"),
)


def apply_v66(conn: sqlite3.Connection) -> None:
    rename_legacy(conn)
    for table, column, statement in V66_COLUMNS:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present and column not in present:
            conn.execute(statement)


V67_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("swarm_suggestions", "made_project_id",
     "ALTER TABLE swarm_suggestions ADD COLUMN made_project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL"),
)


def apply_v67(conn: sqlite3.Connection) -> None:
    rename_legacy(conn)
    for table, column, statement in V67_COLUMNS:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present and column not in present:
            conn.execute(statement)


V68_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("swarm_questions", "summary", "ALTER TABLE swarm_questions ADD COLUMN summary TEXT"),
    ("swarm_questions", "task", "ALTER TABLE swarm_questions ADD COLUMN task TEXT"),
    ("swarm_question_askers", "author_path", "ALTER TABLE swarm_question_askers ADD COLUMN author_path TEXT"),
)


def apply_v68(conn: sqlite3.Connection) -> None:
    rename_legacy(conn)
    for table, column, statement in V68_COLUMNS:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present and column not in present:
            conn.execute(statement)


V69_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("companies", "hue", "ALTER TABLE companies ADD COLUMN hue INTEGER CHECK (hue IS NULL OR hue BETWEEN 0 AND 359)"),
    ("swarm_agents", "color_chosen",
     "ALTER TABLE swarm_agents ADD COLUMN color_chosen INTEGER NOT NULL DEFAULT 0 CHECK (color_chosen IN (0, 1))"),
)


def apply_v69(conn: sqlite3.Connection) -> None:
    rename_legacy(conn)
    for table, column, statement in V69_COLUMNS:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present and column not in present:
            conn.execute(statement)


V70_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("swarm_agents", "specialty", "ALTER TABLE swarm_agents ADD COLUMN specialty TEXT"),
    ("swarm_agents", "former_names", "ALTER TABLE swarm_agents ADD COLUMN former_names TEXT"),
)


def apply_v70(conn: sqlite3.Connection) -> None:
    rename_legacy(conn)
    for table, column, statement in V70_COLUMNS:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present and column not in present:
            conn.execute(statement)


V71_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("swarm_agents", "shape",
     "ALTER TABLE swarm_agents ADD COLUMN shape TEXT CHECK (shape IS NULL OR shape IN ('square', 'circle', 'hexagon', 'triangle', 'diamond', 'pentagon', 'octagon', 'star', 'shield', 'cloud'))"),
    ("swarm_agents", "tile_bg", "ALTER TABLE swarm_agents ADD COLUMN tile_bg INTEGER CHECK (tile_bg IS NULL OR tile_bg BETWEEN 1 AND 8)"),
)


def apply_v71(conn: sqlite3.Connection) -> None:
    rename_legacy(conn)
    for table, column, statement in V71_COLUMNS:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if present and column not in present:
            conn.execute(statement)


LEGACY_TABLES: Tuple[str, ...] = (
    "agents", "wakes", "deliveries", "repo_visibility", "reports", "facts", "fact_fts", "questions", "question_fts",
    "question_askers", "question_hops", "receipts", "learning", "promotions", "project_settings", "suggestions",
)
_DDL_ALL: Tuple[str, ...] = DDL_V59 + DDL_V62 + DDL_V63 + DDL_V64 + DDL_V65


def _tables(conn: sqlite3.Connection) -> set:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def rename_legacy(conn: sqlite3.Connection) -> None:
    """Rename a database's ``pack_*`` Swarm tables to ``swarm_*``, idempotent, inside the caller's transaction.

    Description: ``ALTER TABLE RENAME`` rewrites foreign keys but keeps index names, so the old ``pack_`` indexes are dropped
      and the DDL's own ``swarm_`` indexes recreated; ``swarm_deliveries`` is rebuilt so its ``source`` CHECK reads
      ``swarm_question`` and ``swarm_answer`` and the stored values follow. A table whose ``swarm_`` twin already exists is left alone.
    Inputs: conn (sqlite3.Connection). Output: None. Example: rename_legacy(conn)
    """
    have = _tables(conn)
    todo = [n for n in LEGACY_TABLES if f"pack_{n}" in have and f"swarm_{n}" not in have]
    if not todo:
        return
    for n in todo:
        conn.execute(f"ALTER TABLE pack_{n} RENAME TO swarm_{n}")
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'pack\\_%' ESCAPE '\\' AND sql IS NOT NULL").fetchall():
        conn.execute(f'DROP INDEX IF EXISTS "{name}"')
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'swarm_deliveries'").fetchone()
    if row and "pack_question" in row[0]:
        new_sql = row[0].replace("pack_question", "swarm_question").replace("pack_answer", "swarm_answer")
        new_sql = re.sub(r'CREATE TABLE\s+"?swarm_deliveries"?', "CREATE TABLE swarm_deliveries_new", new_sql, count=1)
        conn.execute(new_sql)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(swarm_deliveries)")]
        pick = ", ".join("CASE source WHEN 'pack_question' THEN 'swarm_question' WHEN 'pack_answer' THEN 'swarm_answer' ELSE source END"
                         if c == "source" else c for c in cols)
        conn.execute(f"INSERT INTO swarm_deliveries_new ({', '.join(cols)}) SELECT {pick} FROM swarm_deliveries")
        conn.execute("DROP TABLE swarm_deliveries")
        conn.execute("ALTER TABLE swarm_deliveries_new RENAME TO swarm_deliveries")
    have = _tables(conn)
    for statement in _DDL_ALL:
        m = re.match(r"CREATE (?:UNIQUE )?INDEX IF NOT EXISTS \w+ ON (\w+)", statement)
        if m and m.group(1) in have:
            conn.execute(statement)
