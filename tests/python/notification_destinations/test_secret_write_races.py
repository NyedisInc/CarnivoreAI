
from __future__ import annotations

import asyncio
import threading

from src.core.notifications.sync import secrets_sync, seen

URL = "https://hooks.slack.com/services/T0/B0/abc"
NEWER = "https://hooks.slack.com/services/T0/B0/newer"


def test_a_cancelled_create_keeps_its_secret_when_the_record_still_lands(service, keychain):
    gate, started = threading.Event(), threading.Event()
    real_update = service.destinations._docs.update

    def slow_update(mutate):
        started.set()
        gate.wait(5)
        return real_update(mutate)

    service.destinations._docs.update = slow_update

    async def scenario():
        task = asyncio.ensure_future(service.destinations.create("slack", "team", {}, {"url": URL}))
        while not started.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        gate.set()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0.2)
        return await service.destinations.list()

    listed = asyncio.run(scenario())
    assert len(listed) == 1 and len(keychain.items) == 1


def test_a_pull_cannot_overwrite_a_bundle_an_owner_edit_is_writing(service):
    async def scenario():
        created = await service.destinations.create("slack", "team", {}, {"url": URL})
        dest = created.destination["id"] if hasattr(created, "destination") else created.dest["id"]
        service.docs.update(lambda d, me: seen.forget(d, dest))
        secrets = service.destinations._secrets
        real_put = secrets.put_verified

        calls = []

        async def slow_put(dest_id, fields):
            calls.append(1)
            if len(calls) == 1:
                await asyncio.sleep(0.1)
            return await real_put(dest_id, fields)

        secrets.put_verified = slow_put

        async def fetch(ids):
            return {"secrets": {dest: {"rev": 1, "fields": {"url": URL}}}}

        pull = asyncio.ensure_future(secrets_sync.pull_stale(service.docs, secrets, fetch, "peer"))
        await asyncio.sleep(0.01)
        await service.destinations.update(dest, secret_patch={"url": NEWER})
        await pull
        return await secrets.get(dest)

    assert asyncio.run(scenario()) == {"url": NEWER}
