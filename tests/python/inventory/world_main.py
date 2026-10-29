
from __future__ import annotations

from types import SimpleNamespace

from tests.python.inventory.world import (A, APP_A, APP_D, B, CONV_A, CONV_A0, CONV_B, CONV_D, NOW, P, TMUX_A, UUID_A,
                                          UUID_B, UUID_D)


def seed_conversations(w: SimpleNamespace) -> None:
    s = w.main_seed
    s.put("session_notes", (A,), session_uuid=UUID_A, body="a", revision=1, updated_at=NOW)
    s.put("session_notes", (), session_uuid=UUID_D, body="d", revision=1, updated_at=NOW)
    group = s.put("session_groups", (A,), group_uuid="g-1", name="g", position=0, created_at=NOW, updated_at=NOW)
    s.put("session_group_membership", (A,), session_uuid=UUID_A, group_id=group, position=0, added_at=NOW)
    s.put("session_group_styles", (A,), group_id=group, updated_at=NOW)
    s.put("session_group_members", (A,), tmux_name=TMUX_A, group_id=group, added_at=NOW)
    layout = s.put("layouts", (A,), layout_uuid="l-1", name="l", name_fold="l", position=0, shape="x", revision=1,
                   created_at=NOW, updated_at=NOW)
    s.put("layout_members", (A,), layout_id=layout, session_row_id=w.row_a, position=0)
    s.put("layout_broadcast_off", (A,), layout_id=layout, session_row_id=w.row_a, updated_at=NOW)
    s.put("layout_styles", (A,), layout_uuid="l-1", updated_at=NOW)
    for conv in (CONV_A, CONV_A0):
        s.put("conversation_index", (A,), conversation_id=conv, session_uuid=UUID_A, project_id=w.p1, captured_at=NOW, updated_at=NOW)
        s.put("conversation_milestones", (A,), conversation_id=conv, session_uuid=UUID_A, kind="start", source="scan", created_at=NOW)
    s.put("conversation_index", (B,), conversation_id=CONV_B, session_uuid=UUID_B, project_id=w.p1, captured_at=NOW, updated_at=NOW)
    s.put("conversation_index", (P,), conversation_id="orphan-conv-0001", session_uuid="gone-session", project_id=w.p1,
          captured_at=NOW, updated_at=NOW)
    s.put("conversation_index", (), conversation_id=CONV_D, session_uuid=UUID_D, project_id=w.p2, captured_at=NOW, updated_at=NOW)
    job = s.put("pipeline_jobs", (A,), conversation_id=CONV_A, session_uuid=UUID_A, event="stop", state="done", created_at=NOW, updated_at=NOW)
    s.put("pipeline_stage_runs", (A,), job_id=job, stage="s", status="done")
    s.put("pipeline_jobs", (), conversation_id=CONV_D, session_uuid=UUID_D, event="stop", state="done", created_at=NOW, updated_at=NOW)
    s.put("transcript_files", (A,), path=f"/h/.claude/projects/-w-proj1/{CONV_A}.jsonl", conversation_id=CONV_A, family="claude",
          root="r", kind="conversation", status="present")
    s.put("transcript_files", (A,), path=f"/h/.claude/projects/-w-proj1/{CONV_A0}.jsonl", conversation_id=CONV_A0, family="claude",
          root="r", kind="conversation", status="present")
    s.put("transcript_files", (), path=f"/h/.claude/projects/-w-proj2/{CONV_D}.jsonl", conversation_id=CONV_D, family="claude",
          root="r", kind="conversation", status="present")
    archive = s.put("transcript_archives", (A,), archive_uuid="a-1", kind="session", claude_session_uuid=CONV_A,
                    source_path=f"-w-proj1/{CONV_A}.jsonl", root_session_id=w.row_a, line_ending="LF", has_trailing_newline=1,
                    root_state="rooted", growth_kind="initial")
    s.put("transcript_records", (A,), archive_id=archive, line_no=1, byte_offset=0, byte_length=1, status="ok")
    s.put("transcript_root_decisions", (A,), archive_id=archive, decided_at=NOW, decided_by="x", action="rooted", root_session_id=w.row_a)
    ours = s.put("message_transcripts", (A,), source_ref=f"M::claude-projects::-w-proj1/{CONV_A}.jsonl", session_ref=CONV_A,
                 session_ref_scheme="uuid", line_ending="LF", has_trailing_newline=1)
    other = s.put("message_transcripts", (), source_ref="M::claude-projects::-w-proj2/d.jsonl", session_ref=CONV_D,
                  session_ref_scheme="uuid", line_ending="LF", has_trailing_newline=1)
    only = s.put("message_bodies", (A,), identity_key="k-only", body_json="{}")
    both = s.put("message_bodies", (), identity_key="k-both", body_json="{}")
    line = {"line_status": "ok", "fidelity_outcome": "fidelity_verified"}
    s.put("message_appearances", (A,), transcript_id=ours, line_no=1, body_id=only, **line)
    s.put("message_appearances", (A,), transcript_id=ours, line_no=2, body_id=both, **line)
    s.put("message_appearances", (), transcript_id=other, line_no=1, body_id=both, **line)


