from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.config.provider_accounts import ProviderAccount
from src.core.db import connect, transaction
from src.core.pipeline import contract as PK
from src.core.pipeline import deliver, observe, plugin_db as host
from src.core.pipeline.contract import Appended
from src.core.stats import account_owner, queries
from src.core.stats.plugin import extract, ingest
from src.core.stats.plugin.pipeline_plugin import STATS as STATS_PLUGIN
from src.core.stats.store import StatsStore
from src.core.transcript_contract import FAMILY_AGY, parse_range
from src.core.transcript_manifest import refresh as manifest_refresh
from src.models.stats import QueryRequest, StatsFilters

CONV_AGY = "aaaaaaaa-1111-4222-8333-444444444444"
CONV_CODEX = "bbbbbbbb-1111-4222-8333-444444444444"
T0 = 1795700400


def _iso(t: int) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def _blob(records) -> bytes:
    return b"".join((json.dumps(r) + "\n").encode() for r in records)


def test_parse_range_and_classify_agy_transcript():
    path = f"/Users/test/.gemini/antigravity-cli/brain/{CONV_AGY}/.system_generated/logs/transcript.jsonl"
    target = observe.classify(path)
    assert target is not None
    assert target.family == PK.FAMILY_AGY
    assert target.conversation_id == CONV_AGY
    assert target.file_kind == PK.FILE_CONVERSATION

    raw = _blob([
        {"step_index": 0, "type": "USER_INPUT", "created_at": _iso(T0), "content": "hi"},
        {"step_index": 1, "type": "PLANNER_RESPONSE", "created_at": _iso(T0 + 5),
         "model": "gemini-4-neon-high", "input_tokens": 1200, "cache_read_tokens": 300, "output_tokens": 250,
         "tool_calls": [{"name": "read_file", "args": {}}]},
    ])
    rng = parse_range(raw, 0, FAMILY_AGY)
    assert len(rng.lines) == 2
    assert rng.lines[0].parsed.family == FAMILY_AGY
    assert rng.lines[0].parsed.kind == "USER_INPUT"
    assert rng.lines[0].parsed.known is True
    assert rng.lines[1].parsed.kind == "PLANNER_RESPONSE"


def test_agy_stats_ingest_query_and_provider_filter(tmp_path):
    store = StatsStore(tmp_path)
    store.initialize()
    conn = host.open_db(tmp_path, STATS_PLUGIN)
    path = f"/Users/test/.gemini/antigravity-cli/brain/{CONV_AGY}/.system_generated/logs/transcript.jsonl"
    ingest.set_account_resolver(lambda provider, cid, p=None: "agy-alice-example-com" if provider == "antigravity" else None)
    ingest.set_project_resolver(lambda provider, cid: "/work/carnivore" if cid == CONV_AGY else None)
    try:
        records = [
            {"step_index": 0, "type": "USER_INPUT", "created_at": _iso(T0), "content": "audit stats"},
            {"step_index": 1, "type": "PLANNER_RESPONSE", "created_at": _iso(T0 + 10),
             "model": "gemini-4-neon-high", "input_tokens": 11500, "cache_read_tokens": 0, "output_tokens": 500,
             "tool_calls": [{"name": "read_file", "args": {}}, {"name": "run_command", "args": {}}]},
            {"step_index": 1, "type": "PLANNER_RESPONSE", "created_at": _iso(T0 + 12),
             "model": "gemini-4-neon-high", "input_tokens": 11500, "cache_read_tokens": 0, "output_tokens": 600},
            {"step_index": 2, "type": "PLANNER_RESPONSE", "created_at": _iso(T0 + 65),
             "model": "gemini-4-hydrogen-tiered-high", "input_tokens": 2000, "cache_read_tokens": 11500,
             "output_tokens": 400},
            {"step_index": 3, "type": "CHECKPOINT", "created_at": _iso(T0 + 70)},
        ]
        rng = parse_range(_blob(records), 0, FAMILY_AGY)
        event = Appended(CONV_AGY, PK.FAMILY_AGY, path, PK.FILE_CONVERSATION, 0, rng.complete_end, rng.lines, 0, 0, None, "test")
        with transaction(conn):
            ingest.appended(conn, event, now=T0 + 120)
    finally:
        ingest.set_account_resolver(None)
        ingest.set_project_resolver(None)
        conn.close()

    req = QueryRequest.model_validate({
        "metric": "total_tokens",
        "operation": "ranking",
        "group_by": "model",
        "from": _iso(T0 - 60),
        "to": _iso(T0 + 3600),
        "filters": {"provider": "antigravity"},
    })
    ans = queries.execute(store, req)
    by_model = {row["key"]: (row["label"], row["value"]) for row in ans["ranking"]}
    assert by_model["gemini-4-hydrogen-tiered-high"] == ("Gemini 4 Hydrogen Tiered High", 13900)
    assert by_model["gemini-4-neon-high"] == ("Gemini 4 Neon High", 12100)

    sum_req = QueryRequest.model_validate({
        "metric": "total_tokens",
        "operation": "summary",
        "from": _iso(T0 - 60),
        "to": _iso(T0 + 3600),
        "filters": {"provider": "antigravity"},
    })
    assert queries.execute(store, sum_req)["summary"]["value"] == 26000

    tools_req = QueryRequest.model_validate({
        "metric": "tool_calls",
        "operation": "ranking",
        "group_by": "key",
        "from": _iso(T0 - 60),
        "to": _iso(T0 + 3600),
        "filters": {"provider": "antigravity"},
    })
    tools_ans = queries.execute(store, tools_req)
    assert {r["key"]: r["value"] for r in tools_ans["ranking"]} == {"read_file": 1, "run_command": 1}

    with store.connect(readonly=True) as ro:
        row = ro.execute("SELECT provider, account_id FROM dim_source WHERE conversation_id = ?", (CONV_AGY,)).fetchone()
        assert tuple(row) == ("antigravity", "agy-alice-example-com")
        proj = ro.execute("SELECT DISTINCT project FROM minute_usage WHERE conversation_id = ?", (CONV_AGY,)).fetchone()
        assert proj[0] == extract.project_key("/work/carnivore")


