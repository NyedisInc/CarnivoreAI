
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.markup import escape
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from src.tui import keys
from src.tui.strings import t

SCOPE_ORDER = (keys.APP, keys.SESSIONS, keys.APPROVALS, keys.LEDGER, keys.CATALOG, keys.OFFLINE, keys.HELP)


def help_lines() -> list[str]:
    rows = keys.help_rows()
    lines: list[str] = []
    for scope in SCOPE_ORDER:
        mine = [(label, desc) for label, desc, row_scope, _live in rows if row_scope == scope]
        if not mine:
            continue
        lines.append(f"[b $accent]{escape(t('tui.help.scope.' + scope)).upper()}[/]")
        lines.extend(f"  [b]{escape(label):<10}[/] {escape(desc)}" for label, desc in mine)
        lines.append("")
    return lines


class HelpScreen(ModalScreen[None]):

    DEFAULT_CSS = """
    HelpScreen { align: center middle; }
    HelpScreen #help-box { width: 60; height: auto; max-height: 90%; border: solid $accent; padding: 0 1; }
    """
    BINDINGS = keys.textual_bindings(keys.HELP)

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-box"):
            yield Label(t("tui.help.title").upper(), id="help-title")
            yield Static("\n".join(help_lines()), id="help-body")

    def action_close(self) -> None:
        self.dismiss(None)
