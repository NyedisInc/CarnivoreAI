
from __future__ import annotations

import dataclasses
import os
from typing import Any, Optional

import structlog
from rich.text import Text
from textual import on
from textual.app import ComposeResult, SuspendNotSupported
from textual.containers import Vertical
from textual.widgets import DataTable, Input, Label

from src.tui import attach, keys, theme
from src.tui.api_client import AuthRequired, ServerUnavailable
from src.tui.led import led_for, use_ascii
from src.tui.screens import session_actions as act
from src.tui.screens import session_rows as sr
from src.tui.strings import t

logger = structlog.get_logger(__name__)
PREFERENCES_PATH = "/api/v1/preferences"


class SessionsTable(DataTable[Any]):

    BINDINGS = keys.textual_bindings(keys.SESSIONS)

    def pane(self) -> "SessionsPane":
        return self.parent  # type: ignore[return-value]

    def action_cursor_down(self) -> None:
        super().action_cursor_down()

    def action_cursor_up(self) -> None:
        super().action_cursor_up()

    def action_top(self) -> None:
        self.move_cursor(row=0)

    def action_bottom(self) -> None:
        self.move_cursor(row=max(self.row_count - 1, 0))

    def action_filter(self) -> None:
        self.pane().open_filter()

    def action_sort(self) -> None:
        self.pane().toggle_sort()

    def action_attach(self) -> None:
        self.pane().attach_selected()

    def action_watch(self) -> None:
        self.pane().attach_selected(read_only=True)

    def action_new(self) -> None:
        self.pane().run_worker(self.pane().new_session(), exclusive=True, group="action")

    def action_stop(self) -> None:
        self.pane().act("stop")

    def action_restart(self) -> None:
        self.pane().act("restart")

    def action_arm(self) -> None:
        self.pane().arm_selected()

    def action_mark_read(self) -> None:
        self.pane().act("mark_read")


