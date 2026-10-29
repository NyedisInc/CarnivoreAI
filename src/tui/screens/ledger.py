
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from rich.text import Text

from src.tui import keys
from src.tui.screens.read_board import Board, ReadBoardPane
from src.tui.strings import t

LEDGER_PATH = "/api/v1/provider-ledger"
STATE_STYLE = {"ok": "ansi_green", "rate_limited": "ansi_yellow", "expired": "ansi_red", "refused": "ansi_red",
               "missing": "ansi_red", "error": "ansi_red", "unknown": "ansi_white"}


class LedgerBoard(Board):

    BINDINGS = keys.textual_bindings(keys.LEDGER)


def _when(stamp: Optional[str], now: Optional[datetime] = None) -> str:
    if not stamp:
        return ""
    try:
        at = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    secs = int((at - (now or datetime.now(timezone.utc))).total_seconds())
    if secs <= 0:
        return "now"
    days, rest = divmod(secs, 86400)
    hours, rest = divmod(rest, 3600)
    return f"{days}d {hours}h" if days else f"{hours}h {rest // 60:02d}m"


def _usage(windows: list[dict[str, Any]]) -> str:
    return "  ".join(f"{w.get('label', '')} {round(float(w.get('used_pct') or 0))}%" for w in windows)


class LedgerPane(ReadBoardPane):

    path = LEDGER_PATH
    topic = "provider_ledger"
    pane_id = "pane-ledger"

    def make_board(self) -> Board:
        return LedgerBoard(id="ledger-table", cursor_type="row", zebra_stripes=False)

    def setup_columns(self, board: Board) -> None:
        for col in ("account", "provider", "plan", "state", "usage", "resets", "error"):
            board.add_column(t(f"tui.ledger.col.{col}"), key=col)

    def paint(self, board: Board, data: dict[str, Any]) -> str:
        board.clear()
        for acct in data.get("accounts") or []:
            state = str(acct.get("credential_state") or "unknown")
            windows = acct.get("windows") or []
            resets = min((w["resets_at"] for w in windows if w.get("resets_at")), default=None)
            board.add_row(
                acct.get("name") or acct.get("id") or "", acct.get("provider") or "", acct.get("plan") or "",
                Text(t(f"tui.ledger.state.{state}"), style=STATE_STYLE.get(state, "ansi_white")),
                _usage(windows) or t("tui.ledger.never"), _when(resets), acct.get("error") or "",
                key=str(acct.get("id") or id(acct)),
            )
        total = data.get("total") or {}
        parts = [t("tui.ledger.total").replace("{n}", str(total.get("accounts", 0)))]
        parts.append(_usage(total.get("windows") or []))
        if not (data.get("loop") or {}).get("alive", True):
            parts.append(t("tui.ledger.loop_dead"))
        self.query_one(".read-note").update("" if board.row_count else t("tui.ledger.empty"))
        return "  ".join(p for p in parts if p)
