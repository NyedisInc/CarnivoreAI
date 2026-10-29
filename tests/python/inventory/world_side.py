
from __future__ import annotations

import json
from types import SimpleNamespace

from src.core.inventory.model import MAIN_STORE
from src.core.stats.plugin.extract import project_key
from src.core.work import tables
from tests.python.inventory.world import (A, APP_A, B, CONV_A, CONV_D, NOW, P, UUID_A, UUID_B, UUID_D, Seeder)


W = {legacy: new for new, legacy in tables.LEGACY_NAMES.items()}


def seed_task_manager(w: SimpleNamespace) -> None:
    s = Seeder(w.ledger, MAIN_STORE, w.main)
    w.huddle = s
    list1, list2 = str(w.p1), str(w.p2)
    item = dict(text="t", position=1, created_by="joe", state="open", created_at=1.0, updated_at=1.0, created_seq=1, seq=1)
    w.item_a = s.put(W["items"], (A, P), list_key=list1, owner_session_key=UUID_A, **item)
    w.item_b = s.put(W["items"], (B, P), list_key=list1, owner_session_key=UUID_B, **item)
    w.item_p = s.put(W["items"], (P,), list_key=list1, **item)
    s.put(W["items"], (A,), list_key="all", tagged_session_key=UUID_A, **item)
    w.item_d = s.put(W["items"], (), list_key=list2, owner_session_key=UUID_D, **item)
    for table, extra in (("messages", dict(author="joe", kind="say", text="m", created_at=1.0, seq=1, parts='{"files": []}')),
                         ("item_lineage", dict(list_key=list1, at=1.0, from_state="open", to_state="working", by="joe")),
                         ("card_events", dict(list_key=list1, at=1.0, kind="state", by="joe")),
                         ("blockers", dict(kind="k", text="t", created_by="joe", created_at=1.0)),
                         ("item_nudges", dict(count=1)),
                         ("item_triggers", dict(kind="at", fire_at=1.0, updated_at=1.0)),
                         ("item_waits", dict(waiting_on="x", kind="k", set_by="joe", set_at=1.0, status="open")),
                         ("message_receipts", dict(message_id=1, delivered_at=1.0))):
        s.put(W[table], (A, P), item_id=w.item_a, **extra)
        s.put(W[table], (), item_id=w.item_d, **{**extra, **({"message_id": 2} if table == "message_receipts" else {})})
    s.put(W["write_actors"], (A, P), item_id=w.item_a, op="add", actor_key=UUID_A, actor_session_id=UUID_A, cross_project=0, at=1.0)
    s.put(W["write_actors"], (A,), item_id=w.item_d, op="add", actor_key=UUID_A, actor_session_id=UUID_A, cross_project=0, at=1.0)
    s.put(W["write_actors"], (), item_id=w.item_d, op="add", actor_key=UUID_D, actor_session_id=UUID_D, cross_project=0, at=1.0)
    s.put(W["callers"], (A,), session_id=UUID_A, list_key="all", at=1.0)
    s.put(W["callers"], (P,), session_id=UUID_D, list_key=list1, at=1.0)
    s.put(W["callers"], (), session_id=UUID_D, list_key=list2, at=1.0)
    s.put(W["reads"], (A,), session_id=UUID_A, list_key="all", cursor=1)
    s.put(W["reads"], (B, P), session_id=UUID_B, list_key=list1, cursor=1)
    s.put(W["session_prefs"], (A,), session_uuid=UUID_A)
    s.put(W["session_prefs"], (), session_uuid=UUID_D)
    for table, key, extra in (("list_prefs", "list_key", {}), ("card_rules", "list_key", {}),
                              ("card_suggestions", "list_key", dict(card_id=1, by_agent=1, reason="r", at=1.0)),
                              ("card_deals", "project_key", dict(state="waiting", requested_at=1.0)),
                              ("inbox", "list_key", dict(raw_text="r", author="joe", created_at=1.0, status="new")),
                              ("item_groups", "list_key", dict(name="g", position=0, created_by="joe", created_at=1.0, updated_at=1.0, seq=1)),
                              ("tells", "list_key", dict(cursor=1, target="t")), ("tell_picks", "list_key", dict(target_key="t")),
                              ("held_tells", "list_key", dict(target="t", since=1.0, deadline=2.0)),
                              ("project_roles", "list_key", dict(lead_key=UUID_A))):
        s.put(W[table], (P,), **{key: list1}, **extra)
        s.put(W[table], (), **{key: list2}, **extra)
    s.put(W["card_grants"], (P,), scope=f"project:{w.p1}", slots=2, set_by="owner", set_at=1.0)
    s.put(W["card_grants"], (), scope=f"project:{w.p2}", slots=2, set_by="owner", set_at=1.0)


