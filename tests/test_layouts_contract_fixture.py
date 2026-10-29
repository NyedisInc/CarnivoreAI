
from __future__ import annotations

import json
import os
import random
import re
from pathlib import Path
from typing import Any, Dict, List

from contextlib import closing

from tests.layouts_helpers import add_sessions, client_for, grid, row

# ruff: noqa: E402
from src.core.db import connect
from src.core.layouts.ddl import REVERSAL_SQL_V34

FIXTURE = Path(__file__).parent / "fixtures" / "layouts_api.json"
API = "/api/v1/layouts"
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def _normalise(value: Any, uuids: Dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {k: _normalise(v, uuids) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalise(v, uuids) for v in value]
    if isinstance(value, str):
        if STAMP.match(value):
            return "<timestamp>"
        for real, name in uuids.items():
            value = value.replace(real, name)
    return value


def _examples(client, db_path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    uuids: Dict[str, str] = {}

    def call(title: str, method: str, path: str, body: Any = None) -> Dict[str, Any]:
        res = client.request(method, path, json=body)
        data = res.json()
        layout = data.get("layout") if isinstance(data, dict) else None
        if isinstance(layout, dict) and layout["layout_uuid"] not in uuids:
            uuids[layout["layout_uuid"]] = f"<layout_uuid_{len(uuids) + 1}>"
        out.append({
            "title": title, "method": method, "path": _normalise(path, uuids),
            "request": _normalise(body, uuids), "status": res.status_code,
            "response": _normalise(data, uuids),
        })
        return data

    pair = grid(row(1), row(2))
    call("list, empty install", "GET", API)
    first = call("create", "POST", API, {"name": "api + web", "shape": pair})["layout"]["layout_uuid"]
    call("create with a source_key (the one-time migration's)",
         "POST", API, {"name": "migrated", "shape": pair, "source_key": "terminal_layouts:cloude_a@1"})
    call("create, idempotent repeat", "POST", API,
         {"name": "migrated", "shape": pair, "source_key": "terminal_layouts:cloude_a@1"})
    call("create, 409 name taken (case folded)", "POST", API, {"name": "API + WEB", "shape": pair})
    call("create, 409 member unresolved", "POST", API, {"name": "ghost", "shape": grid(row(1), row(99))})
    call("create, 400 too few members", "POST", API, {"name": "solo", "shape": grid(row(1))})
    call("create, 400 name invalid", "POST", API, {"name": "   ", "shape": pair})
    call("create, 400 primary sentinel in a layout", "POST", API,
         {"name": "p", "shape": grid("terminal:@primary", row(2))})
    call("rename", "PATCH", f"{API}/{first}", {"name": "api + web + db"})
    call("set style (issue #821)", "PUT", f"{API}/{first}/style",
         {"colour": "teal", "gradient": "tide", "animation": "shimmer"})
    call("set style, 400 invalid colour", "PUT", f"{API}/{first}/style", {"colour": "not-a-colour"})
    call("set style, 404 unknown layout", "PUT",
         f"{API}/00000000-0000-0000-0000-000000000000/style", {"colour": "teal"})
    call("broadcast toggle off (issue #837; revision unchanged)", "PUT",
         f"{API}/{first}/members/u1-0000/broadcast", {"enabled": False})
    call("broadcast toggle, 409 not a member", "PUT",
         f"{API}/{first}/members/u3-0000/broadcast", {"enabled": False})
    call("broadcast: one result per member (row 1 live, row 2 toggled off)", "POST",
         f"{API}/{first}/broadcast", {"text": "git status"})
    call("broadcast, 400 a newline is a second command", "POST",
         f"{API}/{first}/broadcast", {"text": "ls\nrm -rf build"})
    call("replace shape (tabs inside a component)", "PUT", f"{API}/{first}/shape", {
        "shape": grid(row(1), row(2), groups={row(1): [row(1), row(3)]}), "expected_revision": 1})
    call("replace shape, 409 stale carries current", "PUT", f"{API}/{first}/shape",
         {"shape": pair, "expected_revision": 1})
    call("add member by session_uuid", "POST", f"{API}/{first}/members", {"session_uuid": "u3-0000"})
    call("remove member", "DELETE", f"{API}/{first}/members/u3-0000")
    call("remove member", "DELETE", f"{API}/{first}/members/u2-0000")
    call("remove member to one: deleted with survivor", "DELETE", f"{API}/{first}/members/u1-0000")
    call("list", "GET", API)
    second = [k for k, v in uuids.items() if v == "<layout_uuid_2>"][0]
    call("reorder", "PUT", f"{API}/order", {"layout_uuids": [second]})
    call("renew active lease", "PUT", f"{API}/{second}/active")
    call("renew lease, 404 unknown layout", "PUT", f"{API}/00000000-0000-0000-0000-000000000000/active")
    call("delete (sessions untouched)", "DELETE", f"{API}/{second}")
    call("delete, 404", "DELETE", f"{API}/{second}")
    with closing(connect(db_path, create=False)) as conn:
        for statement in REVERSAL_SQL_V34:
            conn.execute(statement)
    call("list, tables unreadable: 200 unavailable, never an empty ok", "GET", API)
    call("create, 503 datastore unavailable", "POST", API, {"name": "x", "shape": pair})
    return out


def _live_row_one(client) -> None:
    from types import SimpleNamespace

    class Pane:
        def is_alive(self) -> bool:
            return True

        async def paste_and_submit(self, text: str) -> None:
            return None

    info = SimpleNamespace(session_row_id=1, session=SimpleNamespace(id="ses_1"),
                           activity_status="idle", startup_gate="ready")

    async def list_session_infos():
        return [info]

    client.app.state.session_manager = SimpleNamespace(list_session_infos=list_session_infos)
    client.app.state.services = SimpleNamespace(
        registry=SimpleNamespace(get_backend=lambda sid: Pane() if sid == "ses_1" else None))


def test_the_fixture_matches_the_live_routes(tmp_path, monkeypatch):
    client, db_path, _ = client_for(tmp_path, monkeypatch)
    sessions = add_sessions(db_path, 4)
    _live_row_one(client)
    assert [r for r, _ in sessions] == [1, 2, 3, 4]
    random.seed(20260926)
    examples = _examples(client, db_path)
    document = {
        "description": (
            "Request and response examples for every /api/v1/layouts route (issue #424, "
            "slice A #745; the broadcast toggle and broadcast, issue #837). Sessions rows 1-4 carry session_uuid u0-0000..u3-0000; "
            "<layout_uuid_N> and <timestamp> stand for generated values. Regenerated and "
            "checked by tests/test_layouts_contract_fixture.py. Model: docs/layouts.md."),
        "examples": examples,
    }
    if os.environ.get("LAYOUTS_FIXTURE_WRITE") == "1":
        FIXTURE.parent.mkdir(exist_ok=True)
        FIXTURE.write_text(json.dumps(document, indent=2) + "\n")
    stored = json.loads(FIXTURE.read_text())
    assert len(stored["examples"]) == len(examples) >= 20
    for want, got in zip(stored["examples"], examples):
        assert got == want, want["title"]
    assert {e["status"] for e in examples} >= {200, 400, 404, 409, 503}
