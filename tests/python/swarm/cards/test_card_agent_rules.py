
from __future__ import annotations

import asyncio
import dataclasses
import sqlite3
from contextlib import closing
from types import SimpleNamespace

from src.core.db import connect, db_path_for
from src.core.swarm import brief, definition, desk, facts, spawn, store, wake_prompt
from src.core.swarm import body_create
from src.core.swarm.body_create import brief_for
from src.core.swarm.cards import deliver, effects, ops, port as card_port, texts
from tests.python.swarm.test_swarm_s7_smokefix import _row, env  # noqa: F401

SPEC = brief.BriefSpec(
    slug="x", display_name="X", persona="p", name_reason="r", job="j", rank="task", order="o", goal="g", effort="medium",
    effort_reason="", parent_name="Boss", memory_dir="/m")


def _section_four(text: str) -> str:
    return text.split(f"## {brief.SECTION_TODO}")[1].split(f"## {brief.SECTION_RULES}")[0]


def test_a_task_and_feature_brief_teach_the_card_loop_in_section_four():
    for rank in ("task", "feature"):
        todo = _section_four(brief.render_brief(dataclasses.replace(SPEC, rank=rank)).body)
        for tool in ("swarm_card_start", "swarm_card_handoff", "swarm_card_finish", "swarm_card_release", "swarm_remember"):
            assert f"`{tool}`" in todo, (rank, tool)
        assert "how-to-validate" in todo and "`needs_owner`" in todo and "ask Boss with `swarm_ask`" in todo
        assert "Do the job named in section 1" not in todo


def test_a_project_agent_gets_the_dealing_rules_after_its_delegation_sentence_in_all_three_places():
    project = _row("project")
    texts_ = {"brief_for": brief_for(project), "resume": wake_prompt.resume_message("manual", "", project),
              "desk": wake_prompt.render_desk(project, "spawn", "", desk.Desk())}
    for where, text in texts_.items():
        assert definition.PROJECT_RULES in text, where
        assert text.index("Delegation rule:") < text.index("swarm_card_deal"), where
        for tool in ("swarm_card_list", "swarm_card_create", "swarm_accept_report", "swarm_card_reorder"):
            assert tool in text, (where, tool)
    assert definition.PROJECT_RULES.startswith("Delegation rule:")
    task = _row("task", goal="add a footer", effort="medium")
    assert "swarm_card_deal" not in brief_for(task, "Espresso", "/m")
    assert "swarm_card_deal" not in wake_prompt.resume_message("manual", "", task)
    assert "swarm_card_deal" not in brief.render_brief(SPEC).body


def test_both_wake_texts_carry_the_card_duty_after_the_reporting_duty():
    for rank in ("project", "task", "company", "alpha"):
        row = _row(rank, goal="g")
        for text in (wake_prompt.resume_message("manual", "", row), wake_prompt.render_desk(row, "manual", "", desk.Desk())):
            assert wake_prompt.CARD_DUTY in text and text.index(wake_prompt.REPORTING_DUTY) < text.index(wake_prompt.CARD_DUTY), rank
    assert "needs_owner" in wake_prompt.CARD_DUTY
    assert wake_prompt.CARD_DUTY in wake_prompt.resume_message("manual", "")


def test_the_dealt_text_lists_at_most_three_chain_facts_between_the_handoff_and_the_instruction():
    card = {"id": 4, "title": "fix login", "text": "why", "handoff": "half done"}
    plain = texts.dealt(card)
    assert "What your chain already knows" not in plain and plain.endswith("(result, how-to-validate and needs_owner).")
    known = [{"fact_id": f"f_00000000000{i}", "title": f"title {i}\nwith a break"} for i in range(5)]
    text = texts.dealt(card, chain_facts=known)
    lines = text.split("\n")
    assert lines.index("What your chain already knows:") == lines.index("Handoff so far: half done.") + 1
    assert [ln for ln in lines if ln.startswith("fact ")] == [f"fact f_00000000000{i}: title {i} with a break" for i in range(3)]
    assert text.index("fact f_000000000002") < text.index("Call swarm_card_start now")
    assert texts.tell_text("dealt", card, chain_facts=known) == text