def test_codex_and_antigravity_account_attribution_and_backfill(tmp_path, monkeypatch):
    default_codex = tmp_path / "default-codex"
    managed_codex = tmp_path / "managed-codex"
    (default_codex / "sessions" / "2026" / "11" / "26").mkdir(parents=True)
    (managed_codex / "sessions" / "2026" / "11" / "26").mkdir(parents=True)
    p_default = default_codex / "sessions" / "2026" / "11" / "26" / f"rollout-2026-11-26T10-00-00-{CONV_CODEX}.jsonl"
    p_managed = managed_codex / "sessions" / "2026" / "11" / "26" / "rollout-2026-11-26T10-05-00-cccccccc-1111-4222-8333-444444444444.jsonl"
    p_default.write_text("{}\n")
    p_managed.write_text("{}\n")

    agy_state = tmp_path / "agy-state"
    agy_state.mkdir()
    (agy_state / "9999.json").write_text(json.dumps({
        "conversation_id": CONV_AGY,
        "email": "Alice@Example.com",
        "cwd": "/work/argent",
        "written_at": 1795700500.0,
    }))

    accounts = [
        ProviderAccount(id="codex-personal", name="Codex Personal", provider="codex", codex_home=str(default_codex)),
        ProviderAccount(id="codex-nyedis", name="Codex Nyedis", provider="codex", codex_home=str(managed_codex)),
        ProviderAccount(id="agy-only", name="Google Ultra", provider="antigravity"),
    ]
    monkeypatch.setattr(account_owner.accounts_store, "list_accounts", lambda _p: accounts)
    monkeypatch.setattr(account_owner.poller_scan, "with_auto_default", lambda rows: rows)

    resolver = account_owner.AccountAttribution(tmp_path / "config.json", state_dir=tmp_path)
    assert resolver("codex", CONV_CODEX, str(p_default)) == "codex-personal"
    assert resolver("codex", "cccccccc-1111-4222-8333-444444444444", str(p_managed)) == "codex-nyedis"
    assert resolver("antigravity", CONV_AGY) == "agy-alice-example-com"
    assert resolver("antigravity", "dddddddd-1111-4222-8333-444444444444") == "agy-only"

    proj = account_owner.ProjectAttribution(tmp_path)
    assert proj("antigravity", CONV_AGY) == "/work/argent"

    store = StatsStore(tmp_path)
    store.initialize()
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO dim_source (path_key, conversation_id, provider, agent_kind, account_id) VALUES (?,?,?,?,NULL)",
            (extract.path_key(str(p_managed)), "cccccccc-1111-4222-8333-444444444444", "codex", "session"),
        )
        conn.execute(
            "INSERT INTO plugin_cursors (path, conversation_id, family, file_kind, offset, lines, inherit_state, inherited_start, inherited_end, updated_at) "
            "VALUES (?, ?, 'codex', 'conversation', 3, 1, 'closed', 0, 0, 1)",
            (str(p_managed), "cccccccc-1111-4222-8333-444444444444"),
        )
    updated = account_owner.backfill_unattributed_accounts(store, resolver)
    assert updated == 1
    with store.connect(readonly=True) as ro:
        acct = ro.execute(
            "SELECT account_id FROM dim_source WHERE conversation_id = ?",
            ("cccccccc-1111-4222-8333-444444444444",),
        ).fetchone()[0]
        assert acct == "codex-nyedis"


