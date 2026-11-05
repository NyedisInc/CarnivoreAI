
from __future__ import annotations

import asyncio
import json
import types

import pytest

from src.api import computers_routes
from src.core.computers import join_proto, runtime
from src.core.computers.invites import Invites
from src.core.computers.join_client import JoinFailed
from src.core.computers.join_limits import KnockRates
from src.core.computers.join_server import JoinServer
from src.core.computers.knock import KnockDesk, clean_label
from tests.python.computers.test_join_commit import JOIN, MAIN, world  # noqa: F401
from tests.python.computers.test_join_inproc import _join, _raw


async def _knock(port: int, fid: str, label: str = "doom", iid: str = "i" * 26):
    reader, writer = await _raw(port)
    writer.write(join_proto.MAGIC)
    await join_proto.write_message(writer, join_proto.knock(fid=fid, iid=iid, label=label))
    raw = await asyncio.wait_for(reader.read(), 5)
    writer.close()
    return raw, json.loads(raw[4:])


@pytest.mark.asyncio
async def test_knock_shows_the_owner_a_code_and_the_code_join_completes(world, monkeypatch):
    main, join = world
    clock = [1000.0]
    now = lambda: clock[0]  # noqa: E731
    invites = Invites(clock=now)
    told, topics = [], []
    desk = KnockDesk(invites, "air", clock=now, notify=topics.append, emit=lambda label, addr, kid: told.append((label, addr, kid)) or True,
                     rates=KnockRates(clock=now))
    findable = [True]
    srv = JoinServer(invites=invites, identity=main.identity, fed_key=main.key, public_key=main.public, own_iid=MAIN, own_label="air",
                     open_db=main.open_db, listener=main.listener, pack=main.pack, host="127.0.0.1", port=0, addresses=lambda: ["127.0.0.1"],
                     link_port=47110, app_version="t", fail_delay=0.0, lan_only=False, findable=lambda: findable[0], on_knock=desk.handle)
    monkeypatch.setattr(runtime, "_ACTIVE", types.SimpleNamespace(knocks=desk))

    assert await srv.sync() and srv.port and not invites.any_live()

    dirty = "Ad​‮am's " + "x" * 60
    raw, reply = await _knock(srv.port, "A" * 26, dirty)
    inv = invites.live()[0]
    assert reply["t"] == "knock_ok" and reply["main_label"] == "air" and reply["knock_id"] == inv.id and 0 < reply["expires_in"] <= 900
    assert inv.code.encode() not in raw and inv.link_secret.encode() not in raw and inv.secret not in raw
    code = inv.code

    (shown,) = (await computers_routes.get_knocks(None))["knocks"]
    assert shown["code"] == code and shown["id"] == inv.id and shown["addr"] == "127.0.0.1" and shown["fid_short"] == "AAAAAA"
    assert shown["label"] == clean_label(dirty, "A" * 26) and len(shown["label"]) <= 40 and "​" not in shown["label"] and "‮" not in shown["label"]
    assert told == [(shown["label"], "127.0.0.1", inv.id)] and "pack_knocks" in topics

    assert (await _knock(srv.port, "A" * 26))[1]["knock_id"] == inv.id and len(invites.live()) == 1
    assert (await _knock(srv.port, "B" * 26))[1] == join_proto.error("busy")
    assert (await _knock(srv.port, "B" * 26))[1] == join_proto.error("rate_limited")
    clock[0] += 61

    out = await _join(main, join, srv.port, mode="code", code=code)
    assert (out.main_install_id, out.kind) == (MAIN, "new") and (await computers_routes.get_knocks(None))["knocks"] == []

    _, again = await _knock(srv.port, "C" * 26)
    assert again["t"] == "knock_ok"
    cid = again["knock_id"]
    typed = invites.live()[0].code
    assert await computers_routes.delete_knock(cid, None) == {"deleted": True}
    with pytest.raises(JoinFailed) as gone:
        await _join(main, join, srv.port, mode="code", code=typed)
    assert gone.value.code == "no_invite"
    assert (await _knock(srv.port, "C" * 26))[1] == join_proto.error("refused")
    with pytest.raises(Exception) as missing:
        await computers_routes.delete_knock(cid, None)
    assert missing.value.status_code == 404 and missing.value.detail["code"] == "knock_not_found"

    findable[0] = False
    assert await srv.sync() is False and srv.port is None


@pytest.mark.asyncio
async def test_a_hostile_knock_cannot_retire_a_shown_code_rewrite_a_label_or_feed_the_pause():
    clock = [1000.0]
    now = lambda: clock[0]  # noqa: E731
    invites = Invites(clock=now)
    desk = KnockDesk(invites, "air", clock=now, rates=KnockRates(clock=now))
    shown = invites.mint("code")
    assert (await desk.handle(Knock_("A" * 26, "doom"), "10.0.0.7"))["code"] == "busy"
    assert shown.code is not None
    invites.cancel(shown.id)

    first = await desk.handle(Knock_("A" * 26, "doom"), "10.0.0.7")
    assert first["t"] == "knock_ok"
    await desk.handle(Knock_("A" * 26, "evil"), "10.0.0.9")
    (row,) = desk.pending()
    assert row["label"] == "doom" and row["addr"] == "10.0.0.7"

    inv = invites.live()[0]
    for _ in range(3):
        taken = invites.take_attempt("code")
        invites.finish_attempt(taken, ok=False, mode="code", addr="10.0.0.7")
    assert not invites.code_paused() and invites.live() == [] and len(invites._wrong) == 0  # noqa: SLF001

    again = await desk.handle(Knock_("B" * 26, "doom"), "10.0.0.7")
    assert again["t"] == "knock_ok"
    assert desk.dismiss(desk.pending()[0]["id"])
    clock[0] += 61
    assert (await desk.handle(Knock_("C" * 26, "doom"), "10.0.0.7"))["code"] == "refused"
    assert inv.knock


@pytest.mark.asyncio
async def test_knock_wrong_tries_hit_their_own_hourly_cap_and_knocks_pause():
    clock = [1000.0]
    now = lambda: clock[0]  # noqa: E731
    invites = Invites(clock=now)
    desk = KnockDesk(invites, "air", clock=now, rates=KnockRates(clock=now))
    for n in range(4):
        clock[0] += 61
        doc = await desk.handle(Knock_(chr(65 + n) * 26, "x"), f"192.0.2.{n + 1}")
        if doc["t"] != "knock_ok":
            break
        for _ in range(3):
            taken = invites.take_attempt("code")
            if taken is None:
                break
            invites.finish_attempt(taken, ok=False, mode="code", addr="192.0.2.1")
    assert invites.knock_paused() and not invites.code_paused()
    clock[0] += 61
    assert (await desk.handle(Knock_("Z" * 26, "x"), "192.0.2.99"))["code"] == "paused"


def Knock_(fid: str, label: str):  # noqa: N802
    from src.core.computers.knock import Knock

    return Knock(fid, "i" * 26, label)
