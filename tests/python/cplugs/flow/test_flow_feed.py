
from __future__ import annotations

import asyncio
import json
import sqlite3
from types import SimpleNamespace

import pytest

from src.cplugs.flow import build, feed, live, service, tail
from src.cplugs.host.activity_reader import ActivityReader
from src.cplugs.sdk import transcript_events
from tests.python.cplugs.flow import fixture as fx

NOW = fx.BASE + 4 * 3600


@pytest.fixture()
def made(tmp_path, monkeypatch):
    made = fx.make_install(tmp_path)
    monkeypatch.setattr(ActivityReader, "_transcript_path", lambda self, conv: next((str(p) for p in made["paths"].values() if p.stem == conv), None))
    made["reader"] = ActivityReader(made["state_dir"])
    return made


def _page(reader, cache, cursor=None, now=NOW):
    return feed.page(build.build_run(reader, "huddle_item", "395", now=now, scan=cache.scan), cursor)


def _index(items, item_id):
    return next(n for n, i in enumerate(items) if i["id"] == item_id)


def test_feed_kinds_and_causal_order(made):
    page = _page(made["reader"], tail.TailCache())
    items, sub = page["items"], f"a:{fx.AGENT_ID}"
    assert {"bubble", "work", "crosstalk", "launch", "return", "huddle", "task"} <= {i["kind"] for i in items}
    keys = [(i["t"], feed.RANK[i["kind"]], i["id"]) for i in items]
    assert keys == sorted(keys) and page["total"] == len(items) and page["full"]
    ask, reply = _index(items, "crosstalk:m-N8jp"), _index(items, "crosstalk:m-xGDy")
    fleet_work = [n for n, i in enumerate(items) if i["kind"] == "work" and i["lane"] == f"s:{fx.F}"]
    assert ask < fleet_work[0] < reply and items[reply]["reply_to"] == "m-N8jp" and items[ask]["landed"]
    assert len(fleet_work) == 2
    launch, back = _index(items, "launch:launch:tf2"), _index(items, "return:return:tf2")
    task = next(n for n, i in enumerate(items) if i["lane"] == sub and i["kind"] == "bubble" and i["role"] == "task")
    work = next(n for n, i in enumerate(items) if i["lane"] == sub and i["kind"] == "work")
    said = next(n for n, i in enumerate(items) if i["lane"] == sub and i["kind"] == "bubble" and i["role"] == "agent")
    assert launch < task < work < said < back
    assert (items[work]["count"], items[work]["tools"]) == (2, {"Bash": 1, "Write": 1})
    assert (items[back]["lane"], items[back]["to"], items[back]["tool_count"]) == (sub, f"s:{fx.F}", 2)
    assert items[back]["duration_s"] == pytest.approx(2990 - 290.1, abs=0.2)
    assert items[_index(items, "huddle:hmsg:1913")]["owner"] is True
    moved = items[_index(items, "task:card:2")]
    assert (moved["change"], moved["from_col"], moved["to_col"], moved["item_id"]) == ("moved", "in_progress", "review", 395)
    lanes = {lane["id"]: lane for lane in page["lanes"]}
    assert lanes[sub]["depth"] == 1 and lanes["owner"]["color"] is None and lanes[f"s:{fx.B}"]["color"] == 0


def test_cursor_sends_only_what_changed_and_reads_only_new_bytes(made):
    cache = tail.TailCache()
    first = _page(made["reader"], cache)
    again = _page(made["reader"], cache, cursor=first["cursor"])
    edge = first["cursor"] - feed.SKEW_S
    assert again["total"] == first["total"] and again["cursor"] == first["cursor"]
    assert [i["id"] for i in again["items"]] == [i["id"] for i in first["items"] if i["u"] > edge]
    assert len(again["items"]) < len(first["items"]) // 4
    read_before = cache.bytes_read
    lines = [fx.rec("assistant", fx.BASE + 3500, message={"content": [{"type": "text", "text": "backup path fixed"}]}),
             fx.call(fx.BASE + 3501, "tf9", "Bash"), fx.result(fx.BASE + 3503, "tf9", "ok")]
    added = "".join(json.dumps(r) + "\n" for r in lines)
    with made["paths"][fx.F].open("a", encoding="utf-8") as handle:
        handle.write(added + '{"type": "assistant", "timestamp": "2026-')
    later = _page(made["reader"], cache, cursor=first["cursor"])
    assert cache.bytes_read - read_before == len(added.encode())
    new = [i for i in later["items"] if i["u"] > first["cursor"]]
    assert [(i["kind"], i["lane"]) for i in new] == [("bubble", f"s:{fx.F}"), ("work", f"s:{fx.F}")]
    assert new[0]["text"] == "backup path fixed" and later["total"] == first["total"] + 2
    assert {i["id"] for i in later["items"]} == {i["id"] for i in again["items"]} | {i["id"] for i in new}
    assert later["cursor"] == pytest.approx(fx.BASE + 3503)


def test_a_spawn_inside_the_window_is_a_spawn_card(made):
    db = sqlite3.connect(made["state_dir"] / "carnivore.db")
    db.execute("CREATE TABLE agent_spawn_links (child_id TEXT PRIMARY KEY, child_uuid TEXT, parent_id TEXT, parent_uuid TEXT, parent_kind TEXT, "
               "task_message_id TEXT, peer_install_id TEXT, spawned_at REAL)")
    db.execute("INSERT INTO agent_spawn_links VALUES ('ses_dddddddd',?,?,?,'session','m-6LGV',NULL,?)", (fx.D, fx.APP[fx.F], fx.F, fx.BASE + 3005))
    db.commit()
    db.close()
    items = _page(made["reader"], tail.TailCache())["items"]
    spawn = items[_index(items, f"spawn:spawn:{fx.D}")]
    assert (spawn["lane"], spawn["to"], spawn["basis"], spawn["inferred"]) == (f"s:{fx.F}", f"s:{fx.D}", "spawn_link", False)
    assert _index(items, f"spawn:spawn:{fx.D}") < _index(items, "crosstalk:m-6LGV")


def test_get_feed_leases_the_runs_sessions_and_names_the_topic_on_their_appends(made, monkeypatch):
    clock = [1000.0]
    watch = live.FeedWatch(clock=lambda: clock[0])
    monkeypatch.setattr(live, "WATCH", watch)
    monkeypatch.setattr(tail, "CACHE", tail.TailCache())
    transcript_events.reset()
    named = []
    ctx = SimpleNamespace(activity=made["reader"], notify=lambda name, key=None: named.append(name))
    answer = asyncio.run(service.get_feed(ctx, "huddle_item", "395"))
    assert answer["items"] and watch.leased()["subscribed"]
    assert fx.APP[fx.F] in watch.leased()["keys"] and "carnivore_2" in watch.leased()["keys"]
    transcript_events.publish_append("ses_somebodyelse", "carnivore_99")
    assert named == []
    transcript_events.publish_append("ses_unknown", "carnivore_2")
    assert named == [live.TOPIC]
    clock[0] += live.LEASE_S + 1
    transcript_events.publish_append(fx.APP[fx.F], None)
    assert named == [live.TOPIC] and not watch.leased()["subscribed"] and not transcript_events.listening()
