
from __future__ import annotations

import os
import tempfile
from contextlib import closing

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ps_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ps_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core import resource_push
from src.core.crosstalk import store as xstore
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.swarm import stream, stream_sources, store, wake_prompt, desk


def _who(key, ses, epoch, name):
    return {"key": key, "id": ses, "uuid": key, "epoch": epoch, "name": name, "provider": "claude", "model": None}


@pytest.fixture()
def world(tmp_path, monkeypatch):
    from src.config import settings

    monkeypatch.setattr(type(settings), "get_state_dir", lambda self: tmp_path, raising=True)
    assert ensure_db_migrated(tmp_path).status == "ok"
    monkeypatch.setattr(stream.thread_port, "get", lambda: None)
    agents = {}
    with closing(connect(db_path_for(tmp_path), create=False)) as conn:
        for name in ("alpha", "loki"):
            conn.execute(
                "INSERT INTO sessions (session_uuid, tmux_socket, tmux_name, tmux_created_epoch, working_dir, title, origin, "
                "lifecycle, created_at, updated_at) VALUES (?, 'cloude', ?, 100, '/tmp/pk', 't', 'created', 'stopped', "
                "'2026-03-01T00:00:00Z', '2026-03-01T00:00:00Z')", (f"uuid-{name}", f"cloude_{name}"))
            row_id = conn.execute("SELECT id FROM sessions WHERE session_uuid = ?", (f"uuid-{name}",)).fetchone()[0]
            agents[name] = store.create_agent(conn, slug=name, rank="alpha" if name == "alpha" else "feature", job=f"{name} job",
                                              display_name=name.title(), repo_dir=f"/tmp/pk-{name}", effort="high",
                                              parent_id=None if name == "alpha" else agents["alpha"]["id"])
            store.set_session_row(conn, agents[name]["id"], row_id)
            agents[name] = store.get_agent(conn, agents[name]["id"])
    return agents


def _kinds(page):
    return [(e["kind"], e.get("direction") or e.get("event")) for e in page["entries"]]


@pytest.mark.asyncio
async def test_exchange_and_events_survive_a_wake_into_a_new_body(world, monkeypatch):
    alpha, loki = world["alpha"], world["loki"]
    seen = []
    monkeypatch.setattr(resource_push, "notify", seen.append)
    a, l = _who("uuid-alpha", "ses_a1", 100, "Alpha"), _who("uuid-loki", "ses_l1", 100, "Loki")
    xstore.grant_contact(a["key"], l["key"], 100, 100)
    first = xstore.reserve(sender=a, receiver=l, text="swap the model", expect_reply=True)
    xstore.reserve(sender=l, receiver=a, text="on it", in_reply_to=first["id"])
    xstore.claim_for(l["key"])
    xstore.finish(first["id"], "delivered")
    assert f"swarm_agent:{alpha['id']}" in seen and f"swarm_agent:{loki['id']}" in seen
    assert seen.count(f"swarm_agent:{loki['id']}") >= 3

    before = {n: await stream.page(ag) for n, ag in world.items()}
    for page in before.values():
        traffic = [e for e in page["entries"] if e["kind"] == "traffic"]
        assert [t["text"] for t in traffic] == ["swap the model", "on it"]
    out_a = [e for e in before["alpha"]["entries"] if e["kind"] == "traffic"]
    assert [t["direction"] for t in out_a] == ["out", "in"] and out_a[0]["peer"] == "Loki"
    assert out_a[0]["receipt"]["status"] == "delivered" and out_a[0]["receipt"]["delivered_at"] is not None
    assert ("event", "spawned") in _kinds(before["alpha"]) and ("event", "spawned") in _kinds(before["loki"])

    xstore.repin("uuid-loki", "ses_l2", 777)
    after = {n: await stream.page(ag) for n, ag in world.items()}
    assert after == before
    l2 = _who("uuid-loki", "ses_l2", 777, "Loki")
    reply = xstore.reserve(sender=a, receiver=l2, text="status?") if xstore.contact(a["key"], l2["key"], 100, 777) else None
    assert reply is not None
    page = await stream.page(loki)
    assert [e["text"] for e in page["entries"] if e["kind"] == "traffic"] == ["swap the model", "on it", "status?"]
    assert page["cursor"] == page["entries"][-1]["id"]
    assert [e["at"] for e in page["entries"]] == sorted(e["at"] for e in page["entries"])


@pytest.mark.asyncio
async def test_reported_and_accepted_events_and_an_unrelated_pair_stays_out(world):
    from src.config import settings

    alpha, loki = world["alpha"], world["loki"]
    with closing(connect(db_path_for(settings.get_state_dir()), create=False)) as conn:
        rid = store.create_report(conn, loki, "done")
        store.decide_report(conn, rid, "accepted")
    xstore.grant_contact("uuid-x", "uuid-y", 1, 1)
    xstore.reserve(sender=_who("uuid-x", "s1", 1, "X"), receiver=_who("uuid-y", "s2", 1, "Y"), text="private")
    page = await stream.page(alpha)
    events = [e["event"] for e in page["entries"] if e["kind"] == "event"]
    assert sorted(events) == ["accepted", "reported", "spawned"] and not [e for e in page["entries"] if e["kind"] == "traffic"]
    with pytest.raises(ValueError):
        stream_sources.event_entry("nope", 1.0, "x", "t")
    assert stream_sources.event_entry("asked", 2.0, "q:1", "t")["id"] == "ev:asked:q:1"


def test_every_wake_restates_the_reporting_duty():
    agent = {"id": 1, "display_name": "Loki", "job": "j", "goal": None, "rank": "feature"}
    assert wake_prompt.REPORTING_DUTY in wake_prompt.render_desk(agent, "spawn", "", desk.Desk())
    assert wake_prompt.REPORTING_DUTY in wake_prompt.resume_message("crosstalk", "", agent)
