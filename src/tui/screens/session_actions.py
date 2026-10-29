
from __future__ import annotations

from typing import Any, Mapping, Optional

import httpx
from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

from src.tui.strings import t

API = "/api/v1"


def is_live(row: Mapping[str, Any]) -> bool:
    return row.get("activity_status") not in ("dead", "stopped")


def _detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return str(resp.status_code)
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        detail = detail.get("detail") or detail.get("message")
    return str(detail) if detail else str(resp.status_code)


async def mark_read(client: Any, tmux_name: str) -> tuple[bool, str]:
    resp = await client.request("PATCH", f"{API}/sessions/{tmux_name}/unread", json={"unread": False})
    return (True, t("tui.action.marked_read")) if resp.status_code == 200 else (False, _detail(resp))


async def stop(client: Any, session_uuid: str) -> tuple[bool, str]:
    """Stop (sleep) the session: its agent and tmux session end, the row stays asleep; the server's gates may refuse."""
    resp = await client.request("POST", f"{API}/sessions/{session_uuid}/sleep")
    if resp.status_code != 200:
        return False, _detail(resp)
    body = resp.json()
    if body.get("status") == "asleep":
        return True, t("tui.action.stopped")
    return False, str(body.get("detail") or t("tui.action.refused"))


async def restart(client: Any, tmux_name: str, *, live_confirmed: bool) -> tuple[bool, str]:
    resp = await client.request(
        "POST", f"{API}/sessions/respawn", json={"session_name": tmux_name, "confirm_restart_live": live_confirmed}
    )
    if resp.status_code != 200:
        return False, _detail(resp)
    body = resp.json()
    return bool(body.get("ok")), str(body.get("detail") or t("tui.action.restarted"))


async def list_profiles(client: Any) -> list[dict[str, Any]]:
    resp = await client.request("GET", f"{API}/launch-profiles")
    if resp.status_code != 200:
        return []
    return [p for p in resp.json().get("profiles", []) if isinstance(p, dict) and p.get("id")]


async def create(client: Any, working_dir: str, profile_id: Optional[str]) -> tuple[bool, str]:
    body: dict[str, Any] = {"auto_start_claude": True, "working_dir": working_dir}
    if profile_id:
        body["agent_type"] = profile_id
    resp = await client.request("POST", f"{API}/sessions", json=body)
    return (True, t("tui.action.created")) if resp.status_code in (200, 201) else (False, _detail(resp))


class NewSessionModal(ModalScreen[Optional[tuple[str, Optional[str]]]]):

    DEFAULT_CSS = """
    NewSessionModal { align: center middle; }
    NewSessionModal #new-box { width: 60; height: auto; max-height: 80%; border: solid $accent; padding: 0 1; }
    """
    BINDINGS = [("escape", "cancel", "cancel")]

    def __init__(self, profiles: list[dict[str, Any]], folder: str) -> None:
        super().__init__()
        self._profiles = profiles
        self._folder = folder

    def compose(self) -> ComposeResult:
        with Vertical(id="new-box"):
            yield Label(t("tui.new.title"))
            yield Input(self._folder, placeholder=t("tui.new.folder"), id="new-folder")
            yield OptionList(
                *[Option(f"{p.get('label') or p['id']} ({p.get('harness', '')})", id=str(p["id"])) for p in self._profiles],
                id="new-profiles",
            )
            yield Label(t("tui.new.hint"))

    def on_mount(self) -> None:
        options = self.query_one(OptionList)
        for i, p in enumerate(self._profiles):
            if p.get("default"):
                options.highlighted = i
                break
        else:
            options.highlighted = 0 if self._profiles else None
        options.focus()

    @on(OptionList.OptionSelected)
    def _pick(self, event: OptionList.OptionSelected) -> None:
        folder = self.query_one("#new-folder", Input).value.strip()
        if folder:
            self.dismiss((folder, event.option.id))

    @on(Input.Submitted, "#new-folder")
    def _folder_done(self) -> None:
        if self._profiles:
            self.query_one(OptionList).focus()
        else:
            folder = self.query_one("#new-folder", Input).value.strip()
            if folder:
                self.dismiss((folder, None))

    def action_cancel(self) -> None:
        self.dismiss(None)