def _agent(conn, slug, rank, tmp_path, parent=None):
    return store.create_agent(conn, slug=slug, rank=rank, job=f"job of {slug}", display_name=slug.title(), repo_dir=str(tmp_path / slug),
                              effort="high", parent_id=parent["id"] if parent else None)


def test_a_dealt_card_carries_the_best_matching_live_facts_of_its_chain_and_no_others(env, tmp_path):  # noqa: F811
    with closing(connect(db_path_for(env.state), create=False)) as conn:
        boss = env.agents["acmeboss"]
        child = _agent(conn, "loki", "task", tmp_path, boss)
        outsider = _agent(conn, "studio", "task", tmp_path, env.agents["alpha"])
        mine = facts.store_owner_fact(conn, boss, title="login redirect rule", text="the login redirect keeps the next param", owner_message_ref="huddle:msg:1")
        held = facts.store_owner_fact(conn, boss, title="login redirect old", text="the login redirect was removed", owner_message_ref="huddle:msg:2")
        facts.store_owner_fact(conn, boss, title="billing rounding", text="round invoices up to the cent", owner_message_ref="huddle:msg:3")
        facts.store_owner_fact(conn, outsider, title="login redirect elsewhere", text="login redirect in another chain", owner_message_ref="huddle:msg:4")
        conn.execute("UPDATE swarm_facts SET state = 'held' WHERE id = ?", (held["fact_id"],))
        conn.commit()
        found = facts.chain_facts(conn, child, "fix the login redirect")
        assert found == [{"fact_id": mine["fact_id"], "title": "login redirect rule"}]
        assert facts.chain_facts(conn, child, "zzzz nothing matches") == []
        assert facts.chain_facts(conn, child, "") == []
    told = []

    async def record(app_state, agent_id, text, *, ref, **kw):
        told.append(SimpleNamespace(agent_id=agent_id, text=text, ref=ref))
        return "delivered"

    card = {"id": 9, "title": "fix the login redirect", "text": "", "handoff": ""}
    effect = {"kind": "tell", "text": "dealt", "agent_id": child["id"], "data": {}}
    orig, deliver.tell = deliver.tell, record
    try:
        asyncio.run(effects._tell(SimpleNamespace(), card, effect))
        asyncio.run(effects._tell(SimpleNamespace(), card, dict(effect, agent_id=child["id"] + 999)))
    finally:
        deliver.tell = orig
    assert len(told) == 2 and told[0].ref == "card:9" and "What your chain already knows" not in told[1].text
    assert f"fact {mine['fact_id']}: login redirect rule" in told[0].text and told[0].text.count("\nfact ") == 1
    assert "login redirect elsewhere" not in told[0].text and "billing rounding" not in told[0].text
    with closing(connect(db_path_for(env.state), create=False)) as conn:
        for n in range(4):
            facts.store_owner_fact(conn, child, title=f"login redirect extra {n}", text=f"login redirect detail {n}", owner_message_ref=f"huddle:msg:{10 + n}")
        assert len(facts.chain_facts(conn, child, "fix the login redirect")) == 3
        assert len(facts.chain_facts(conn, child, "fix the login redirect", limit=2)) == 2