def seed_graph(w: SimpleNamespace) -> None:
    s = w.main_seed
    for node_type, node_id in (("session", UUID_A), ("conversation", CONV_A), ("conversation", CONV_A0)):
        s.put("lineage_nodes", (A,), node_type=node_type, node_id=node_id, updated_at=NOW)
    s.put("lineage_nodes", (), node_type="conversation", node_id=CONV_D, updated_at=NOW)
    for parent, child, kind in ((("conversation", CONV_A0), ("conversation", CONV_A), "resume"),
                                (("conversation", CONV_A), ("subagent", f"{CONV_A}/agent-1"), "subagent"),
                                (("session", UUID_A), ("session", UUID_B), "spawned_by")):
        s.put("lineage_edges", (A,) + ((B,) if kind == "spawned_by" else ()), parent_type=parent[0], parent_id=parent[1],
              child_type=child[0], child_id=child[1], edge_kind=kind, created_at=NOW)
    s.put("lineage_edges", (), parent_type="conversation", parent_id=CONV_D, child_type="subagent", child_id=f"{CONV_D}/agent-9",
          edge_kind="subagent", created_at=NOW)
    s.put("agent_spawn_links", (A,), child_id=APP_A, parent_id="ses_parent01", parent_kind="session", spawned_at=1.0)
    s.put("agent_spawn_links", (), child_id=APP_D, parent_id="ses_parent01", parent_kind="session", spawned_at=1.0)
    s.put("crosstalk_messages", (A,), id="m-1", thread="t", sender_key=UUID_A, receiver_key=UUID_D, sender_uuid=UUID_A,
          receiver_uuid=UUID_D, sender_id=APP_A, receiver_id=APP_D, text="hi", status="delivered", created_at=1.0)
    s.put("crosstalk_messages", (), id="m-2", thread="t2", sender_key=UUID_D, receiver_key="other", sender_uuid=UUID_D,
          receiver_uuid="other", sender_id=APP_D, receiver_id="x", text="no", status="delivered", created_at=1.0)
    s.put("crosstalk_contacts", (A,), pair_key=f"{UUID_A}|{UUID_D}", left_key=UUID_A, right_key=UUID_D, granted_at=1.0, source="owner")
    s.put("crosstalk_watches", (A,), id="w-1", watcher_key=UUID_A, watcher_id=APP_A, target_key=UUID_D, target_id=APP_D,
          status="watching", created_at=1.0)
    s.put("mcp_events", (A,), call_id="c-1", started_at=1.0, tool="t", caller_kind="pane", caller_session_id=APP_A, caller_tmux=TMUX_A)
    s.put("mcp_events", (), call_id="c-2", started_at=1.0, tool="t", caller_kind="pane", caller_session_id=APP_D, caller_tmux="x")
    s.put("messaging_bindings", (A,), conversation_id="chat-1", session_uuid=UUID_A, direction="both", created_at=NOW)
    s.put("messaging_messages", (A,), provider_id="p", conversation_id="chat-1", session_uuid=UUID_A, direction="in", kind="message", status="queued")
    s.put("messaging_notices", (A,), conversation_id="chat-1", notice="n", episode=1, sent_at=NOW)
    s.put("messaging_notices", (), conversation_id="chat-9", notice="n", episode=1, sent_at=NOW)
    s.put("session_conversations", (A,), session_uuid=UUID_A, conversation_id=CONV_A0, sequence=0, recorded_at=NOW)
    s.put("export_bundles", (A,), bundle_id="crate-a", sha256="a" * 64, scope="session", session_uuid=UUID_A, created_at=1.0, updated_at=1.0)
    s.put("export_pointers", (A,), conversation_id=CONV_A, family="claude", bundle_id="crate-a", exported_at=1.0)
    s.put("export_bundles", (P,), bundle_id="crate-p", sha256="b" * 64, scope="project", project_uid="project-uid-1", created_at=1.0, updated_at=1.0)
    s.put("export_bundles", (), bundle_id="crate-d", sha256="c" * 64, scope="session", session_uuid=UUID_D, created_at=1.0, updated_at=1.0)
    s.put("export_pointers", (), conversation_id=CONV_D, family="claude", bundle_id="crate-d", exported_at=1.0)
    s.put("spectator_links", (A,), id="sl-1", session_id=APP_A, token_sha256="a" * 64, created_at=1, expires_at=2)
    s.put("spectator_links", (), id="sl-2", session_id=APP_D, token_sha256="b" * 64, created_at=1, expires_at=2)
    s.put("pack_session_moves", (A,), id="mv-1", role="source", session_uuid=UUID_A, source_install_id="i1", target_install_id="i2",
          state="moved", started_at=NOW)
    s.put("pack_placements", (A,), agent_id=1, session_id=w.row_a, workload_json="{}", mode="stats", reason="r", candidates_json="[]", created_at=1.0)
    s.put("peer_sessions", (A,), host_key="h", peer_session_uuid="peer-1", session_id=APP_A)
    for table in ("pack_rollups", "pack_rollup_counters"):
        extra = {"counter": 1, "key": 1, "value": 1} if table.endswith("counters") else {}
        s.put(table, (A,), peer_install_id="i2", conversation_id=CONV_A, hour=1, model="m", project="Proj One", **extra)


