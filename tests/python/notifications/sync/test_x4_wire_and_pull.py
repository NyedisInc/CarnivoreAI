
from __future__ import annotations

import asyncio
import types as pytypes

from src.core.notifications.destinations import secrets as secret_store
from src.core.notifications.sync import merge as merge_mod
from src.core.notifications.sync import seen
from src.core.notifications.sync import secrets_sync, wire

from .test_secrets import URL, create
from .test_converge import link_all, rounds


def test_a_tombstone_merged_before_a_split_still_reports_its_deleted_destination(monkeypatch):
    store = pytypes.SimpleNamespace(snapshot=lambda: {"global": {"a": {}, "b": {}}})
    monkeypatch.setattr(wire, "plan_buckets", lambda snap, minimum=1: 2)
    monkeypatch.setattr(wire, "split_map", lambda snap, n: [{"a": {}}, {"b": {}}])
    seen_calls = []

    async def call(body):
        seen_calls.append((body["buckets"], body["bucket"]))
        if body["buckets"] == 2 and body["bucket"] == 0:
            return {"status": "ok", "entries": {"x": {}}}
        if body["buckets"] == 2:
            return {"status": "split", "buckets": 4}
        return {"status": "no_change"}

    monkeypatch.setattr(merge_mod, "merge_into",
                        lambda s, entries, now: merge_mod.MergeOutcome(True, {}, ("d_0123456789ab",)))
    result = asyncio.run(wire.run_exchange(store, call, lambda: 1.0))
    assert (4, 0) in seen_calls
    assert result.deleted_dests == ("d_0123456789ab",) and result.changed is True


def test_one_bad_secret_id_does_not_abort_the_rest_of_the_pull(cluster, make, monkeypatch):
    a, b = make("A"), make("B")
    link_all(cluster, "A", "B")
    one = create(a, name="one", url=URL)
    two = create(a, name="two", url=URL + "2")
    rounds(a, b, n=1)
    b.service.docs.update(lambda d, me: seen.forget(seen.forget(d, one), two))
    stale = seen.stale_destinations(b.doc())
    assert sorted(stale) == sorted([one, two])
    real = b.service.secrets.put_verified
    bad = stale[0]

    async def flaky(dest_id, fields):
        if dest_id == bad:
            raise secret_store.InvalidDestinationId("bad id")
        return await real(dest_id, fields)

    async def fetch(ids):
        return {"secrets": {i: {"rev": 1, "fields": {"url": URL if i == one else URL + "2"}} for i in ids}}

    monkeypatch.setattr(b.service.secrets, "put_verified", flaky)
    result = asyncio.run(secrets_sync.pull_stale(b.service.docs, b.service.secrets, fetch, "A"))
    assert bad in result.still_stale and len(result.stored) == len(stale) - 1
