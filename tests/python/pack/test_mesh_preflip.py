from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import pytest

from src.api import pack_jobs_precheck_routes as precheck_routes, pack_placement_routes
from src.core.argent import pair_sync
from src.core.argent.pair_credential import CAP_CREDENTIAL, CredentialSender
from src.core.db import connect, db_path_for
from src.core.db_migration import ensure_db_migrated
from src.core.federation import peer_hosts
from src.core.pack.machines import capabilities as caps
from src.core.pack.machines.roster_v2 import RosterComputerV2, RosterV2
from src.core.pack.meshdata import star_era
from src.core.pack.placement import explain, rule
from src.core.pack.relay import member_reach
from src.core.pack.rollup_import import puller, relay_export
from src.core.pack.rollup_import.ddl import COUNTER_TABLE, STATE_TABLE, USAGE_TABLE
from src.core.relay_identity.device_key import DeviceKey, b64url
from src.core.pack.jobs import precheck
from src.core.stats import config as stats_config, rollup
from tests.argent.test_argent_refresh import Rig, rig  # noqa: F401
from tests.python.pack.test_mesh_data_links import CERT
from tests.python.pack.test_rollup_import import _conversation
from tests.python.pack.test_rollup_relay import Node

DAY = 86400
ISSUED = 20 * DAY



