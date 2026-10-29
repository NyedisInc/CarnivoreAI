
from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote

import structlog
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Label, Static

from src.tui import keys
from src.tui.api_client import AuthRequired, ServerUnavailable
from src.tui.listing_store import LIVENESS
from src.tui.strings import t

logger = structlog.get_logger(__name__)
APPROVALS_PATH = "/api/v1/approvals"
TOPIC = "approvals"
POLL_SECONDS = 30.0
APPROVABLE_KINDS = ("permission", "codex_approval", "folder_trust")
YES_LABELS = ("yes", "yes, proceed", "yes, i trust this folder")
_NAV_ACTIONS = ("cursor_down", "cursor_up", "top", "bottom")


def plain_yes(item: dict[str, Any]) -> Optional[str]:
    if item.get("source") != "dialog" or item.get("kind") not in APPROVABLE_KINDS or item.get("multi_select"):
        return None
    for label in item.get("options") or []:
        text = str(label).strip().lower()
        if text.endswith(" (y)"):
            text = text[:-4]
        if text in YES_LABELS:
            return str(label)
    return None


def answer_request(item: dict[str, Any], approve: bool) -> Optional[tuple[str, dict[str, Any]]]:
    if item.get("source") == "agent_action":
        if approve and item.get("confirm_text"):
            return None
        verb = "approve" if approve else "deny"
        return f"/api/v1/agent-actions/{quote(str(item.get('id') or ''), safe='')}/{verb}", {}
    if item.get("source") != "dialog":
        return None
    if approve:
        label = plain_yes(item)
        choice: dict[str, Any] = {"option": label} if label else {}
    else:
        choice = {"dismiss": True}
    if not choice:
        return None
    sid = quote(str(item.get("session_id") or ""), safe="")
    return f"/api/v1/sessions/{sid}/dialog/answer", {"fingerprint": item.get("fingerprint") or "", "choice": choice}


def refusal_text(payload: Any) -> str:
    detail = payload.get("detail") if isinstance(payload, dict) else None
    reason = detail.get("reason") if isinstance(detail, dict) else None
    if isinstance(reason, str) and reason:
        text = t(f"approvals.reason.{reason}")
        return reason if text == f"approvals.reason.{reason}" else text
    return t("approvals.failed")


def item_summary(item: dict[str, Any]) -> str:
    if item.get("source") == "agent_action":
        return str(item.get("summary") or item.get("action") or "")
    if item.get("source") == "startup_prompt":
        return t("approvals.startup.waiting")
    return str(item.get("question") or "")


def item_detail(item: dict[str, Any]) -> str:
    parts = [item_summary(item), str(item.get("body") or "")]
    if item.get("options"):
        parts.append("  ".join(f"[{o}]" for o in item["options"]))
    return "\n".join(p for p in parts if p)


class ApprovalsTable(DataTable[Any]):

    BINDINGS = keys.textual_bindings(keys.APPROVALS) + [
        b for b in keys.textual_bindings(keys.SESSIONS) if b.action in _NAV_ACTIONS
    ]

    def action_cursor_down(self) -> None:
        super().action_cursor_down()

    def action_cursor_up(self) -> None:
        super().action_cursor_up()

    def action_top(self) -> None:
        self.move_cursor(row=0)

    def action_bottom(self) -> None:
        self.move_cursor(row=max(self.row_count - 1, 0))

    def action_approve(self) -> None:
        self.parent.answer(True)  # type: ignore[union-attr]

    def action_deny(self) -> None:
        self.parent.answer(False)  # type: ignore[union-attr]


