
from __future__ import annotations

import asyncio
import json

from src.core.notifications import doc_model
from src.core.notifications.settings_doc import ticks, view

SECRET_URL = "https://hooks.slack.com/services/T0/B0/SYNCSENTINEL9f3a"


def link_all(cluster, *names):
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            cluster.link(a, b)


def rounds(*computers, n=3):
    for _ in range(n):
        for c in computers:
            c.sync()


def create(c, name="team", scope="global", url=SECRET_URL):
    made = asyncio.run(c.service.destinations.create("slack", name, {}, {"url": url}, scope=scope))
    return made.destination["id"]


def test_two_computers_converge_after_edits_on_both_sides(cluster, make):
    a, b = make("A"), make("B")
    link_all(cluster, "A", "B")
    dest = create(a)
    ticks.put_default(b.service.docs, "session.finished", False)
    assert a.sync() == {"B": "refused"}
    rounds(a, b)
    assert a.doc()["global"] == b.doc()["global"]
    assert view.dest_scope(b.doc(), dest) == "global"
    assert view.default_tick(a.doc(), "session.finished") is False
    ticks.put_tick(b.service.docs, "screen", "session.finished", False)
    rounds(b, a, n=1)
    assert a.doc()["global"] == b.doc()["global"]
    assert view.cell(a.doc(), "screen", "session.finished").value is False


def test_a_third_computer_converges_through_the_second(cluster, make):
    a, b, c = make("A"), make("B"), make("C")
    cluster.link("A", "B")
    cluster.link("B", "C")
    dest = create(a)
    rounds(a, b, c)
    assert c.doc()["global"] == a.doc()["global"]
    assert view.dest_scope(c.doc(), dest) == "global"
    assert not any(x[0] == "C" and x[1] == "A" for x in cluster.sent)
    assert c.keychain.items == a.keychain.items and c.keychain.items


def test_a_locally_pinned_override_survives_every_exchange(cluster, make):
    a, b = make("A"), make("B")
    link_all(cluster, "A", "B")
    create(a)
    rounds(a, b)
    ticks.put_tick(a.service.docs, "screen", "session.finished", False, "local")
    for _ in range(2):
        ticks.put_tick(b.service.docs, "screen", "session.finished", True, "global")
        rounds(a, b, n=1)
        assert view.cell(a.doc(), "screen", "session.finished").value is False
        assert view.cell(a.doc(), "screen", "session.finished").source == "local"
        assert doc_model.is_pinned(a.doc(), doc_model.tick_path("screen", "session.finished"))
    assert view.cell(b.doc(), "screen", "session.finished").value is True


def test_a_tombstone_deletes_on_the_peer_and_drops_its_keychain_item(cluster, make):
    a, b = make("A"), make("B")
    link_all(cluster, "A", "B")
    dest = create(a)
    rounds(a, b)
    assert b.keychain.items and view.dest_scope(b.doc(), dest) == "global"
    asyncio.run(a.service.destinations.delete(dest))
    rounds(a, b, n=1)
    assert view.dest_scope(b.doc(), dest) is None
    assert doc_model.is_tombstone(b.doc()["global"][doc_model.dest_path(dest)])
    assert b.keychain.items == {}


def test_the_local_part_never_appears_in_an_exchange_body(cluster, make):
    a, b = make("A"), make("B")
    link_all(cluster, "A", "B")
    local_dest = create(a, name="mine", scope="local", url="https://hooks.slack.com/services/T9/B9/LOCALONLY")
    ticks.set_paused(a.service.docs, True)
    ticks.put_tick(a.service.docs, "screen", "session.finished", False, "local")
    rounds(a, b)
    blob = json.dumps([x[3] for x in cluster.sent] + cluster.answers)
    assert local_dest not in blob and "LOCALONLY" not in blob and "local/" not in blob and "paused" not in blob
    assert view.dest_scope(b.doc(), local_dest) is None and not view.paused(b.doc())
    assert "secret_seen" not in blob and "install_id" not in blob


