
from __future__ import annotations

from dataclasses import dataclass

from textual.binding import Binding

from src.tui.strings import t

APP = "app"
SESSIONS = "sessions"
APPROVALS = "approvals"
LEDGER = "ledger"
CATALOG = "catalog"
HELP = "help"
OFFLINE = "offline"


@dataclass(frozen=True)
class Key:

    label: str
    keys: tuple[str, ...]
    action: str
    desc: str
    scope: str
    live: bool = True
    show: bool = False


KEYS: tuple[Key, ...] = (
    Key("1", ("1",), "show_screen('sessions')", "tui.key.screen_sessions", APP, show=True),
    Key("2", ("2",), "show_screen('approvals')", "tui.key.screen_approvals", APP, show=True),
    Key("3", ("3",), "show_screen('ledger')", "tui.key.screen_ledger", APP, show=True),
    Key("4", ("4",), "show_screen('catalog')", "tui.key.screen_catalog", APP, show=True),
    Key("?", ("question_mark",), "help", "tui.key.help", APP, show=True),
    Key("q", ("q",), "quit", "tui.key.quit", APP),
    Key("enter", ("enter",), "attach", "tui.key.attach", SESSIONS, show=True),
    Key("w", ("w",), "watch", "tui.key.watch", SESSIONS, show=True),
    Key("n", ("n",), "new", "tui.key.new", SESSIONS),
    Key("s", ("s",), "stop", "tui.key.stop", SESSIONS),
    Key("R", ("R",), "restart", "tui.key.restart", SESSIONS),
    Key("A", ("A",), "arm", "tui.key.arm", SESSIONS),
    Key("u", ("u",), "mark_read", "tui.key.mark_read", SESSIONS),
    Key("/", ("slash",), "filter", "tui.key.filter", SESSIONS, show=True),
    Key("j/down", ("j", "down"), "cursor_down", "tui.key.down", SESSIONS),
    Key("k/up", ("k", "up"), "cursor_up", "tui.key.up", SESSIONS),
    Key("g", ("g",), "top", "tui.key.top", SESSIONS),
    Key("G", ("G",), "bottom", "tui.key.bottom", SESSIONS),
    Key("o", ("o",), "sort", "tui.key.sort", SESSIONS, show=True),
    Key("j/down", ("j", "down"), "cursor_down", "tui.key.down", LEDGER),
    Key("k/up", ("k", "up"), "cursor_up", "tui.key.up", LEDGER),
    Key("g", ("g",), "top", "tui.key.top", LEDGER),
    Key("G", ("G",), "bottom", "tui.key.bottom", LEDGER),
    Key("/", ("slash",), "filter", "tui.key.filter", CATALOG, show=True),
    Key("j/down", ("j", "down"), "cursor_down", "tui.key.down", CATALOG),
    Key("k/up", ("k", "up"), "cursor_up", "tui.key.up", CATALOG),
    Key("g", ("g",), "top", "tui.key.top", CATALOG),
    Key("G", ("G",), "bottom", "tui.key.bottom", CATALOG),
    Key("a", ("a",), "approve", "tui.key.approve", APPROVALS, show=True),
    Key("d", ("d",), "deny", "tui.key.deny", APPROVALS, show=True),
    Key("esc/?", ("escape", "question_mark"), "close", "tui.key.close", HELP),
    Key("enter/t", ("enter", "t"), "type", "tui.key.type", OFFLINE, show=True),
    Key("w", ("w",), "watch", "tui.key.watch", OFFLINE, show=True),
    Key("f", ("f",), "fit", "tui.key.fit", OFFLINE, show=True),
    Key("a", ("a",), "show_all", "tui.key.show_all", OFFLINE, show=True),
    Key("r", ("r",), "reload", "tui.key.reload", OFFLINE),
    Key("j/down", ("j", "down"), "cursor_down", "tui.key.down", OFFLINE),
    Key("k/up", ("k", "up"), "cursor_up", "tui.key.up", OFFLINE),
    Key("?", ("question_mark",), "help", "tui.key.help", OFFLINE, show=True),
    Key("q", ("q",), "quit", "tui.key.quit", OFFLINE, show=True),
)


def textual_bindings(scope: str) -> list[Binding]:
    return [
        Binding(key, key_i.action, t(key_i.desc), show=key_i.show and i == 0)
        for key_i in KEYS
        if key_i.scope == scope
        for i, key in enumerate(key_i.keys)
    ]


def help_rows() -> list[tuple[str, str, str, bool]]:
    return [(k.label, t(k.desc), k.scope, k.live) for k in KEYS]
