
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.core import session_journal_store as store
from src.core import session_sleep
from src.core.session_delivery import bring_up


def _write_offer(state_dir: Path, state: str = "open") -> None:
    journal = store.empty_journal()
    journal["offer"] = {"id": "o1", "state": state, "candidates": [{"session_uuid": "u970", "tmux_name": "carnivore_Carnivore"}]}
    store.ensure_private(state_dir)
    assert store.save_journal(state_dir, journal)


def test_open_offer_name_is_reserved_and_closed_offer_is_not(tmp_path: Path) -> None:
    _write_offer(tmp_path)
    assert "carnivore_Carnivore" in session_sleep.reserved_names({"carnivore_x"}, db_path=tmp_path / "carnivore.db")
    _write_offer(tmp_path, state="accepted")
    assert "carnivore_Carnivore" not in session_sleep.reserved_names(set(), db_path=tmp_path / "carnivore.db")


def test_scheduled_start_is_refused_while_an_offer_lists_the_project(monkeypatch: pytest.MonkeyPatch) -> None:
    class Ops:
        started = False

        async def start(self, project_id: int) -> str:
            self.started = True
            return "ses_new"

    ops = Ops()
    monkeypatch.setattr(bring_up, "offer_holds_projects", lambda: {7})
    with pytest.raises(bring_up.RestoreOfferOpen):
        asyncio.run(bring_up.start_in_project(ops, 7))
    assert ops.started is False
    assert bring_up.RestoreOfferOpen.code in bring_up.BUSY_CODES
