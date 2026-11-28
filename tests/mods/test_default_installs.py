
import asyncio
from types import SimpleNamespace

from src.api import catalog_default_installs as cdi


class _Ledger:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def find(self, item_id, scope, project):
        return self.rows.get(item_id)


def _request(rows):
    catalog = SimpleNamespace(ledger=lambda: _Ledger(rows))
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(catalog=catalog))))


def test_default_item_installs_once_then_the_owner_wins(tmp_path, monkeypatch):
    calls = []
    rows = {}

    async def snapshot(request):
        return object()

    async def preview(request, body):
        return SimpleNamespace(
            digest="d",
            body_sha="b",
            mod_report_sha="r",
            plan_token="t",
            mod_flagged_ack_needed=False,
            requires_warning_ack=False,
            flagged=False,
        )

    async def install(request, body):
        calls.append(body.item_id)
        assert body.consent.mod_trust and body.consent.mod_report_sha == "r"
        rows[body.item_id] = object()

    monkeypatch.setattr(cdi, "_snapshot", snapshot)
    monkeypatch.setattr(cdi, "resolve_item", lambda snap, item_id: (object(), object()))
    monkeypatch.setattr(cdi, "preview_install", preview)
    monkeypatch.setattr(cdi, "run_install", install)
    run = lambda: asyncio.run(cdi.install_defaults(_request(rows), ids=("nyedis/q",), state_dir=tmp_path))
    assert run() == ["nyedis/q"] and calls == ["nyedis/q"]
    rows.clear()
    assert run() == [] and calls == ["nyedis/q"]


def test_an_id_the_catalog_lacks_is_skipped_and_retried(tmp_path, monkeypatch):
    from fastapi import HTTPException

    async def snapshot(request):
        raise HTTPException(status_code=502, detail="offline")

    monkeypatch.setattr(cdi, "_snapshot", snapshot)
    assert asyncio.run(cdi.install_defaults(_request({}), ids=("nyedis/q",), state_dir=tmp_path)) == []
    from src.core.mods import owner_state

    assert not owner_state.was_offered("nyedis/q", state_dir=tmp_path)


def test_the_default_list_is_info_mode_and_a_computer_offered_the_old_id_is_offered_the_new_one(tmp_path):
    from src.core.catalog.default_items import DEFAULT_ITEM_IDS
    from src.core.mods import owner_state

    assert DEFAULT_ITEM_IDS == ("carnivore/info-mode",)
    owner_state.mark_offered("nyedis/quiet-tool-rows", state_dir=tmp_path)
    assert not owner_state.was_offered("carnivore/info-mode", state_dir=tmp_path)