def seed_small_stores(w: SimpleNamespace) -> None:
    book = Seeder(w.ledger, "bookmarks.db", w.side["bookmarks.db"])
    for session, row, conv, tags in ((UUID_A, w.row_a, CONV_A, (A,)), (UUID_D, w.row_d, CONV_D, ())):
        book.put("bookmarks", tags, session_uuid=session, session_row_id=row, claude_session_uuid=conv, entry_uuid="e", created_by="owner", created_at=NOW)
    Seeder(w.ledger, "attention_history.db", w.side["attention_history.db"]).put("attention_events", (A,), session_uuid=UUID_A, kind="question", at=NOW)
    deep = Seeder(w.ledger, "deepsearch.db", w.side["deepsearch.db"])
    live = deep.put("session_search_live", (A,), conversation_id=CONV_A, path="/h/projects/-p/a.jsonl", file_kind="conversation", family="claude",
                    base_offset=0, base_line=0, indexed_offset=0, indexed_lines=0, last_serial=0, last_serial_offset=0, rows=1,
                    filter_version="v", in_scope=1, scope="human", created_at=NOW, indexed_at=NOW)
    deep.put("session_search_rows", (), doc_id=0, frame_index=0, frame_offset=0, frame_len=1, frame_first_line=0, line=0, kind="user", live_id=live)
    deep.put("session_search_folders", (), live_id=live, folder="/h/projects/-p")
    deep.sql("INSERT INTO session_search_fts (rowid, body) VALUES (1, 'hello')")
    deep.put("session_search_live", (), conversation_id=CONV_D, path="/h/projects/-q/d.jsonl", file_kind="conversation", family="claude",
             base_offset=0, base_line=0, indexed_offset=0, indexed_lines=0, last_serial=0, last_serial_offset=0, rows=1,
             filter_version="v", in_scope=1, scope="human", created_at=NOW, indexed_at=NOW)
    seed_automations(w)
    seed_stats(w)
    path_a = f"/h/.claude/projects/-p/{CONV_A}.jsonl"
    cursors = Seeder(w.ledger, "reader_state.db", w.side["reader_state.db"])
    for path, tags in ((path_a, (A,)), (f"/h/.claude/projects/-q/{CONV_D}.jsonl", ())):
        cursors.put("reader_state", tags, reader="r", path=path, version="v", size=1, mtime_ns=1, off=0, head=b"", tail=b"", ino=1, payload="{}", written_at=1.0)
    fires = Seeder(w.ledger, "skill_fires.db", w.side["skill_fires.db"])
    fires.put("skill_fires", (A,), path=path_a, off=0, skill="s", harness="claude", profile="p", session_key=CONV_A, source="x")
    fires.put("skill_fires", (), path=f"/h/.claude/projects/-q/{CONV_D}.jsonl", off=0, skill="s", harness="claude", profile="p", session_key=CONV_D, source="x")
    fires.put("skill_fire_cursors", (A,), path=path_a, size=1, head=b"", off=0)


