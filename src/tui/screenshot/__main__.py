
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional, Sequence

import httpx

from src.tui import app as app_module
from src.tui import theme
from src.tui.screens import sessions as sessions_module
from src.tui.app import CarnivoreTui
from src.tui.listing_store import ListingStore

REPO = Path(__file__).resolve().parents[3]
DEFAULT_OUT = REPO / "client" / "img" / "tui" / "tui-sessions.svg"
SIZE = (100, 13)


def row(name: str, status: str, project: str, family: str = "claude", unread: bool = False) -> dict[str, Any]:
    return {"session": {"id": name, "name": name}, "session_uuid": f"u-{name}", "label": name,
            "activity_status": status, "project_name": project, "agent_family": family, "unread": unread}


ROWS = [
    row("docs-pass", "working", "website"),
    row("api-review", "question", "billing", unread=True),
    row("fix-flaky-test", "finished_unread", "billing", unread=True),
    row("release-notes", "idle", "website"),
    row("data-import", "working", "ingest", family="codex"),
    row("scratch", "idle", "sandbox"),
]


class ShotApp(CarnivoreTui):

    def __init__(self) -> None:
        snap = {"stream": "s", "seq": 1, "collections": {"list": {"rows": ROWS, "ok": True}}}

        async def fetch() -> dict[str, Any]:
            return snap

        async def stop() -> None:
            return None

        async def check_session() -> bool:
            await events.listing.resync()
            return True

        events = SimpleNamespace(listing=ListingStore(fetch), down=False, on_topics=lambda fn: (lambda: None),
                                 topic_pushed=lambda topic: False, start=lambda: None, stop=stop)

        async def request(method: str, path: str, **kw: Any) -> httpx.Response:
            if path == "/api/v1/approvals":
                return httpx.Response(200, json={"items": []})
            return httpx.Response(200, json={"values": {}})

        super().__init__(SimpleNamespace(base_url="http://127.0.0.1", request=request, aclose=stop, check_session=check_session), events)  # type: ignore[arg-type]


def strip_remote(svg: str) -> str:
    svg = re.sub(r"@font-face\s*\{[^}]*\}", "", svg)
    svg = re.sub(r"@import[^;]*;", "", svg)
    svg = re.sub(r"https?://[^\s\"')<>]+", "", svg)
    return svg.replace('xmlns=""', 'xmlns="http://www.w3.org/2000/svg"', 1)


async def render(out: Path) -> None:
    theme.set_active(theme.load_palette(theme.DEFAULT_THEME))
    for module in (app_module, sessions_module):
        module.use_ascii = lambda: False
    app = ShotApp()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.pause()
        svg = strip_remote(app.export_screenshot(title="carnivore tui"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    out = Path(args[0]) if args else DEFAULT_OUT
    asyncio.run(render(out))
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
