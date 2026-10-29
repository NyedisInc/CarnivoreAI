
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.cplugs.flow import build, service
from src.cplugs.flow.views import events, model, page, tasks, text, tree
from src.cplugs.host.activity_reader import ActivityReader
from tests.python.cplugs.flow import fixture as fx

NOW = fx.BASE + 4 * 3600
UTC = dt.timezone.utc


@pytest.fixture()
def run(tmp_path, monkeypatch):
    made = fx.make_install(tmp_path)
    monkeypatch.setattr(ActivityReader, "_transcript_path", lambda self, conv: next((str(p) for p in made["paths"].values() if p.stem == conv), None))
    return build.build_run(ActivityReader(made["state_dir"]), "huddle_item", "395", now=NOW)


@pytest.fixture()
def view(run):
    return model.build_view(run, UTC)


def test_page_is_standalone_small_and_safe(run):
    run["lanes"][1]["label"] = "</script><img src=x onerror=alert(1)>"
    html_text = page.render_html(run, UTC)
    assert len(html_text.encode()) < 2 * 1024 * 1024
    for needle in ("<link", 'src="http', 'href="http', "fetch(", "XMLHttpRequest", "import(", "</script><img", "WebSocket", "localStorage"):
        assert needle not in html_text
    assert html_text.count("</script>") == 2 and "u003c/script" in html_text
    for view_id in ("v-hybrid", "v-gantt", "v-chat", "v-swim"):
        assert f'id="{view_id}"' in html_text