def test_manifest_codex_session_roots_includes_managed_profiles(tmp_path, monkeypatch):
    default_home = tmp_path / "codex-default"
    managed_home = tmp_path / "codex-managed"
    (default_home / "sessions").mkdir(parents=True)
    (managed_home / "sessions").mkdir(parents=True)

    import src.core.attention.codex_gather as cg
    import src.core.provider_ledger.accounts_store as acc_store

    monkeypatch.setattr(cg, "DEFAULT_CODEX_HOME", str(default_home))
    monkeypatch.setattr(
        acc_store,
        "list_accounts",
        lambda _p: [ProviderAccount(id="team-codex", name="Team Codex", provider="codex", codex_home=str(managed_home))],
    )
    roots = manifest_refresh._codex_session_roots(None)
    assert [r.resolve() for r in roots] == [(default_home / "sessions").resolve(), (managed_home / "sessions").resolve()]
    assert manifest_refresh._codex_session_roots("") == []


def test_stats_filters_accepts_antigravity():
    f = StatsFilters(provider="antigravity")
    assert f.provider == "antigravity"
    with pytest.raises(ValueError):
        StatsFilters(provider="unknown")


def test_pipeline_deliver_file_ingests_agy_transcript_end_to_end(tmp_path):
    brain = tmp_path / "brain" / CONV_AGY / ".system_generated" / "logs"
    brain.mkdir(parents=True)
    transcript = brain / "transcript.jsonl"
    transcript.write_bytes(_blob([
        {"step_index": 0, "type": "USER_INPUT", "created_at": _iso(T0), "content": "ship it"},
        {"step_index": 1, "type": "PLANNER_RESPONSE", "created_at": _iso(T0 + 5),
         "model": "gemini-4-neon-high", "input_tokens": 5000, "cache_read_tokens": 1000, "output_tokens": 300,
         "tool_calls": [{"name": "edit_file", "args": {}}]},
    ]))
    target = observe.classify(str(transcript))
    assert target is not None and target.family == PK.FAMILY_AGY

    run = deliver.PluginRun(STATS_PLUGIN)
    delivery = deliver.Delivery(tmp_path, [run], trigger="test")
    try:
        deliver.deliver_file(delivery, target)
    finally:
        delivery.close_reads()

    assert run.failed is None
    assert run.events == 1
    store = StatsStore(tmp_path)
    with store.connect(readonly=True) as ro:
        rows = ro.execute(
            "SELECT provider, model, input_tokens, cache_read_tokens, output_tokens FROM minute_usage"
        ).fetchall()
        assert [tuple(r) for r in rows] == [("antigravity", "gemini-4-neon-high", 5000, 1000, 300)]


def _init_sessions_db(state_dir: Path) -> Path:
    from src.core.db import db_path_for

    app_db = db_path_for(state_dir)
    with connect(app_db, create=True) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS sessions ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, session_uuid TEXT, working_dir TEXT, tmux_socket TEXT, "
            "tmux_name TEXT, agent_type TEXT, agent_family TEXT, claude_session_uuid TEXT, title TEXT, lifecycle TEXT)"
        )
    return app_db


