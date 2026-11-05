
from __future__ import annotations

import argparse
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.lib.testsrv_client import access_token, api
from scripts.lib.verify_harness import Report


class Server:

    def __init__(self, base: str, storage_state: str) -> None:
        self.base = base
        self.token = access_token(storage_state, base)

    def call(self, method: str, path: str, body: dict | None = None):
        try:
            return api(self.base, self.token, "/api/v1" + path, body, method, timeout=30)
        except urllib.error.HTTPError as exc:
            return (exc.code, exc.read().decode(errors="replace"))

    def listing(self) -> dict:
        rows = self.call("GET", "/sessions/list")
        return {r["tmux_session"]: r for r in rows if isinstance(r, dict) and r.get("tmux_session")}


@dataclass
class Env:

    args: argparse.Namespace
    page: Any
    report: Report
    server: Server
    tag: str
    repo: Path
    scratch: Path
    existing_dir: Path
    no_swarm_dir: Path
    worktree_root: Path
    layout_row_state: dict[str, str]
    made_blueprints: list[str]
    made_layouts: list[str]
    made_tmux: list[str]
    made_projects: list[str]
