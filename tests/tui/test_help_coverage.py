
from __future__ import annotations

import asyncio
import re
from typing import Any

from textual.app import App
from textual.widgets import Static

from src.tui import keys
from src.tui.app import MainScreen
from src.tui.screens.approvals import ApprovalsTable
from src.tui.screens.catalog import CatalogBoard
from src.tui.screens.help import HelpScreen, help_lines
from src.tui.screens.ledger import LedgerBoard
from src.tui.screens.sessions import SessionsTable
from src.tui.offline.app import OfflineTable

HANDLERS: dict[str, Any] = {
    keys.APP: MainScreen,
    keys.SESSIONS: SessionsTable,
    keys.APPROVALS: ApprovalsTable,
    keys.LEDGER: LedgerBoard,
    keys.CATALOG: CatalogBoard,
    keys.HELP: HelpScreen,
    keys.OFFLINE: OfflineTable,
}


def test_every_binding_has_a_help_row_and_a_handler() -> None:
    assert {k.scope for k in keys.KEYS} <= set(HANDLERS)
    for k in keys.KEYS:
        handler = HANDLERS[k.scope]
        name = re.match(r"\w+", k.action).group(0)
        assert callable(getattr(handler, f"action_{name}", None)), (k.scope, k.action)
        assert any(r[0] == k.label and r[2] == k.scope for r in keys.help_rows())
        assert k.live, (k.scope, k.action)

    body = "\n".join(help_lines())
    for label, desc, _scope, _live in keys.help_rows():
        assert label in body and desc in body

    async def run() -> str:
        class Host(App[None]):
            pass

        async with Host().run_test() as pilot:
            await pilot.app.push_screen(HelpScreen())
            await pilot.pause()
            shown = str(pilot.app.screen.query_one("#help-body", Static).render())
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(pilot.app.screen, HelpScreen)
            return shown

    shown = asyncio.run(run())
    assert all(label in shown for label, *_ in keys.help_rows())