def test_multilevel_agy_and_codex_subagents_fold_into_root_agent_name(tmp_path):
    from src.core.stats import agent_names

    agent_names.forget()
    app_db = _init_sessions_db(tmp_path)
    with connect(app_db) as db:
        db.execute(
            "INSERT INTO sessions (session_uuid, working_dir, tmux_socket, tmux_name, agent_type, agent_family, "
            "claude_session_uuid, title, lifecycle) VALUES (?, ?, 's', 'carnivore_cv_plugins', 'antigravity', 'custom', ?, 'Cv-Plugins', 'running')",
            ("sess-agy-1", "/work/cloudecode", CONV_AGY),
        )
        db.execute(
            "INSERT INTO sessions (session_uuid, working_dir, tmux_socket, tmux_name, agent_type, agent_family, "
            "claude_session_uuid, title, lifecycle) VALUES (?, ?, 's', 'carnivore_codex_1', 'codex-yolo', 'codex', ?, 'Codex-Main', 'running')",
            ("sess-codex-1", "/work/cloudecode", CONV_CODEX),
        )

    orch_id = "11111111-1111-4222-8333-444444444444"
    worker_id = "22222222-1111-4222-8333-444444444444"
    codex_sub_id = "33333333-1111-4222-8333-444444444444"

    store = StatsStore(tmp_path)
    store.initialize()
    conn = host.open_db(tmp_path, STATS_PLUGIN)
    ingest.set_project_resolver(account_owner.ProjectAttribution(tmp_path))
    try:
        root_records = [
            {"step_index": 0, "type": "USER_INPUT", "created_at": _iso(T0), "content": "run teamwork"},
            {"step_index": 1, "type": "PLANNER_RESPONSE", "created_at": _iso(T0 + 5),
             "model": "gemini-4-neon-high", "input_tokens": 1000, "cache_read_tokens": 0, "output_tokens": 100},
        ]
        orch_records = [
            {"step_index": 0, "type": "SYSTEM_MESSAGE", "created_at": _iso(T0 + 10),
             "content": f"<SYSTEM_MESSAGE>\n[Message] timestamp={_iso(T0 + 10)} sender={CONV_AGY} priority=HIGH content=go"},
            {"step_index": 1, "type": "PLANNER_RESPONSE", "created_at": _iso(T0 + 15),
             "model": "gemini-4-hydrogen-tiered-high", "input_tokens": 2000, "cache_read_tokens": 0, "output_tokens": 200},
        ]
        worker_records = [
            {"step_index": 0, "type": "SYSTEM_MESSAGE", "created_at": _iso(T0 + 20),
             "content": f"<SYSTEM_MESSAGE>\n[Message] timestamp={_iso(T0 + 20)} sender={orch_id} priority=HIGH content=build"},
            {"step_index": 1, "type": "PLANNER_RESPONSE", "created_at": _iso(T0 + 25),
             "model": "gemini-4-hydrogen-tiered-high", "input_tokens": 3000, "cache_read_tokens": 0, "output_tokens": 300},
        ]
        codex_sub_records = [
            {"type": "session_meta", "timestamp": _iso(T0 + 30), "payload": {
                "cwd": "/work/cloudecode", "thread_source": "subagent", "agent_role": "worker", "parent_thread_id": CONV_CODEX}},
            {"type": "turn_context", "timestamp": _iso(T0 + 31), "payload": {"model": "gpt-6-astra"}},
            {"type": "event_msg", "timestamp": _iso(T0 + 35), "payload": {
                "type": "token_count", "info": {"total_token_usage": {
                    "input_tokens": 500, "cached_input_tokens": 0, "output_tokens": 50}}}},
        ]

        for cid, recs in ((CONV_AGY, root_records), (orch_id, orch_records), (worker_id, worker_records)):
            rng = parse_range(_blob(recs), 0, FAMILY_AGY)
            p = f"/Users/test/.gemini/antigravity-cli/brain/{cid}/.system_generated/logs/transcript.jsonl"
            ev = Appended(cid, PK.FAMILY_AGY, p, PK.FILE_CONVERSATION, 0, rng.complete_end, rng.lines, 0, 0, None, "test")
            with transaction(conn):
                ingest.appended(conn, ev, now=T0 + 60)

        rng_c = parse_range(_blob(codex_sub_records), 0, PK.FAMILY_CODEX)
        ev_c = Appended(codex_sub_id, PK.FAMILY_CODEX, f"/t/rollout-2026-11-26T10-00-00-{codex_sub_id}.jsonl",
                        PK.FILE_CONVERSATION, 0, rng_c.complete_end, rng_c.lines, 0, 0, None, "test")
        with transaction(conn):
            ingest.appended(conn, ev_c, now=T0 + 60)
    finally:
        ingest.set_project_resolver(None)
        conn.close()

    agent_names.forget()
    req = QueryRequest.model_validate({
        "metric": "total_tokens",
        "operation": "ranking",
        "group_by": "conversation_id",
        "from": _iso(T0 - 60),
        "to": _iso(T0 + 3600),
    })
    ans = queries.execute(store, req)
    by_label = {row["label"]: row["value"] for row in ans["ranking"]}
    assert by_label == {"Cv-Plugins": 6600, "Codex-Main": 550}
    with store.connect(readonly=True) as ro:
        projs = {r[0] for r in ro.execute("SELECT DISTINCT project FROM minute_usage WHERE provider = 'antigravity'").fetchall()}
        assert projs == {extract.project_key("/work/cloudecode")}


