
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, Tuple

from src.core.db import connect, db_path_for
from tests.python.inventory import schemas
from tests.python.session_purge.purge_world import add_session, insert

A, B, P = "A", "B", "P"
CONV_A, CONV_A0, CONV_B, CONV_D = ("aaaaaaaa-0000-0000-0000-00000000000a", "aaaaaaaa-0000-0000-0000-0000000000a0",
                                   "bbbbbbbb-0000-0000-0000-00000000000b", "dddddddd-0000-0000-0000-00000000000d")
UUID_A, UUID_B, UUID_D = "sess-uuid-A-0001", "sess-uuid-B-0002", "sess-uuid-D-0003"
APP_A, APP_B, APP_D = "ses_aaaa0001", "ses_bbbb0002", "ses_dddd0003"
TMUX_A, TMUX_B, TMUX_D = "carnivore_A", "carnivore_B", "carnivore_D"
EPOCH_A = 1700000001
NOW = "2026-10-16T00:00:00Z"


class Ledger:

    def __init__(self) -> None:
        self.rows: Counter = Counter()
        self.files: Counter = Counter()
        self.entries: Counter = Counter()

    def note(self, tags: Iterable[str], store: str, table: str, kind: Counter) -> None:
        for tag in tags:
            kind[(tag, store, table)] += 1


class Seeder:

    def __init__(self, ledger: Ledger, store: str, path: Path) -> None:
        self.ledger, self.store, self.path = ledger, store, path

    def put(self, table: str, tags: Tuple[str, ...] = (), **values: Any) -> int:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.row_factory = sqlite3.Row
            rowid = insert(conn, table, **values)
            conn.commit()
        self.ledger.note(tags, self.store, table, self.ledger.rows)
        return rowid

    def sql(self, statement: str, *params: Any) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(statement, params)
            conn.commit()


def build_state(tmp_path: Path) -> SimpleNamespace:
    state = tmp_path / "state"
    state.mkdir()
    main = schemas.build_main(state)
    side = schemas.build_side(state)
    return SimpleNamespace(state=state, main=main, side=side, ledger=Ledger(), config=tmp_path / "config.json",
                           home=tmp_path / "claude", codex=tmp_path / "codex", tmp=tmp_path,
                           root1=str((tmp_path / "proj1").resolve()), root2=str((tmp_path / "proj2").resolve()))


def seed_sessions(w: SimpleNamespace) -> None:
    with closing(connect(db_path_for(w.state))) as conn:
        company = insert(conn, "companies", name="Acme", uid="company-uid-1", created_at=NOW, updated_at=NOW)
        w.p1 = insert(conn, "projects", root=w.root1, raw_path=w.root1, display_name="Proj One", uid="project-uid-1",
                      company_id=company, source="manual", created_at=NOW, updated_at=NOW)
        w.p2 = insert(conn, "projects", root=w.root2, raw_path=w.root2, display_name="Proj Two", uid="project-uid-2",
                      source="manual", created_at=NOW, updated_at=NOW)
        w.company = company
        w.row_a = add_session(conn, UUID_A, TMUX_A, CONV_A, epoch=EPOCH_A, title="session A")
        w.row_b = add_session(conn, UUID_B, TMUX_B, CONV_B, epoch=1700000002, title="session B", parent=w.row_a)
        w.row_d = add_session(conn, UUID_D, TMUX_D, CONV_D, epoch=1700000003, title="session D")
        for row, project, app, root in ((w.row_a, w.p1, APP_A, w.root1), (w.row_b, w.p1, APP_B, w.root1), (w.row_d, w.p2, APP_D, w.root2)):
            conn.execute("UPDATE sessions SET project_id = ?, legacy_session_id = ?, working_dir = ? WHERE id = ?",
                         (project, app, root, row))
        conn.commit()
    w.main_seed = Seeder(w.ledger, "cloude.db", w.main)
    w.ledger.note((A,), "cloude.db", "sessions", w.ledger.rows)
    w.ledger.note((B,), "cloude.db", "sessions", w.ledger.rows)
    w.ledger.note((P,), "cloude.db", "projects", w.ledger.rows)
    w.ledger.note((P,), "cloude.db", "companies", w.ledger.rows)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def write_text(path: Path, text: str = "{}\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def seeded_ids(w: SimpleNamespace) -> Dict[str, Any]:
    return {"row_a": w.row_a, "row_b": w.row_b, "p1": w.p1}
