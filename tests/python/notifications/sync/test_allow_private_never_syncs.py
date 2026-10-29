
from __future__ import annotations

import asyncio
import json

from src.core.notifications.settings_doc import view
from src.core.notifications.sync import secrets_sync

from .test_converge import link_all, rounds

URL = "https://203.0.113.13/hook-SWITCHSENTINEL"


def test_switch_is_not_in_the_exchange_or_the_secrets_pull_and_starts_off_on_the_peer(cluster, make):
    a, b = make("A"), make("B")
    link_all(cluster, "A", "B")
    made = asyncio.run(a.service.destinations.create("webhook", "hook", {}, {"url": URL}, allow_private=True))
    dest = made.destination["id"]
    assert view.allow_private(a.doc(), dest) is True
    rounds(a, b)
    assert dest in view.dest_ids(b.doc())
    assert view.allow_private(b.doc(), dest) is False
    assert "allow_private" not in json.dumps(a.doc()["global"])
    sent = json.dumps([x[3] for x in cluster.sent if x[2].endswith("exchange")]) + json.dumps(cluster.answers)
    assert "allow_private" not in sent
    pulled = asyncio.run(secrets_sync.serve(a.service.docs, a.service.secrets, [dest]))
    assert "allow_private" not in json.dumps(pulled)
