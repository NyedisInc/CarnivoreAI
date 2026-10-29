
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import structlog
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.widgets import DataTable, Footer, Label

from src.tui import attach, keys, theme
from src.tui.app import textual_theme
from src.tui.led import use_ascii
from src.tui.offline.listing import OfflineRow, list_rows
from src.tui.offline.socket_check import OfflineContext
from src.tui.offline.tmux_cmd import OfflineTmuxError, TmuxCommandFailed, TmuxNotRunning, clean_env, probe_session
from src.tui.screens.help import HelpScreen
from src.tui.strings import t

logger = structlog.get_logger(__name__)


def state_text(row: OfflineRow) -> str:
    if row.dead:
        return t("tui.offline.state.dead")
    if row.attached:
        return t("tui.offline.state.attached").replace("{count}", str(row.attached))
    return t("tui.offline.state.running")


def error_text(err: OfflineTmuxError) -> str:
    if isinstance(err, TmuxNotRunning):
        return t("tui.offline.not_running")
    detail = err.detail if isinstance(err, TmuxCommandFailed) else str(err)
    return t("tui.offline.failed").replace("{detail}", detail)


class OfflineTable(DataTable[Any]):

    BINDINGS = keys.textual_bindings(keys.OFFLINE)

    @property
    def tui(self) -> "OfflineTui":
        app = self.app
        assert isinstance(app, OfflineTui)
        return app

    def action_type(self) -> None:
        self.tui.attach_selected(read_only=False)

    def action_watch(self) -> None:
        self.tui.attach_selected(read_only=True)

    def action_fit(self) -> None:
        self.tui.toggle_fit()

    def action_show_all(self) -> None:
        self.tui.toggle_show_all()

    def action_reload(self) -> None:
        self.tui.reload()

    def action_help(self) -> None:
        self.tui.push_screen(HelpScreen())

    def action_quit(self) -> None:
        self.tui.exit()


class OfflineTui(App[None]):

    CSS_PATH = Path(__file__).resolve().parent.parent / "chrome.tcss"

    def __init__(self, context: OfflineContext, state_dir: Optional[Path]) -> None:
        super().__init__()
        self.set_class(use_ascii(), "ascii")
        theme.set_active(theme.load_palette(theme.DEFAULT_THEME))
        textual = textual_theme(theme.active())
        self.register_theme(textual)
        self.theme = textual.name
        self.context = context
        self.state_dir = state_dir
        self.show_all = False
        self.fit = False
        self.rows: list[OfflineRow] = []

    def get_css_variables(self) -> dict[str, str]:
        return {**super().get_css_variables(), **theme.active().css_variables()}

    def compose(self) -> ComposeResult:
        banner = t("tui.offline.banner").replace("{socket}", self.context.target.socket_path)
        yield Label(banner.replace("{binary}", self.context.target.binary), id="server-down-banner")
        yield OfflineTable(cursor_type="row", zebra_stripes=False, id="offline-board")
        yield Label("", id="sessions-note")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(OfflineTable)
        table.add_columns(
            t("tui.sessions.col.name"), t("tui.sessions.col.project"), t("tui.offline.col.tmux"),
            t("tui.offline.col.state"), t("tui.offline.col.source"),
        )
        self.reload()
        table.focus()

    def say(self, text: str) -> None:
        self.query_one("#sessions-note", Label).update(text)

    def reload(self) -> None:
        try:
            self.rows = list_rows(self.context.target, self.state_dir, self.show_all)
        except OfflineTmuxError as err:
            self.rows = []
            self.render_rows()
            self.say(error_text(err))
            return
        self.render_rows()
        if not self.rows:
            self.say(t("tui.offline.empty") if self.show_all else t("tui.offline.empty_owned"))
        else:
            self.say(t("tui.offline.show_all_on") if self.show_all else t("tui.offline.show_all_off"))

    def render_rows(self) -> None:
        table = self.query_one(OfflineTable)
        cursor = table.cursor_row
        table.clear()
        for row in self.rows:
            name = row.display_name or row.tmux_name
            project = row.project or ("" if row.owned else t("tui.offline.unowned"))
            table.add_row(name, project, row.tmux_name, state_text(row), t("tui.offline.row_source"))
        if self.rows:
            table.move_cursor(row=min(max(cursor, 0), len(self.rows) - 1))

    def selected(self) -> Optional[OfflineRow]:
        cursor = self.query_one(OfflineTable).cursor_row
        return self.rows[cursor] if 0 <= cursor < len(self.rows) else None

    def toggle_fit(self) -> None:
        self.fit = not self.fit
        self.say(t("tui.offline.fit_on") if self.fit else t("tui.offline.fit_off"))

    def toggle_show_all(self) -> None:
        self.show_all = not self.show_all
        self.reload()

    def attach_selected(self, read_only: bool) -> None:
        row = self.selected()
        if row is None:
            return
        if not row.attachable:
            self.notify(t("tui.offline.dead"), severity="warning")
            return
        prefix = self.context.target.prefix()
        try:
            probe_session(prefix, row.tmux_name, clean_env(os.environ))
        except TmuxNotRunning:
            self.notify(t("tui.offline.not_running"), severity="error")
            self.reload()
            return
        except TmuxCommandFailed as err:
            logger.info("tui_offline_attach_probe_failed", detail=err.detail)
            self.notify(t("tui.offline.attach_failed"), severity="error")
            self.reload()
            return
        size = attach.read_pane_size(prefix, row.tmux_name)
        preamble = attach.attach_preamble(size, resize_terminal=not self.fit, read_only=read_only)
        plan = attach.plan_attach(
            row.tmux_name, self.context.target.socket_name, clean_env(os.environ),
            prefix=prefix, read_only=read_only, fit=self.fit, preamble=preamble,
        )
        try:
            if plan.suspend:
                with self.suspend():
                    rc = attach.run(plan)
            else:
                rc = attach.run(plan)
        except SuspendNotSupported:
            self.notify(t("tui.action.no_suspend"))
            return
        if rc != 0:
            self.notify(t("tui.offline.attach_failed"), severity="error")
        self.reload()