class SessionsPane(Vertical):

    DEFAULT_CSS = """
    SessionsPane #sessions-filter { display: none; height: 3; }
    SessionsPane.filtering #sessions-filter { display: block; }
    SessionsPane #sessions-note { height: 1; }
    """

    def __init__(self) -> None:
        super().__init__(id="pane-sessions")
        self.arrangement: Optional[dict[str, Any]] = None
        self.sort_mode = "arranged"
        self.filter_text = ""
        self.shown: list[sr.Row] = []
        self._unsub: Any = None
        self._ascii = use_ascii()
        self._transport: Optional[str] = None
        self._arranged = False
        self._armed: Optional[str] = None

    @property
    def armed(self) -> Optional[str]:
        return self._armed

    @armed.setter
    def armed(self, key: Optional[str]) -> None:
        self._armed = key
        self.set_class(key is not None, "armed")

    def compose(self) -> ComposeResult:
        yield Input(placeholder=t("tui.sessions.filter_prompt"), id="sessions-filter")
        yield SessionsTable(id="sessions-table", cursor_type="row", zebra_stripes=False)
        yield Label("", id="sessions-note")

    def on_mount(self) -> None:
        table = self.query_one(SessionsTable)
        table.add_column("", key="led", width=3)
        for col in ("name", "project", "agent", "status", "where"):
            table.add_column(t(f"tui.sessions.col.{col}"), key=col)
        listing = self.app.events.listing  # type: ignore[attr-defined]
        self._unsub = listing.on_change(lambda _names: self.render_rows())
        self.render_rows()
        table.focus()
        self.run_worker(self.refresh_arrangement(), exclusive=True, group="arrangement")

    def on_unmount(self) -> None:
        if self._unsub:
            self._unsub()

    async def refresh_arrangement(self) -> None:
        try:
            resp = await self.app.client.request("GET", PREFERENCES_PATH)  # type: ignore[attr-defined]
        except AuthRequired:
            self.app.show_login()  # type: ignore[attr-defined]
            return
        except ServerUnavailable as exc:
            logger.info("tui_arrangement_unavailable", error=type(exc).__name__)
            return
        if resp.status_code != 200:
            return
        value = (resp.json().get("values") or {}).get("drawer_arrangement")
        self.arrangement = value if isinstance(value, dict) else None
        self.render_rows(keep_cursor=self._arranged)
        self._arranged = True

    def _rows(self) -> list[sr.Row]:
        listing = self.app.events.listing  # type: ignore[attr-defined]
        rows = sr.visible(listing.rows("list") or [])
        rows = sr.sort_by_status(rows) if self.sort_mode == "status" else sr.arrange(rows, self.arrangement)
        transport = "disconnected" if getattr(self.app.events, "down", False) else None  # type: ignore[attr-defined]
        self._transport = transport
        return [r for r in rows if sr.matches(r, self.filter_text, led_for(r, transport=transport).label)]

    def render_rows(self, keep_cursor: bool = True) -> None:
        table = self.query_one(SessionsTable)
        keep = None
        if keep_cursor and self.shown and table.cursor_row < len(self.shown):
            keep = sr.row_key(self.shown[table.cursor_row])
        self.shown = self._rows()
        table.clear()
        for row in self.shown:
            led = led_for(row, transport=self._transport)
            where = (row.get("host_label") or row.get("host_key") or "") if sr.is_remote(row) else ""
            table.add_row(
                Text(led.glyph(self._ascii), style=theme.active().hue(led.hue)), sr.row_name(row), row.get("project_name") or "",
                row.get("agent_family") or "", led.label, where, key=sr.row_key(row) or str(id(row)),
            )
        if keep is not None:
            for i, row in enumerate(self.shown):
                if sr.row_key(row) == keep:
                    table.move_cursor(row=i)
                    break
        self.query_one("#sessions-note", Label).update("" if self.shown else t("tui.sessions.empty"))

    def open_filter(self) -> None:
        self.add_class("filtering")
        self.query_one("#sessions-filter", Input).focus()

    def toggle_sort(self) -> None:
        self.sort_mode = "status" if self.sort_mode == "arranged" else "arranged"
        self.app.notify(t(f"tui.sessions.sort.{self.sort_mode}"))
        self.render_rows()

    def selected(self) -> Optional[sr.Row]:
        table = self.query_one(SessionsTable)
        return self.shown[table.cursor_row] if 0 <= table.cursor_row < len(self.shown) else None

    def _local_row(self) -> Optional[sr.Row]:
        row = self.selected()
        if row is None:
            return None
        if sr.is_remote(row):
            self.app.notify(t("tui.action.read_only"))
            return None
        return row

    def attach_selected(self, read_only: bool = False) -> None:
        row = self._local_row()
        if row is None:
            return
        name = attach.tmux_name_of(row)
        if name is None:
            self.app.notify(t("tui.action.no_tmux"))
            return
        socket = attach.socket_name()
        plan = attach.plan_attach(name, socket, os.environ, read_only=read_only)
        if plan.suspend:
            size = attach.read_pane_size(plan.argvs[0][:3], name)
            preamble = attach.attach_preamble(size, resize_terminal=True, read_only=read_only)
            plan = dataclasses.replace(plan, preamble=preamble)
        try:
            if plan.suspend:
                with self.app.suspend():
                    rc = attach.run(plan)
            else:
                rc = attach.run(plan)
        except SuspendNotSupported:
            self.app.notify(t("tui.action.no_suspend"))
            return
        if rc != 0:
            self.app.notify(t("tui.action.attach_failed"), severity="error")

    def arm_selected(self) -> None:
        row = self._local_row()
        if row is None:
            return
        if not act.is_live(row):
            self.app.notify(t("tui.action.not_live"))
            return
        self.armed = sr.row_key(row)
        self.app.notify(t("tui.action.armed"), severity="warning")

    def act(self, name: str) -> None:
        row = self._local_row()
        if row is not None:
            self.run_worker(self._do(name, row), exclusive=True, group="action")

    async def _do(self, name: str, row: sr.Row) -> None:
        client = self.app.client  # type: ignore[attr-defined]
        tmux_name, uuid = attach.tmux_name_of(row), row.get("session_uuid")
        try:
            if name == "mark_read" and tmux_name:
                result = await act.mark_read(client, tmux_name)
            elif name == "stop" and uuid:
                result = await act.stop(client, str(uuid))
            elif name == "restart" and tmux_name:
                live = act.is_live(row)
                if live and self.armed != sr.row_key(row):
                    self.app.notify(t("tui.action.arm_first"), severity="warning")
                    return
                self.armed = None
                result = await act.restart(client, tmux_name, live_confirmed=live)
            else:
                self.app.notify(t("tui.action.no_tmux"))
                return
        except AuthRequired:
            self.app.show_login()  # type: ignore[attr-defined]
            return
        except ServerUnavailable:
            self.app.notify(t("tui.action.unreachable"), severity="error")
            return
        self.app.notify(result[1], severity="information" if result[0] else "error")

    async def new_session(self) -> None:
        client = self.app.client  # type: ignore[attr-defined]
        row = self.selected()
        session = row.get("session") if row else None
        folder = (session.get("working_dir") if isinstance(session, dict) else None) or "~"
        try:
            profiles = await act.list_profiles(client)
            choice = await self.app.push_screen_wait(act.NewSessionModal(profiles, str(folder)))
            if choice is None:
                return
            ok, message = await act.create(client, choice[0], choice[1])
        except AuthRequired:
            self.app.show_login()  # type: ignore[attr-defined]
            return
        except ServerUnavailable:
            self.app.notify(t("tui.action.unreachable"), severity="error")
            return
        self.app.notify(message, severity="information" if ok else "error")

    @on(DataTable.RowHighlighted)
    def _cursor_moved(self) -> None:
        row = self.selected()
        if self.armed and (row is None or sr.row_key(row) != self.armed):
            self.armed = None

    @on(Input.Changed, "#sessions-filter")
    def _filter_changed(self, event: Input.Changed) -> None:
        self.filter_text = event.value
        self.render_rows()

    @on(Input.Submitted, "#sessions-filter")
    def _filter_commit(self) -> None:
        self.query_one(SessionsTable).focus()

    def on_key(self, event: Any) -> None:
        if event.key == "escape" and self.has_class("filtering"):
            event.stop()
            self.query_one("#sessions-filter", Input).value = ""
            self.remove_class("filtering")
            self.query_one(SessionsTable).focus()

