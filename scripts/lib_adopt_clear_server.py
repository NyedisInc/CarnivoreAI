
from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path

SOCKET = "cloude-verify-adopt-clears"
STAMP = "2026-08-24T13:32:31Z"
NAMES = ["cloude_alpha", "cloude_bravo", "cloude_charlie"]
EPOCHS = {name: 1755000000 + i for i, name in enumerate(NAMES)}


class Server:
    """The REAL prompt route and the REAL adoption write, over one db.

    Description: the harness page's window.API calls land here through
      Playwright bindings, so the browser is talking to the same code
      the app runs, not to a canned shape this file invented.
    Inputs (constructor): state_dir (Path) - a throwaway state directory.
    Output: a Server instance.
    """

    def __init__(self, state_dir: Path) -> None:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from src.api import routes
        from src.api import session_crud_routes
        from src.api.auth import require_auth

        self.state_dir = state_dir
        session_crud_routes.settings.__class__.get_state_dir = lambda _self: state_dir

        class _Manager:
            def tmux_socket_name(_self):
                return SOCKET

        app = FastAPI()
        app.include_router(routes.router, prefix="/api/v1")
        app.state.session_manager = _Manager()
        app.dependency_overrides[require_auth] = lambda: True
        self.client = TestClient(app)
        self._adopts = 0
        self._declines = 0

    def seed(self) -> None:
        from src.core.db import connect, db_path_for, set_meta, transaction
        from src.core.db_migration import ensure_db_migrated
        from src.core.db_models import (
            META_SESSION_IMPORT_UNATTRIBUTED,
            SESSION_ORIGIN_OBSERVED,
        )
        from src.core.session_identity import record_instance

        ensure_db_migrated(self.state_dir, 4, "0.8.2")
        with closing(connect(db_path_for(self.state_dir))) as conn:
            with transaction(conn):
                for name in NAMES:
                    record_instance(
                        conn,
                        socket=SOCKET,
                        name=name,
                        epoch=EPOCHS[name],
                        origin=SESSION_ORIGIN_OBSERVED,
                        now=STAMP,
                    )
                set_meta(
                    conn,
                    META_SESSION_IMPORT_UNATTRIBUTED,
                    json.dumps(
                        [
                            {
                                "tmux_name": name,
                                "epoch": EPOCHS[name],
                                "hints": ["its name matches the auto-generated form"],
                                "reason": "no_admissible_evidence",
                            }
                            for name in NAMES
                        ],
                        sort_keys=True,
                    ),
                )

    def counts(self) -> dict:
        return {"adopts": self._adopts, "declines": self._declines}

    def prompt(self) -> dict:
        return self.client.get("/api/v1/sessions/attribution-prompt").json()

    def adopt(self, name: str) -> dict:
        from src.core.db import connect, db_path_for, transaction
        from src.core.session_adopt_persist import persist_adoption
        from src.core.tmux_listing import TmuxListing

        listing = TmuxListing(
            ok=True,
            sessions=[
                {"name": n, "created_at_epoch": EPOCHS[n], "attached": False}
                for n in NAMES
            ],
        )
        with closing(connect(db_path_for(self.state_dir))) as conn:
            with transaction(conn):
                result = persist_adoption(
                    conn, socket=SOCKET, name=name, listing=listing, now=STAMP
                )
        self._adopts += 1
        return {"ok": bool(result.persisted), "outcome": result.outcome}

    def decline(self, names: list) -> dict:
        out = self.client.post(
            "/api/v1/sessions/attribution-decline", json={"tmux_names": list(names)}
        ).json()
        self._declines += len(names)
        return out

    def origins(self) -> dict:
        from src.core.db import connect, db_path_for

        with closing(connect(db_path_for(self.state_dir), create=False)) as conn:
            return {
                str(r[0]): str(r[1])
                for r in conn.execute(
                    "SELECT tmux_name, origin FROM sessions WHERE tmux_socket = ?",
                    (SOCKET,),
                ).fetchall()
            }
