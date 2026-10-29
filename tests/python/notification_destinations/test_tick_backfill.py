
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("fastapi")

from src.core.notifications import doc_model  # noqa: E402
from src.core.notifications.destinations import tick_backfill  # noqa: E402
from src.core.notifications.settings_doc import view  # noqa: E402

from .test_settings_and_destinations import BASE, create, make_client  # noqa: E402

TYPE = "pack.skills"


def _forget(service, dest_id):
    def mutate(doc, me):
        out = {**doc, "global": {k: v for k, v in doc["global"].items() if k != doc_model.tick_path(dest_id, TYPE)},
               "local": {k: v for k, v in doc["local"].items() if k != doc_model.tick_path(dest_id, TYPE)}}
        return out
    service.docs.update(mutate)


def test_existing_destinations_get_the_pack_skills_tick_once_and_an_untick_stays(service):
    client = make_client(service)
    dest = create(client)["destination"]["id"]
    _forget(service, dest)
    assert view.cell(service.docs.snapshot(), dest, TYPE).value is False
    assert asyncio.run(tick_backfill.backfill_type_ticks(service.docs)) == 1
    assert view.cell(service.docs.snapshot(), dest, TYPE).value is True
    assert asyncio.run(tick_backfill.backfill_type_ticks(service.docs)) == 0
    service.docs.update(lambda doc, me: doc_model.set_global(doc, doc_model.tick_path(dest, TYPE), False, me))
    assert asyncio.run(tick_backfill.backfill_type_ticks(service.docs)) == 0
    assert view.cell(service.docs.snapshot(), dest, TYPE).value is False