def test_unchanged_state_answers_no_change_and_writes_nothing(cluster, make):
    a, b = make("A"), make("B")
    link_all(cluster, "A", "B")
    create(a)
    rounds(a, b)
    assert a.doc()["global"] == b.doc()["global"]
    revs = (a.doc()["rev"], b.doc()["rev"])
    cluster.sent.clear()
    cluster.answers.clear()
    assert a.sync() == {"B": "no_change"}
    assert b.sync() == {"A": "no_change"}
    assert (a.doc()["rev"], b.doc()["rev"]) == revs
    assert cluster.answers == [{"status": "no_change"}] * 2
    assert all(x[3]["entries"] is not None for x in cluster.sent) and len(cluster.sent) == 2


def test_an_older_peer_is_reported_and_never_called(cluster, make):
    a = make("A")
    make("B")
    link_all(cluster, "A", "B")
    cluster.minors["B"] = 0
    create(a)
    assert a.sync() == {"B": "older"}
    assert cluster.sent == [] and cluster.grants == set()
    last = a.manager.status.get("B")
    assert last is not None and last.result == "older"


def test_the_per_peer_off_switch_stops_exchange_and_secret_pulls(cluster, make):
    from src.core.notifications.sync import status as st

    a, b = make("A"), make("B")
    link_all(cluster, "A", "B")
    create(a)
    b.service.docs.update(lambda doc, me: st.with_enabled(doc, "A", False))
    assert b.sync() == {"A": "off"}
    assert [x for x in cluster.sent if x[0] == "B"] == []
    a.service.docs.update(lambda doc, me: st.with_enabled(doc, "B", False))
    assert a.sync() == {"B": "off"}
    assert cluster.sent == [] and b.keychain.items == {} and cluster.grants == set()
    b.service.docs.update(lambda doc, me: st.with_enabled(doc, "A", True))
    a.service.docs.update(lambda doc, me: st.with_enabled(doc, "B", True))
    rounds(a, b)
    assert b.keychain.items


def test_a_peer_that_has_not_granted_the_scope_is_refused_not_called_again(cluster, make):
    a, b = make("A"), make("B")
    cluster.link("A", "B")
    create(a)

    async def no_grant(install_id, granted):
        return None

    b.manager.gateway.set_scope = no_grant
    a.manager.gateway.set_scope = no_grant
    assert a.sync() == {"B": "refused"}
    assert view.dest_scope(b.doc(), "d_000000000000") is None


def test_a_large_document_splits_into_buckets_each_under_the_peer_limit(cluster, make):
    a, b = make("A"), make("B")
    link_all(cluster, "A", "B")
    for i in range(40):
        create(a, name=f"team{i}", url=f"https://hooks.slack.com/services/T0/B0/k{i}")
    from src.core.notifications.sync import wire

    assert wire.body_size(a.doc()["global"]) > wire.SOFT_LIMIT_BYTES
    rounds(a, b)
    assert a.doc()["global"] == b.doc()["global"]
    assert len(b.keychain.items) == 40
    assert max(len(json.dumps(x[3])) for x in cluster.sent) < 64 * 1024
    assert len({x[3]["bucket"] for x in cluster.sent if x[2].endswith("exchange")}) > 1


def test_incoming_destinations_beyond_the_cap_are_refused(cluster, make, monkeypatch):
    from src.core.notifications.sync import merge as merge_mod

    monkeypatch.setattr(merge_mod, "MAX_GLOBAL_DESTINATIONS", 3)
    a, b = make("A"), make("B")
    link_all(cluster, "A", "B")
    ids = [create(a, name=f"t{i}", url=f"https://hooks.slack.com/services/T0/B0/k{i}") for i in range(4)]
    rounds(a, b)
    from src.core.notifications.sync import sanitize

    assert len(sanitize.live_dest_ids(b.doc()["global"])) == 3
    assert set(sanitize.live_dest_ids(b.doc()["global"])) < set(ids)