def test_a_handwritten_secret_titled_note_and_another_projects_private_fact_are_never_dealt(env, tmp_path):  # noqa: F811
    token = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
    with closing(connect(db_path_for(env.state), create=False)) as conn:
        boss = env.agents["acmeboss"]
        child = _agent(conn, "odin", "task", tmp_path, boss)
        conn.execute(
            "INSERT INTO swarm_facts (id, agent_id, rel_path, title, scope, origin, taught_at, state) "
            "VALUES ('f_0123456789ab', ?, 'facts/f_0123456789ab.md', ?, 'craft', 'handwritten', '2026-10-07T00:00:00Z', 'live')",
            (boss["id"], f"login redirect token {token}"))
        conn.execute("INSERT INTO swarm_fact_fts (doc_key, agent_id, title, body) VALUES ('fact:f_0123456789ab', ?, ?, 'login redirect')",
                     (boss["id"], f"login redirect token {token}"))
        flagged = facts.store_owner_fact(conn, boss, title="login redirect key", text="login redirect secret", owner_message_ref="huddle:msg:20")
        conn.execute("UPDATE swarm_facts SET scope = 'craft', title = ? WHERE id = ?", (f"login redirect key {token}", flagged["fact_id"]))
        (tmp_path / "other").mkdir()
        other = body_create.register_project(conn, str(tmp_path / "other"), "Other")
        conn.execute("UPDATE swarm_agents SET project_id = ? WHERE id = ?", (other["id"], child["id"]))
        private = facts.store_owner_fact(conn, boss, title="login redirect private", text="login redirect project detail", owner_message_ref="huddle:msg:21")
        craft = facts.store_owner_fact(conn, boss, title="login redirect craft", text="login redirect craft detail", owner_message_ref="huddle:msg:22")
        conn.execute("UPDATE swarm_facts SET scope = 'craft' WHERE id = ?", (craft["fact_id"],))
        conn.commit()
        child = store.get_agent(conn, child["id"])
        found = facts.chain_facts(conn, child, "fix the login redirect")
        assert [f["fact_id"] for f in found] == [craft["fact_id"]]
        for row in found:
            assert token not in row["title"]
        assert flagged["fact_id"] not in {f["fact_id"] for f in found} and private["fact_id"] not in {f["fact_id"] for f in found}
        text = texts.dealt({"id": 1, "title": "fix the login redirect", "text": "", "handoff": ""}, chain_facts=found)
        assert token not in text and "login redirect craft" in text


def test_a_spawned_childs_first_message_lists_its_chain_facts_and_none_when_the_read_fails(env, tmp_path, monkeypatch):  # noqa: F811
    line = texts.spawn_card_line({"id": 4, "title": "fix"}, [{"fact_id": "f_000000000001", "title": "a\nb"}] * 5)
    assert line.count("\nfact ") == 3 and "fact f_000000000001: a b" in line
    assert "What your chain" not in texts.spawn_card_line({"id": 4, "title": "fix"}) and texts.spawn_card_line({"id": 4, "title": "fix"}, []).endswith("(result, how-to-validate and needs_owner).")
    with closing(connect(db_path_for(env.state), create=False)) as conn:
        boss = env.agents["acmeboss"]
        child = _agent(conn, "freya", "task", tmp_path, boss)
        mine = facts.store_owner_fact(conn, boss, title="login redirect rule", text="the login redirect keeps the next param", owner_message_ref="huddle:msg:30")
        facts.store_owner_fact(conn, boss, title="billing rounding", text="round invoices up to the cent", owner_message_ref="huddle:msg:31")
        conn.commit()
    card = {"id": 9, "title": "fix the login redirect", "text": "", "handoff": ""}
    seen = []

    async def mint(app_state, parent, kid, **kw):
        seen.append(kid["id"])
        return card

    monkeypatch.setattr(card_port, "get", lambda: object())
    monkeypatch.setattr(ops, "mint_for_spawn", mint)
    plan = SimpleNamespace(request={"job": "fix the login redirect", "goal": ""}, parent=boss, card_id=None)
    said = asyncio.run(spawn._give_card(SimpleNamespace(), plan, child))
    assert seen == [child["id"]] and said.startswith("\n\nYour card is #9: fix the login redirect.")
    assert said.count("\nfact ") == 1 and f"fact {mine['fact_id']}: login redirect rule" in said and "billing rounding" not in said

    def broken(conn, agent, text, **kw):
        raise sqlite3.OperationalError("index gone")

    monkeypatch.setattr(facts, "chain_facts", broken)
    failed = asyncio.run(spawn._give_card(SimpleNamespace(), plan, child))
    assert failed.startswith("\n\nYour card is #9") and "What your chain already knows" not in failed
    empty = asyncio.run(spawn._give_card(SimpleNamespace(), plan, dict(child, id=child["id"] + 999)))
    assert "What your chain already knows" not in empty