def seed_swarm(w: SimpleNamespace) -> None:
    s = w.main_seed
    base = dict(slug="s", rank="task", display_name="x", persona="p", job="j", naming_family="f", naming_state="none",
                memory_scope="project", harness="claude", model="m", effort="medium", goal="g", task_type="t", origin_message_ref="o",
                character_seed="c", color_slot=1, thread_key="th", state="asleep", turn_authority="owner", created_at=1.0,
                updated_at=1.0)
    x1 = s.put("swarm_agents", (A, P), repo_dir=w.root1, project_id=w.p1, session_row_id=w.row_a, **{**base, "slug": "s1", "thread_key": "th1"})
    x2 = s.put("swarm_agents", (P,), repo_dir=w.root1, project_id=w.p1, **{**base, "slug": "s2", "thread_key": "th2"})
    s.put("swarm_agents", (), repo_dir=w.root2, project_id=w.p2, session_row_id=w.row_d, **{**base, "slug": "s3", "thread_key": "th3"})
    for agent, tags in ((x1, (A, P)), (x2, (P,))):
        wake = s.put("swarm_wakes", tags, agent_id=agent, started_at=1.0, reason="manual", mode="fresh", authority="owner", conversation_uuid=CONV_A)
        s.put("swarm_deliveries", tags, agent_id=agent, wake_id=wake, authority="owner", source="crosstalk", owner_message_ref="om", delivered_at=1.0)
        s.put("swarm_facts", tags, agent_id=agent, rel_path="f.md", title="t", scope="project", origin="owner", owner_message_ref="m", taught_at=1.0, sha256="x", state="live")
        question = s.put("swarm_questions", tags, text="q", state="open", created_at=1.0)
        s.put("swarm_learning", tags, agent_id=agent, question_id=question, kind="discovery", text="t", owner_message_ref="o", scope_stamp="project", state="queued", created_at=1.0)
        s.put("swarm_promotions", tags, agent_id=agent, project_id=w.p1, task_type="t", from_rank="task", to_rank="feature", seed_rel_path="p", created_at=1.0)
        s.put("swarm_question_askers", tags, question_id=question, agent_id=agent, asked_at=1.0)
        s.put("swarm_question_hops", tags, question_id=question, agent_id=agent, coverage="c", outcome="answered", at=1.0)
        s.put("swarm_receipts", tags, question_id=question, answering_agent_id=agent, kind="owner_fact", fact_ids="[]", rendered="r", created_at=1.0)
        s.put("swarm_reports", tags, agent_id=agent, task_type="t", summary="s", state="pending", created_at=1.0)
        s.put("swarm_suggestions", tags, by_agent_id=agent, kind="project", name="n", reason="r", state="pending", created_at=1.0)
    s.put("swarm_remote_bodies", (A, P), session_row_id=w.row_a, home_install_id="i", home_agent_id=1, project_uid="project-uid-1",
          rank=1, slug="r", definition_rev=1, mirror_dir="/m/a", created_at=1.0)
    s.put("swarm_project_settings", (P,), project_id=w.p1, promotion_threshold=3)
    s.put("swarm_repo_visibility", (P,), repo_dir=w.root1, checked_at=1.0)
    s.put("swarm_repo_visibility", (), repo_dir=w.root2, checked_at=1.0)