def test_backfill_subagent_parents_upgrades_existing_agy_and_codex_rows(tmp_path):
    from src.core.stats import agent_names

    agent_names.forget()
    app_db = _init_sessions_db(tmp_path)
    with connect(app_db) as db:
        db.execute(
            "INSERT INTO sessions (session_uuid, working_dir, tmux_socket, tmux_name, agent_type, agent_family, "
            "claude_session_uuid, title, lifecycle) VALUES (?, ?, 's', 'carnivore_cv_plugins', 'antigravity', 'custom', ?, 'Cv-Plugins', 'running')",
            ("sess-agy-bf", "/work/cloudecode", CONV_AGY),
        )

    child_id = "44444444-1111-4222-8333-444444444444"
    child_dir = tmp_path / "brain" / child_id / ".system_generated" / "logs"
    child_dir.mkdir(parents=True)
    child_path = child_dir / "transcript.jsonl"
    child_path.write_bytes(_blob([
        {"step_index": 0, "type": "SYSTEM_MESSAGE", "created_at": _iso(T0),
         "content": f"[Message] timestamp={_iso(T0)} sender={CONV_AGY} priority=HIGH content=work"},
        {"step_index": 1, "type": "PLANNER_RESPONSE", "created_at": _iso(T0 + 5),
         "model": "gemini-4-neon-high", "input_tokens": 400, "cache_read_tokens": 0, "output_tokens": 100},
    ]))

    store = StatsStore(tmp_path)
    store.initialize()
    with store.connect() as conn:
        conn.execute("INSERT OR IGNORE INTO dim_model(name) VALUES ('gemini-4-neon-high')")
        conn.execute("INSERT OR IGNORE INTO dim_project(name) VALUES ('')")
        mid = conn.execute("SELECT id FROM dim_model WHERE name='gemini-4-neon-high'").fetchone()[0]
        pid = conn.execute("SELECT id FROM dim_project WHERE name=''").fetchone()[0]
        cur = conn.execute(
            "INSERT INTO dim_source (path_key, conversation_id, provider, agent_kind, parent_conversation_id) "
            "VALUES (?, ?, 'antigravity', 'session', NULL)",
            (extract.path_key(str(child_path)), child_id),
        )
        src_id = cur.lastrowid
        conn.execute(
            "INSERT INTO usage_minute (t, src, model, project, input, cache_write, cache_read, output, cost_nano, messages, priced, pv) "
            "VALUES (?, ?, ?, ?, 400, 0, 0, 100, NULL, 1, 0, NULL)",
            (T0, src_id, mid, pid),
        )
        conn.execute(
            "INSERT INTO plugin_cursors (path, conversation_id, family, file_kind, offset, lines, inherit_state, inherited_start, inherited_end, updated_at) "
            "VALUES (?, ?, 'agy', 'conversation', 100, 2, 'closed', 0, 0, 1)",
            (str(child_path), child_id),
        )
        conn.execute(
            "INSERT INTO dim_source (path_key, conversation_id, provider, agent_kind, parent_conversation_id) "
            "VALUES (?, ?, 'codex', 'session', ?)",
            (extract.path_key("/t/rollout-codex-sub.jsonl"), "55555555-1111-4222-8333-444444444444", CONV_CODEX),
        )

    changed = account_owner.backfill_subagent_parents(store, account_owner.ProjectAttribution(tmp_path))
    assert changed >= 2
    with store.connect(readonly=True) as ro:
        agy_row = ro.execute("SELECT agent_kind, parent_conversation_id FROM dim_source WHERE conversation_id = ?", (child_id,)).fetchone()
        assert tuple(agy_row) == ("subagent", CONV_AGY)
        codex_row = ro.execute("SELECT agent_kind FROM dim_source WHERE conversation_id = ?", ("55555555-1111-4222-8333-444444444444",)).fetchone()
        assert codex_row[0] == "subagent"
        proj = ro.execute("SELECT project FROM minute_usage WHERE conversation_id = ?", (child_id,)).fetchone()[0]
        assert proj == extract.project_key("/work/cloudecode")
