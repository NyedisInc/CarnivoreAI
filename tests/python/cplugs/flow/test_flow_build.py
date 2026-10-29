
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from src.core.flow_data.collect import build, participants
from src.cplugs.host.activity_reader import ActivityReader
from tests.python.cplugs.flow import fixture as fx

NOW = fx.BASE + 4 * 3600


@pytest.fixture()
def reader(tmp_path, monkeypatch):
    made = fx.make_install(tmp_path)
    monkeypatch.setattr(ActivityReader, "_transcript_path", lambda self, conv: next((str(p) for p in made["paths"].values() if p.stem == conv), None))
    return ActivityReader(made["state_dir"])


@pytest.fixture()
def run(reader):
    return build.build_run(reader, "huddle_item", "395", now=NOW)


def edge(run, edge_id):
    return next(e for e in run["edges"] if e["id"] == edge_id)


def test_lanes_follow_the_crosstalk_walk_and_nest_the_subagent(run):
    ids = [(lane["id"], lane["parent"]) for lane in run["lanes"]]
    assert ids[0] == ("owner", None)
    assert [i for i, _ in ids if i.startswith("s:")] == [f"s:{u}" for u in (fx.B, fx.F, fx.D)]
    assert (f"a:{fx.AGENT_ID}", f"s:{fx.F}") in ids
    assert ids.index((f"a:{fx.AGENT_ID}", f"s:{fx.F}")) == ids.index((f"s:{fx.F}", None)) + 1
    assert run["window"]["end"] == pytest.approx(fx.BASE + 3401.05 + participants.DEFAULT_TAIL_S)


def test_crosstalk_edges_are_exact_and_located_in_the_receivers_transcript(run):
    sent = edge(run, "m-N8jp")
    assert (sent["kind"], sent["inferred"], sent["located_by"]) == ("crosstalk", False, "header")
    assert sent["from"] == {"lane": f"s:{fx.B}", "t": fx.BASE + 255.1}
    assert sent["to"] == {"lane": f"s:{fx.F}", "t": pytest.approx(fx.BASE + 255.3, abs=0.01)}
    assert sent["source"]["send"]["line"] == 4 and sent["source"]["receive"]["line"] == 1
    assert edge(run, "m-xGDy")["reply_to"] == "m-N8jp"
    assert edge(run, "m-6LGV")["to"]["lane"] == f"s:{fx.D}"


def test_spawn_before_the_window_annotates_the_lane_and_is_inferred(run):
    assert not any(e["kind"] == "spawn" for e in run["edges"])
    docker = next(lane for lane in run["lanes"] if lane["id"] == f"s:{fx.D}")
    assert docker["spawned_by"] == {"lane": f"s:{fx.F}", "t": fx.SPAWN_AT, "basis": "contact"}


def test_subagent_launch_and_return_join_on_tool_use_id(run):
    launch, back = edge(run, "launch:tf2"), edge(run, "return:tf2")
    assert (launch["kind"], launch["inferred"]) == ("subagent_launch", False)
    assert launch["from"]["lane"] == f"s:{fx.F}" and launch["to"]["lane"] == f"a:{fx.AGENT_ID}"
    assert (back["from"]["lane"], back["to"]["lane"], back["label"]) == (f"a:{fx.AGENT_ID}", f"s:{fx.F}", "completed")
    block = next(b for b in run["blocks"] if b["id"] == f"a:{fx.AGENT_ID}:run")
    assert block["tools"] == {"Bash": 1, "Write": 1} and block["label"] == "Fix QNAP nightly_backup path"
    assert [b["label"] for b in run["blocks"] if b["kind"] == "tool"] == ["Bash"]


def test_task_manager_posts_replies_and_card_moves(run):
    assert edge(run, "hmsg:1914")["kind"] == "huddle_post" and edge(run, "hmsg:1914")["to"]["lane"] == "owner"
    reply = edge(run, "hmsg:1913")
    assert (reply["kind"], reply["inferred"], reply["located_by"]) == ("owner_reply", False, "channel")
    assert reply["to"] == {"lane": f"s:{fx.B}", "t": fx.BASE + 250}
    card = next(m for m in run["marks"] if m["kind"] == "card")
    assert (card["lane"], card["inferred"]) == (f"s:{fx.B}", True)
    assert any(m["kind"] == "huddle_add" and m["source"]["item_id"] == 408 for m in run["marks"])


def test_blocks_turns_and_the_summary(run):
    turns = [b for b in run["blocks"] if b["lane"] == f"s:{fx.F}" and b["kind"] == "turn"]
    first = turns[0]
    assert (first["origin"], first["tools"]) == ("peer", {"huddle_add": 1, "Agent": 1, "crosstalk_reply": 1})
    assert first["source"]["conversation_id"] == "conv-fleet" and first["source"]["line"] == 1
    assert [t["origin"] for t in turns] == ["peer", "task_notification"]
    assert run["stats"]["inferred_edges"] == sum(1 for e in run["edges"] if e["inferred"]) == 0
    assert run["stats"]["edge_kinds"]["crosstalk"] == 3
    assert run["idle_gaps"] and run["idle_gaps"][0]["end"] - run["idle_gaps"][0]["start"] > 2000
    times = [e["t"] for e in run["events"]]
    assert times == sorted(times)


def test_seed_errors(reader):
    with pytest.raises(participants.SeedNotFound):
        build.build_run(reader, "huddle_item", "99999", now=NOW)
    with pytest.raises(ValueError):
        build.build_run(reader, "nope", "1", now=NOW)
    session = build.build_run(reader, "session", fx.F, start=fx.BASE, end=fx.BASE + 600, now=NOW)
    assert {lane["id"] for lane in session["lanes"] if lane["kind"] == "session"} == {f"s:{fx.F}", f"s:{fx.B}"}