class ApprovalsPane(Vertical):

    DEFAULT_CSS = """
    ApprovalsPane #approvals-detail { height: auto; max-height: 12; }
    ApprovalsPane #approvals-note { height: 1; }
    """

    def __init__(self) -> None:
        super().__init__(id="pane-approvals")
        self.items: list[dict[str, Any]] = []
        self._busy = False
        self._unsub: Any = None

    def compose(self) -> ComposeResult:
        yield ApprovalsTable(id="approvals-table", cursor_type="row", zebra_stripes=False)
        yield Static("", id="approvals-detail")
        yield Label("", id="approvals-note")

    def on_mount(self) -> None:
        table = self.query_one(ApprovalsTable)
        for col in ("where", "session", "kind", "asks"):
            table.add_column(t(f"tui.approvals.col.{col}"), key=col)
        events = self.app.events  # type: ignore[attr-defined]
        self._unsub = events.on_topics(self._topics)
        self.set_interval(POLL_SECONDS, self._poll)
        self.refresh_items()

    def on_unmount(self) -> None:
        if self._unsub:
            self._unsub()

    def _topics(self, topics: list[str]) -> None:
        if TOPIC in topics or LIVENESS in topics:
            self.refresh_items()

    def _poll(self) -> None:
        if not self.app.events.topic_pushed(TOPIC):  # type: ignore[attr-defined]
            self.refresh_items()

    def refresh_items(self) -> None:
        self.run_worker(self._read(), exclusive=True, group="approvals-read")

    async def _read(self) -> None:
        try:
            resp = await self.app.client.request("GET", APPROVALS_PATH)  # type: ignore[attr-defined]
        except ServerUnavailable:
            self.query_one("#approvals-note", Label).update(t("approvals.load_failed"))
            return
        except AuthRequired:
            self.app.show_login()  # type: ignore[attr-defined]
            return
        if resp.status_code != 200:
            self.query_one("#approvals-note", Label).update(t("approvals.load_failed"))
            return
        items = resp.json().get("items")
        self.items = [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []
        self.render_items()

    def render_items(self) -> None:
        table = self.query_one(ApprovalsTable)
        keep = self.items[table.cursor_row].get("id") if self.items and table.cursor_row < len(self.items) else None
        table.clear()
        for item in self.items:
            where = str(item.get("host") or "") if item.get("host") not in (None, "local") else ""
            name = item.get("session_name") or item.get("caller") or item.get("session_id") or ""
            table.add_row(where, str(name), str(item.get("kind") or item.get("action") or ""),
                          item_summary(item).replace("\n", " "), key=str(item.get("id") or id(item)))
        for i, item in enumerate(self.items):
            if keep is not None and item.get("id") == keep:
                table.move_cursor(row=i)
                break
        self.query_one("#approvals-note", Label).update("" if self.items else t("approvals.empty"))
        self._show_detail()

    def _show_detail(self) -> None:
        row = self.query_one(ApprovalsTable).cursor_row
        self.query_one("#approvals-detail", Static).update(
            item_detail(self.items[row]) if row < len(self.items) else "")

    def on_data_table_row_highlighted(self) -> None:
        self._show_detail()

    def answer(self, approve: bool) -> None:
        row = self.query_one(ApprovalsTable).cursor_row
        if self._busy or row >= len(self.items):
            return
        request = answer_request(self.items[row], approve)
        if request is None:
            self.app.notify(t("tui.approvals.cannot_answer"), severity="warning")
            return
        self._busy = True
        self.run_worker(self._send(*request, approve), group="approvals-answer")

    async def _send(self, path: str, body: dict[str, Any], approve: bool) -> None:
        try:
            resp = await self.app.client.request("POST", path, json=body)  # type: ignore[attr-defined]
        except ServerUnavailable:
            self.app.notify(t("approvals.failed"), severity="error")
        except AuthRequired:
            self.app.show_login()  # type: ignore[attr-defined]
            return
        else:
            if resp.status_code == 200:
                self.app.notify(t("tui.approvals.approved" if approve else "tui.approvals.denied"))
            else:
                try:
                    payload = resp.json()
                except ValueError:
                    payload = None
                self.app.notify(refusal_text(payload), severity="error")
        finally:
            self._busy = False
        self.refresh_items()