def test_the_argent_delegate_label_reads_the_held_list_off_the_event_loop(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    seen: List[threading.Thread] = []

    def held_stub() -> Any:
        seen.append(threading.current_thread())
        return SimpleNamespace(entry=lambda iid: SimpleNamespace(label="member-label"))

    monkeypatch.setattr(member_reach, "held_v2", held_stub)
    sync = SimpleNamespace(_listing=lambda: [])
    sent: List[dict] = []

    async def post(method: str, path: str, body: Any):
        sent.append(body)
        return 200, {}

    sender = CredentialSender(store=rig.store, tokens=rig.tokens, peer=lambda iid: (post, [CAP_CREDENTIAL]), candidates=lambda: ["m1"], allows=lambda iid: True,
                              read_settings=lambda: rig.cfg, approved=lambda iid: True, clock=lambda: rig.now[0], delegates=rig.delegates,
                              label=lambda iid: pair_sync.PairSync._label_of(sync, iid))
    assert asyncio.run(sender.push()) == ["m1"] and len(sent) == 1
    assert len(seen) == 1 and seen[0] is not threading.main_thread()



def _decision() -> rule.Decision:
    return rule.Decision("iid-a", "stats", "stays home", {"kind": "build"})


@pytest.mark.parametrize("on", [True, False])
def test_the_explain_and_precheck_answers_carry_the_mesh_line_only_while_the_switch_is_on(on: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(caps, "MESH_BUILD_ON", on)

    async def place(*_a: Any, **_k: Any) -> rule.Decision:
        return _decision()

    monkeypatch.setattr(explain, "place", place)
    placed = asyncio.run(pack_placement_routes.placement_explain(pack_placement_routes.ExplainBody(), None))
    checked = precheck_routes._answer(precheck.Verdict("block", "busy", "iid-b"))
    for answer in (placed, checked):
        assert ("note" in answer) is on
        if on:
            assert answer["note"] == explain.MESH_NOTE and "not listed here" in answer["note"]
    assert checked["decision"] == "block" and checked["computer"] == "iid-b" and checked["reason"] == "busy"
    if not on:
        assert set(placed) == set(_decision().as_dict()) and set(checked) == {"decision", "computer", "reason"}



def _held(listed: List[str]) -> RosterV2:
    rows = [RosterComputerV2(install_id=i, label=i, fed_public_key=b64url(DeviceKey.from_seed(bytes([n + 1]) * 32).raw_pub), cert=CERT, mesh=True)
            for n, i in enumerate(listed)]
    return RosterV2(generation=1, alpha=listed[0], home=listed[0], issued_at=ISSUED, computers=rows)


def _fixture(tmp: Path) -> sqlite3.Connection:
    state = tmp / "me"
    state.mkdir()
    assert ensure_db_migrated(state).status == "ok"
    conn = connect(db_path_for(state))
    old = ISSUED - 10 * DAY
    for origin, stamp in (("iid-listed", old), ("iid-star", old), ("iid-ssh", old), ("iid-recent", ISSUED - 3600), ("iid-leftover", old)):
        conn.execute(f"INSERT INTO {USAGE_TABLE} (peer_install_id, conversation_id, hour, model, project) VALUES (?, 'c', 1, 'm', 'p')", (origin,))
        conn.execute(f"INSERT INTO {COUNTER_TABLE} (peer_install_id, conversation_id, hour, model, project, counter, key) VALUES (?, 'c', 1, 'm', 'p', 'k', 'x')", (origin,))
        conn.execute(f"INSERT INTO {STATE_TABLE} (peer_install_id, updated_at, pulled_at, origin_pulled_at) VALUES (?, ?, ?, ?)", (origin, stamp, stamp, stamp))
    peer_hosts.upsert(conn, install_id="iid-star", label="star", grant_id="g", fid="f", initiator=False)
    conn.execute("INSERT INTO hosts (key, label, ssh_target, socket, kind, machine_id, created_at, updated_at) VALUES ('ssh-box', 'box', 'box.example', 's', 'ssh', 'iid-ssh', 'x', 'x')")
    conn.commit()
    return conn


def _origins_in_rows(conn: sqlite3.Connection) -> int:
    return conn.execute(f"SELECT COUNT(DISTINCT peer_install_id) FROM {USAGE_TABLE}").fetchone()[0]


def test_the_finder_names_each_origin_kind_and_changes_nothing(tmp_path: Path) -> None:
    with closing(_fixture(tmp_path)) as conn:
        assert _origins_in_rows(conn) == 5
        assert conn.execute("SELECT COUNT(*) FROM hosts WHERE machine_id = 'iid-ssh' AND kind = 'ssh'").fetchone()[0] == 1
        assert peer_hosts.get(conn, "iid-star") is not None and peer_hosts.get(conn, "iid-ssh") is None
        before_changes, before_rows = conn.total_changes, conn.execute(f"SELECT COUNT(*) FROM {USAGE_TABLE}").fetchone()[0]
        found = star_era.find_leftovers(conn, _held(["iid-listed", "iid-other"]))
        assert found.origins == {"listed": ["iid-listed"], "star_peer": ["iid-star"], "hosts_row": ["iid-ssh"], "recent": ["iid-recent"], "leftover": ["iid-leftover"]}
        assert found.counts == {"listed": 1, "star_peer": 1, "hosts_row": 1, "recent": 1, "leftover": 1}
        assert conn.total_changes == before_changes and conn.execute(f"SELECT COUNT(*) FROM {USAGE_TABLE}").fetchone()[0] == before_rows


def test_the_finder_goes_red_when_a_protecting_condition_is_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with closing(_fixture(tmp_path)) as conn:
        held = _held(["iid-listed", "iid-other"])
        assert star_era.find_leftovers(conn, held).counts["leftover"] == 1
        monkeypatch.setattr(star_era, "_hosts_names", lambda _conn: set())
        assert star_era.find_leftovers(conn, held).origins["leftover"] == ["iid-leftover", "iid-ssh"]
        monkeypatch.setattr(star_era, "MARGIN_SECONDS", -10 * DAY)
        assert "iid-recent" in star_era.find_leftovers(conn, held).origins["leftover"]



def test_the_largest_served_page_comes_out_of_the_serve_path_and_fits_the_body_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stats_config, "get_settings", lambda store: {"enabled": True})
    node = Node(tmp_path, "a")
    for i in range(400):
        _conversation(node.stats, f"conv-{i:04d}-" + "x" * 24, f"proj{i % 40:03d}", list(range(24)), seed=i)
    page = relay_export.serve_stream(node, node.open_db, caller="iid-x", stream=None, since_revision=0, max_bytes=rollup.MAX_PAGE_BYTES)
    body = json.dumps(page, separators=(",", ":")).encode()
    assert page["available"] is True and page["complete"] is False and len(page["groups"]) > 1000
    assert 0.95 * rollup.MAX_PAGE_BYTES <= len(body) <= puller.BULK_MAX_BODY