def test_page_script_is_valid_javascript(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    js = tmp_path / "page.js"
    js.write_text(page.js_source())
    done = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_every_asset_is_under_the_file_limit():
    for name in (*page.CSS_FILES, *page.JS_FILES, "page.html"):
        assert len((page.ASSETS / name).read_text().splitlines()) <= 500, name


def test_page_is_trimmed_to_fit(run, monkeypatch):
    monkeypatch.setattr(page, "MAX_BYTES", 60 * 1024)
    html_text = page.render_html(run, UTC)
    assert len(html_text.encode()) <= 60 * 1024


def test_service_page_answers_html(run):
    answer = service.as_page(run)
    assert answer["html"].startswith("<!doctype html>") and answer["bytes"] == len(answer["html"].encode())
    assert set(answer) == {"html", "bytes", "seed", "stats"}


def test_agents_form_one_tree_under_the_owner(view):
    by_id = {a["id"]: a for a in view["agents"]}
    roots = [a for a in view["agents"] if a["parent"] is None]
    assert [r["id"] for r in roots] == ["owner"]
    assert by_id[f"s:{fx.F}"]["parent"] == f"s:{fx.B}"
    assert by_id[f"s:{fx.D}"]["parent"] == f"s:{fx.F}"
    sub = next(a for a in view["agents"] if a["kind"] == "subagent")
    assert sub["parent"] == f"s:{fx.F}" and sub["role"] == "Subagent"


def test_parents_are_acyclic_even_when_messages_loop():
    lanes = [{"id": "owner", "kind": "owner"}, {"id": "a", "kind": "session"}, {"id": "b", "kind": "session"}]
    edges = [{"kind": "crosstalk", "from": {"lane": "a", "t": 1}, "to": {"lane": "b", "t": 1}}, {"kind": "crosstalk", "from": {"lane": "b", "t": 2}, "to": {"lane": "a", "t": 2}}]
    parent = tree.assign_parents(lanes, edges)
    assert parent == {"owner": None, "a": "owner", "b": "owner"}


def test_tasks_are_items_with_their_card_moves_and_subagents(view):
    by_id = {t["id"]: t for t in view["tasks"]}
    assert set(by_id) == {"#395", "#408", "S1"}
    root = by_id["#395"]
    assert root["root"] and root["status"] == "review" and root["agent"] == f"s:{fx.B}"
    assert by_id["#408"]["status"] == "created" and by_id["#408"]["agent"] == f"s:{fx.F}"
    assert by_id["S1"]["kind"] == "sub" and by_id["S1"]["status"] == "done" and by_id["S1"]["title"] == "Fix nightly_backup path"


def test_delegations_carry_the_task_they_handed_over(view):
    delegates = {(e["from"], e["to"]): e for e in view["edges"] if e["cls"] == "delegate"}
    assert delegates[(f"s:{fx.B}", f"s:{fx.F}")]["task"] == "#408"
    assert delegates[(f"s:{fx.F}", next(a["id"] for a in view["agents"] if a["kind"] == "subagent"))]["task"] == "S1"
    assert delegates[(f"s:{fx.B}", f"s:{fx.F}")]["label"] == "Delegates #408"


def test_events_cover_every_edge_and_task_change_in_time_order(run, view):
    ev = view["events"]
    assert [e["t"] for e in ev] == sorted(e["t"] for e in ev)
    ids = {e["id"] for e in ev}
    assert {edge["id"] for edge in run["edges"]} <= ids
    kinds = {e["kind"] for e in ev}
    assert {"delegate", "return", "task_created", "task_updated"} <= kinds
    assert all(re.fullmatch(r"\d\d:\d\d", e["time"]) for e in ev)
    assert next(e for e in ev if e["id"] == "c:#395")["time"] == dt.datetime.fromtimestamp(run["marks"][0]["t"], UTC).strftime("%H:%M")


def test_chat_chips_use_real_actions_only(view):
    acts = {a["a"] for e in view["events"] for a in e["acts"]}
    assert acts <= {"delegates", "creates", "updates", "completes", "comments", "returns"}
    launch = next(e for e in view["events"] if e["edge_kind"] == "subagent_launch")
    assert launch["acts"][0] == {"a": "creates", "task": "S1", "to": launch["to"]}
    ret = next(e for e in view["events"] if e["edge_kind"] == "subagent_return")
    assert {"a": "completes", "task": "S1"} in ret["acts"]
    post = next(e for e in view["events"] if e["edge_kind"] == "huddle_post")
    assert post["acts"] == [{"a": "comments", "task": "#395"}]


def test_segments_come_from_work_blocks(run, view):
    assert set(view["segments"]) <= {lane["id"] for lane in run["lanes"]}
    for segs in view["segments"].values():
        assert all(a <= b for a, b in segs)
    assert view["segments"][f"s:{fx.B}"]


def test_final_result_is_absent_without_a_review_text(view):
    assert view["final"] is None


def test_final_result_uses_the_items_review_text(run):
    run["marks"][0]["review"] = "**nas fixed** and fresh\nmore"
    assert model.build_view(run, UTC)["final"]["text"] == "nas fixed and fresh"


def test_edges_off_the_tree_are_counted_not_dropped(run):
    run["edges"].append(dict(run["edges"][0], id="x1", **{"from": {"lane": f"s:{fx.D}", "t": run["edges"][0]["from"]["t"]}, "to": {"lane": f"s:{fx.B}", "t": run["edges"][0]["from"]["t"]}}))
    v = model.build_view(run, UTC)
    assert v["offtree"] >= 1 and any(e["id"] == "x1" for e in v["events"])
    assert all(e["id"] != "x1" for e in v["edges"])


def test_view_model_is_json_safe(view):
    json.dumps(view)


def test_text_helpers():
    assert text.short("item 4: Done. Next step is here", 20).endswith("...") or len(text.short("item 4: Done. Next step is here", 20)) <= 23
    assert text.display_name("Agent - Infrastructure (Corporate)") == "Infrastructure"
    assert text.monogram("Daily Bulletin") == "DB"
    assert tasks.column_of("todo") == "created" and tasks.column_of("weird") == "in_progress"


def test_embedded_model_round_trips(run):
    html_text = page.render_html(run, UTC)
    blob = re.search(r'<script type="application/json" id="d">(.*?)</script>', html_text, re.S).group(1)
    data = json.loads(blob)
    assert data["agents"][0]["id"] == "owner" and data["tz_offset"] == 0
    assert events.build_events


def test_mirror_item_filed_by_an_agent_is_found_through_its_created_card_event(tmp_path, monkeypatch):
    import sqlite3

    made = fx.make_install(tmp_path)
    monkeypatch.setattr(ActivityReader, "_transcript_path", lambda self, conv: next((str(p) for p in made["paths"].values() if p.stem == conv), None))
    hud = sqlite3.connect(made["state_dir"] / "carnivore.db")
    hud.execute("ALTER TABLE work_items ADD COLUMN title TEXT")
    hud.execute("ALTER TABLE work_items ADD COLUMN review_description TEXT")
    hud.execute("UPDATE work_items SET title='Backup broken', review_description='Fixed and fresh' WHERE id=395")
    hud.execute("INSERT INTO work_items VALUES (409,'13','mirror body','claude','todo',?,?,0,'Mirror title','')", (fx.BASE + 271, fx.BASE + 271))
    hud.execute("INSERT INTO work_card_events VALUES (9,409,'13',?,'created','','todo',?,'')", (fx.BASE + 271, fx.F))
    hud.commit()
    hud.close()
    run = build.build_run(ActivityReader(made["state_dir"]), "huddle_item", "395", now=NOW)
    mirror = next(m for m in run["marks"] if m["id"] == "item:409")
    assert mirror["lane"] == f"s:{fx.F}" and mirror["title"] == "Mirror title" and not mirror["inferred"]
    assert next(m for m in run["marks"] if m["id"] == "item:395")["review"] == "Fixed and fresh"
    assert {t["id"]: t["title"] for t in model.build_view(run, UTC)["tasks"]}["#409"] == "Mirror title"
