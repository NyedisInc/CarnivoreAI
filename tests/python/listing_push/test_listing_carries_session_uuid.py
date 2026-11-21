from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from src.core import session_store
from tests.test_listing_off_the_loop import _manager_with, _status_rows

SRC = Path(__file__).resolve().parents[3] / "src"
INLINE = re.compile(r"SELECT[ \t]+session_uuid[ \t]+FROM[ \t]+sessions[ \t]+WHERE[ \t]+id[ \t]*=[ \t]*\?", re.IGNORECASE)
OWNER = SRC / "core" / "session_store.py"


KNOWN_SWARM = {
    "core/swarm/alerts.py": 1, "core/swarm/teardown.py": 1, "core/swarm/facade.py": 1,
    "core/swarm/stream_sources.py": 1, "core/swarm/body.py": 1, "core/swarm/say.py": 1,
    "core/swarm/project_agent.py": 1, "core/swarm/membership.py": 1, "core/swarm/body_create.py": 1,
}


def inline_counts(root: Path, owner: Path) -> dict[str, int]:
    return {
        str(p.relative_to(root)): n for p in sorted(root.rglob("*.py"))
        if p != owner and (n := len(INLINE.findall(p.read_text("utf-8"))))
    }


def swarm_drift(found: dict[str, int], known: dict[str, int]) -> list[str]:
    out = [f"{f}: {n} > known {known.get(f, 0)}" for f, n in found.items() if n > known.get(f, 0)]
    return out + [f"{f}: stale known entry (now {found.get(f, 0)})" for f, k in known.items() if found.get(f, 0) < k]


def test_the_scan_can_go_red(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text('c.execute("SELECT session_uuid FROM sessions WHERE id=?", (1,))')
    (tmp_path / "b.py").write_text('c.execute("SELECT session_uuid FROM sessions WHERE id = ?", (1,))')
    (tmp_path / "own.py").write_text('c.execute("SELECT session_uuid FROM sessions WHERE id = ?", (1,))')
    found = inline_counts(tmp_path, tmp_path / "own.py")
    assert found == {"a.py": 1, "b.py": 1}
    assert swarm_drift(found, {"a.py": 1}) == ["b.py: 1 > known 0"]
    assert swarm_drift(found, {"a.py": 1, "b.py": 1, "c.py": 1}) == ["c.py: stale known entry (now 0)"]
    assert swarm_drift(found, {"a.py": 2, "b.py": 1}) == ["a.py: stale known entry (now 1)"]


def test_no_inline_session_uuid_lookup_outside_session_store() -> None:
    assert swarm_drift(inline_counts(SRC, OWNER), KNOWN_SWARM) == []


def test_uuid_for_row_reads_one_row() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, session_uuid TEXT)")
    conn.executemany("INSERT INTO sessions VALUES (?, ?)", [(1, "u-1"), (2, None)])
    assert session_store.uuid_for_row(conn, 1) == "u-1"
    assert session_store.uuid_for_row(conn, 2) is None
    assert session_store.uuid_for_row(conn, 99) is None
    assert session_store.uuid_for_row(conn, None) is None


def test_the_local_listing_wrapper_carries_the_row_uuid(monkeypatch) -> None:
    name = "cloude_a"
    manager = _manager_with([("ses_a", name)])
    monkeypatch.setattr(manager, "_build_tmux_status_map", lambda: _status_rows([name]))
    monkeypatch.setattr(manager, "_instance_index_for_listing", lambda **_kw: None)
    monkeypatch.setattr(manager, "_label_for_tmux_name", lambda _n: "work")
    identity = {"id": 7, "parent_session_id": None, "agent_type": None, "agent_family_source": None,
                "session_uuid": "11111111-2222-3333-4444-555555555555"}
    monkeypatch.setattr(manager, "_identity_for_live_name", lambda _n: identity)
    info = manager._session_info_for("ses_a", status_map=manager._build_tmux_status_map(), instance_index=None, prefetch=None)
    assert info is not None and info.session_row_id == 7
    assert info.session_uuid == "11111111-2222-3333-4444-555555555555"
    assert not hasattr(info.session, "session_uuid")