def test_optional_core_columns_are_picked_up_when_present(reader, tmp_path):
    assert reader.sources()["optional"]["crosstalk_columns"] == []
    db = sqlite3.connect(next((tmp_path / "state").glob("carnivore.db")))
    db.execute("ALTER TABLE crosstalk_messages ADD COLUMN receiver_record_uuid TEXT")
    db.execute("ALTER TABLE sessions ADD COLUMN parent_session_id INTEGER")
    db.execute("UPDATE sessions SET parent_session_id=2 WHERE session_uuid=?", (fx.D,))
    db.commit()
    db.close()
    assert reader.sources()["optional"]["crosstalk_columns"] == ["receiver_record_uuid"]
    run = build.build_run(reader, "huddle_item", "395", now=NOW)
    docker = next(lane for lane in run["lanes"] if lane["id"] == f"s:{fx.D}")
    assert docker["spawned_by"]["basis"] == "parent_session_id"


def test_the_reader_never_writes(reader, tmp_path):
    before = (tmp_path / "state" / "carnivore.db").read_bytes()
    build.build_run(reader, "huddle_item", "395", now=NOW)
    assert (tmp_path / "state" / "carnivore.db").read_bytes() == before


def test_core_flow_data_v90_is_used_when_present(reader, tmp_path):
    db = sqlite3.connect(tmp_path / "state" / "carnivore.db")
    db.executescript("""
        ALTER TABLE crosstalk_messages ADD COLUMN landed_at REAL;
        ALTER TABLE crosstalk_messages ADD COLUMN landed_anchor TEXT;
        ALTER TABLE crosstalk_messages ADD COLUMN delivery_path TEXT;
        ALTER TABLE crosstalk_messages ADD COLUMN spawn_task INTEGER;
        CREATE TABLE agent_spawn_links (child_id TEXT PRIMARY KEY, child_uuid TEXT, parent_id TEXT, parent_uuid TEXT, parent_kind TEXT,
            task_message_id TEXT, peer_install_id TEXT, spawned_at REAL);
        CREATE TABLE mcp_events (id INTEGER PRIMARY KEY, call_id TEXT, started_at REAL, tool TEXT, caller_kind TEXT, caller_session_id TEXT,
            caller_tmux TEXT, target_ids TEXT, result_ids TEXT, outcome TEXT, duration_ms INTEGER);
    """)
    db.execute("UPDATE crosstalk_messages SET landed_at=?, landed_anchor='native:m-6LGV:conv-docker', delivery_path='native' WHERE id='m-6LGV'", (fx.BASE + 3010.4,))
    db.execute("INSERT INTO agent_spawn_links VALUES ('ses_dddddddd',?,?,?,'session','m-OLD1',NULL,?)", (fx.D, "ses_ffffffff", fx.F, fx.SPAWN_AT))
    db.execute("INSERT INTO mcp_events VALUES (1,'c1',?,'huddle_update','pane',?,NULL,'{\"item\": [\"395\"]}',NULL,'ok',40)", (fx.BASE + 3400.95, fx.APP[fx.B]))
    db.commit()
    db.close()
    opt = reader.sources()["optional"]
    assert opt["spawn_links"] and opt["mcp_events"] and "landed_anchor" in opt["crosstalk_columns"]
    run = build.build_run(reader, "huddle_item", "395", now=NOW)
    docker = next(lane for lane in run["lanes"] if lane["id"] == f"s:{fx.D}")
    assert docker["spawned_by"]["basis"] == "spawn_link"
    landed = edge(run, "m-6LGV")
    assert landed["delivery_path"] == "native" and landed["source"]["receive"]["anchor"] == "native:m-6LGV:conv-docker"
    assert landed["located_by"] == "header"
    assert run["mcp_events"] == 1


def test_a_sessions_live_conversation_is_read_even_with_a_stale_end_in_the_index(reader, tmp_path):
    before = build.build_run(reader, "huddle_item", "395", now=NOW)
    fleet_turns = [b for b in before["blocks"] if b["lane"] == f"s:{fx.F}" and b["kind"] == "turn"]
    assert fleet_turns
    db = sqlite3.connect(next((tmp_path / "state").glob("carnivore.db")))
    db.execute("UPDATE conversation_index SET ended_at=? WHERE conversation_id=?", (fx.iso(fx.SPAWN_AT), fx.CONV[fx.F]))
    db.commit()
    db.close()
    after = build.build_run(reader, "huddle_item", "395", now=NOW)
    assert [b for b in after["blocks"] if b["lane"] == f"s:{fx.F}" and b["kind"] == "turn"] == fleet_turns


def test_a_task_seed_carries_its_title_and_github_issue(reader, tmp_path):
    db = sqlite3.connect(next((tmp_path / "state").glob("carnivore.db")))
    db.execute("ALTER TABLE work_items ADD COLUMN title TEXT")
    db.execute("ALTER TABLE work_items ADD COLUMN github_issue TEXT")
    db.execute("UPDATE work_items SET title='Backups: fix the nightly job (#77)', github_issue='https://github.com/o/r/issues/77' WHERE id=395")
    db.commit()
    db.close()
    seed = build.build_run(reader, "huddle_item", "395", now=NOW)["seed"]
    assert seed["title"] == "Backups: fix the nightly job (#77)" and seed["github_issue"] == "https://github.com/o/r/issues/77"


def test_a_task_seed_without_those_columns_keeps_the_text_title(run):
    assert run["seed"]["title"] == "qnap nightly backup broken" and "github_issue" not in run["seed"]
