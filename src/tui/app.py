
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.theme import Theme
from textual.widgets import ContentSwitcher, DataTable, Footer, Input, Label

from src.tui import keys, theme
from src.tui.api_client import ApiClient, AuthRequired, LoginError, ServerUnavailable
from src.tui.events_client import EventsClient
from src.tui.led import use_ascii
from src.tui.listing_store import LIVENESS
from src.tui.safe_errors import crash_summary
from src.tui.screens.approvals import ApprovalsPane
from src.tui.screens.catalog import CatalogPane
from src.tui.screens.help import HelpScreen
from src.tui.screens.ledger import LedgerPane
from src.tui.screens.sessions import SessionsPane
from src.tui.strings import t


class LoginScreen(Screen[None]):

    def __init__(self, notice: Optional[str] = None) -> None:
        super().__init__()
        self._notice = notice or ""

    def compose(self) -> ComposeResult:
        with Vertical(id="login"):
            yield Label(t("auth.totp_prompt.heading"), id="login-heading")
            yield Label(t("auth.totp_prompt.description"))
            yield Label(self._notice, id="login-notice")
            yield Input(
                placeholder=t("auth.totp_prompt.label"),
                password=True,
                max_length=6,
                id="login-code",
            )
            yield Label("", id="login-status")
        yield Footer()

    def on_mount(self) -> None:
        self.call_after_refresh(self._focus_code)

    def _focus_code(self) -> None:
        for field in self.query("#login-code").results(Input):
            field.focus()

    def _say(self, text: str) -> None:
        self.query_one("#login-status", Label).update(text)

    @on(Input.Submitted, "#login-code")
    async def _submit(self, event: Input.Submitted) -> None:
        code = event.value.strip()
        if len(code) != 6:
            self._say(t("auth.totp_prompt.error_length"))
            return
        if not code.isdigit():
            self._say(t("auth.totp_prompt.error_digits"))
            return
        self._say(t("auth.totp_prompt.verifying"))
        event.input.value = ""
        app = self.app
        assert isinstance(app, CarnivoreTui)
        try:
            await app.client.login(code)
        except LoginError as err:
            self._say(
                {
                    "rate_limited": t("tui.login.rate_limited"),
                    "unavailable": t("tui.login.unavailable"),
                    "busy": t("tui.login.busy"),
                }.get(err.reason, t("auth.totp_prompt.error_failed"))
            )
            return
        app.show_main()


PREFERENCES_PATH = "/api/v1/preferences"


def textual_theme(palette: theme.Palette) -> Theme:
    r, g, b = (int(palette.background[i:i + 2], 16) for i in (1, 3, 5))
    return Theme(
        name=f"carnivore-{palette.theme_id}", primary=palette.accent, secondary=palette.accent,
        accent=palette.accent, foreground=palette.foreground, background=palette.background,
        surface=palette.background, panel=palette.titlerow, error=palette.coral,
        warning=palette.hue("yellow"), success=palette.hue("green"), dark=(r + g + b) / 3 < 128,
    )


PANES = (
    ("sessions", "tui.screen.sessions", SessionsPane),
    ("approvals", "tui.screen.approvals", ApprovalsPane),
    ("ledger", "tui.screen.ledger", LedgerPane),
    ("catalog", "tui.screen.catalog", CatalogPane),
)


class MainScreen(Screen[None]):

    BINDINGS = keys.textual_bindings(keys.APP)

    def compose(self) -> ComposeResult:
        yield Label(t("tui.banner.server_down"), id="server-down-banner")
        yield Label("", id="tabs")
        with ContentSwitcher(initial="pane-sessions", id="panes"):
            for _name, _title, pane in PANES:
                yield pane()
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#server-down-banner", Label).display = False
        self.action_show_screen("sessions")

    def action_show_screen(self, name: str) -> None:
        self.query_one(ContentSwitcher).current = f"pane-{name}"
        self.query_one("#tabs", Label).update(
            "  ".join(
                f"[b $accent]{i} {t(title)}[/]" if n == name else f"{i} {t(title)}"
                for i, (n, title, _pane) in enumerate(PANES, 1)
            )
        )
        for table in self.query_one(f"#pane-{name}").query(DataTable):
            table.focus()

    def action_help(self) -> None:
        self.app.push_screen(HelpScreen())

    def action_quit(self) -> None:
        self.app.exit()


class CarnivoreTui(App[None]):

    BINDINGS = [Binding("ctrl+q", "quit", t("tui.quit.hint"))]
    CSS_PATH = Path(__file__).with_name("chrome.tcss")

    def __init__(self, client: ApiClient, events: Optional[EventsClient] = None) -> None:
        super().__init__()
        self.set_class(use_ascii(), "ascii")
        self.apply_palette(theme.load_palette(theme.DEFAULT_THEME))
        self.client = client
        self.events = events or EventsClient(client, client.base_url, self._set_banner, self._auth_lost)

    def get_css_variables(self) -> dict[str, str]:
        return {**super().get_css_variables(), **theme.active().css_variables()}

    def apply_palette(self, palette: theme.Palette) -> None:
        theme.set_active(palette)
        textual = textual_theme(palette)
        self.register_theme(textual)
        self.theme = textual.name
        self.refresh_css()

    async def load_theme(self) -> None:
        try:
            resp = await self.client.request("GET", PREFERENCES_PATH)
        except AuthRequired:
            self.show_login()
            return
        except ServerUnavailable:
            return
        values: Any = resp.json().get("values") if resp.status_code == 200 else None
        theme_id = values.get("theme") if isinstance(values, dict) else None
        if isinstance(theme_id, str) and theme_id and theme_id != theme.active().theme_id:
            self.apply_palette(theme.load_palette(theme_id))
            for pane in self.screen.query(SessionsPane):
                pane.render_rows()

    async def on_mount(self) -> None:
        try:
            ok = await self.client.check_session()
        except ServerUnavailable:
            self.push_screen(LoginScreen(t("tui.login.unavailable")))
            return
        if ok:
            self.show_main()
        else:
            self.push_screen(LoginScreen())

    def show_main(self) -> None:
        self.switch_screen(MainScreen()) if len(self.screen_stack) > 1 else self.push_screen(MainScreen())
        self.events.start()
        self.events.on_topics(lambda topics: LIVENESS in topics and self.run_worker(self.load_theme(), group="theme"))
        self.run_worker(self.load_theme(), exclusive=True, group="theme")

    def _set_banner(self, down: bool) -> None:
        for banner in self.screen.query("#server-down-banner"):
            banner.display = down

    def _handle_exception(self, error: Exception) -> None:
        if isinstance(getattr(error, "error", None), AuthRequired) or isinstance(error, AuthRequired):
            self.show_login()
            return
        super()._handle_exception(error)

    def _fatal_error(self) -> None:
        from rich.text import Text

        exc = sys.exc_info()[1]
        self.bell()
        self._exit_renderables.append(Text(crash_summary(exc) if exc else "carnivore tui crashed"))
        self._close_messages_no_wait()

    def _auth_lost(self) -> None:
        self.show_login()

    def show_login(self) -> None:
        self.switch_screen(LoginScreen(t("tui.login.expired")))

    async def on_unmount(self) -> None:
        await self.events.stop()
        await self.client.aclose()