def seed_project(w: SimpleNamespace) -> None:
    s = w.main_seed
    s.put("project_tombstones", (P,), root=w.root1, display_name="Proj One", deleted_at=NOW)
    s.put("project_tombstones", (), root=w.root2, display_name="Proj Two", deleted_at=NOW)
    s.put("project_storage", (P,), project_id=w.p1, state="packed", updated_at=NOW)
    s.put("project_replicas", (P,), project_uid="project-uid-1", install_id="i2", root=w.root1, transport_rung="git", state="ok", created_at=NOW, updated_at=NOW)
    s.put("pack_bundle_tips", (P,), project_uid="project-uid-1", install_id="i2", direction="in", last_tip_sha="abc", at=NOW)
    s.put("pack_carried_trust", (P,), folder=w.root1, project_uid="project-uid-1", source_install_id="i2", op_id="o", created_at=NOW)
    s.put("pack_migrations", (P,), id="mg-1", kind="project", role="source", subject_uid="project-uid-1", source_install_id="i1",
          target_install_id="i2", state="flipped", started_at=NOW)
    s.put("installed_items", (P,), install_id="inst-1", item_id="item", kind="skill", publisher="p", name="n", version="1", digest="d",
          scope="project", project_path=w.root1, source_index_url="u", consented_digest="d", consented_body_sha="b", publisher_key_id="k",
          revision=1, installed_at=NOW, updated_at=NOW)
    s.put("installed_item_targets", (P,), install_id="inst-1", harness="claude", path=f"{w.root1}/.claude/skills/n")
    s.put("installed_loadout_members", (P,), install_id="inst-1", item_id="item", version="1", state="ok")
    s.put("installed_items", (), install_id="inst-2", item_id="item2", kind="skill", publisher="p", name="n2", version="1", digest="d",
          scope="project", project_path=w.root2, source_index_url="u", consented_digest="d", consented_body_sha="b", publisher_key_id="k",
          revision=1, installed_at=NOW, updated_at=NOW)