def seed_automations(w: SimpleNamespace) -> None:
    s = Seeder(w.ledger, "automations.db", w.side["automations.db"])
    message = lambda uuid: {"kind": "session_message", "session_uuid": uuid, "text": "go"}  # noqa: E731
    rows = (
        ("auto-1", w.p1, {"kind": "recipe", "recipe": "scrooge"}, (P,), UUID_A, (A, P)),
        ("auto-2", w.p2, message(UUID_D), (), UUID_D, ()),
        ("auto-3", None, message(UUID_A), (A,), UUID_A, (A,)),
        ("auto-4", None, {"kind": "agent", "folder": w.root1}, (P,), UUID_D, (P,)),
        ("auto-5", w.p2, {"kind": "sequence", "steps": [{"kind": "recipe", "recipe": "scrooge"}, message(UUID_B)]}, (B,), UUID_D, (B,)),
    )
    for key, project, target, tags, session, woke in rows:
        s.put("automations", tags, automation_id=key, name=key, name_key=key, enabled=1, cron="* * * * *", target=json.dumps(target),
              delivery="{}", revision=1, created_by="owner", created_at=1.0, updated_at=1.0, project_id=project)
        s.put("automation_changes", tags, automation_id=key, action="create", at=1.0, actor="owner")
        s.put("runs", tags, run_id=f"run-{key}", automation_id=key, trigger="cron", status="done", created_at=1.0)
        s.put("run_sessions", woke, run_id=f"run-{key}", session_uuid=session,
              session_row_id={UUID_A: w.row_a, UUID_D: w.row_d}[session])


def seed_stats(w: SimpleNamespace) -> None:
    s = Seeder(w.ledger, "stats.db", w.side["stats.db"])
    names = {}
    keys = {"Proj One": project_key(w.root1), "Proj Two": project_key(w.root2)}
    for name, tags in (("Proj One", (P,)), ("Proj Two", ())):
        names[name] = s.put("dim_project", tags, name=keys[name])
    model = s.put("dim_model", (), name="m1")
    for conv, name, tags, row in ((CONV_A, "Proj One", (A,), 1), (CONV_D, "Proj Two", (), 2)):
        src = s.put("dim_source", tags, path_key=row, conversation_id=conv, provider="claude", agent_kind="main")
        live = s.put("dim_live", tags, host="local", provider="claude", conversation_id=conv, project=keys[name], model="m1", agent_kind="main")
        usage = tags + ((P,) if tags else ())
        for table in ("usage_minute", "usage_hour"):
            s.put(table, usage, t=1, src=src, model=model, project=names[name])
        for table in ("counter_minute", "counter_hour"):
            s.put(table, usage, t=1, src=src, model=model, project=names[name], counter=1, key=1, value=1)
        s.put("file_state", tags, src=src, last_t=1, wide=0, state="{}")
        for table in ("activity_minute", "activity_hour"):
            s.put(table, tags, t=1, live=live)
    s.put("dim_live", (A,), host="local", provider="shell", conversation_id=f"session:{APP_A}", project=keys["Proj One"], model="", agent_kind="session")
    s.put("dim_live", (), host="local", provider="shell", conversation_id="session:ses_other", project=keys["Proj Two"], model="", agent_kind="session")
    seed_pipeline_state(w, s, keys)


def seed_pipeline_state(w: SimpleNamespace, stats: Seeder, keys: dict) -> None:
    deep = Seeder(w.ledger, "deepsearch.db", w.side["deepsearch.db"])
    cursor = dict(family="claude", file_kind="conversation", offset=0, lines=0, inherit_state="none", inherited_start=0, inherited_end=0, updated_at=1.0)
    for seeder in (deep, stats):
        seeder.put("plugin_cursors", (A,), path=f"/h/.claude/projects/-p/{CONV_A}.jsonl", conversation_id=CONV_A, **cursor)
        seeder.put("plugin_cursors", (), path=f"/h/.claude/projects/-q/{CONV_D}.jsonl", conversation_id=CONV_D, **cursor)
    stats.put("rollup_rev", (A,), conversation_id=CONV_A, hour=1, rev=1)
    stats.put("rollup_rev", (), conversation_id=CONV_D, hour=1, rev=1)
    for name, tags in (("Proj One", (P,)), ("Proj Two", ())):
        stats.put("stats_git_markers", tags, project=keys[name], commit_id="c1", filename="CLAUDE.md")
        stats.put("stats_git_progress", tags, project=keys[name], filename="CLAUDE.md", head="h", offset=0, complete=1)
        stats.put("stats_annotations", tags, id=f"ann-{name}", revision=1, occurred_at=1, kind="rule", label="l",
                  scope_json=f'{{"project": "{keys[name]}"}}', basis="observed", created_at=1, updated_at=1)
    stats.put("stats_annotations", (), id="ann-global", revision=1, occurred_at=1, kind="note", label="l", scope_json="{}",
              basis="manual", created_at=1, updated_at=1)
