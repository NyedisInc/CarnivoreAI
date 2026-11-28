
from __future__ import annotations

import asyncio
import importlib
import json
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pytest

from tests.lifecycle_helpers import add_row  # noqa: F401

# ruff: noqa: E402
from src.api import machine_stats_routes, provider_ledger_routes
from src.core import item_settings_store, session_group_store
from src.core.computers import direction
from src.core.deepsearch import peer_air_gap
from src.core.federation import peer_forward, peer_hosts, peer_listing, peer_serve
from src.core.federation.peer_link import CONNECTED
from src.core.item_settings_ddl import ITEM_SETTINGS_TABLE
from src.core.layouts import store as layouts_store
from src.core.mcp_usage import report as mcp_report
from src.core.pack.machines import restrictions, roster as roster_mod, settings_doc
from src.core.pack.meshdata import panel_kind, workspace_kind
from src.core.pack.relay import ledger_sync_store
from src.core.pack.rollup_import import v2_export, v2_store
from src.core.pack.rollup_import.ddl import ACTIVITY_TABLE, CONVERSATIONS_TABLE, PROJECTS_TABLE, USAGE_5M_TABLE, USAGE_TABLE
from src.core.provider_ledger import relay_accounts
from src.core.session_group_membership import assign_layout
from src.core.session_usage import rollup as session_usage_rollup
from src.core.stats import config as stats_config, events as stats_events, insights, live_view, queries, rollup, tripwires as stats_tripwires
from src.core.stats.plugin.extract import project_key
from src.core.stats_feed import model as feed_model, peers as feed_peers
from src.models.provider_ledger import AccountUsage, LedgerSnapshot, LedgerTotal, LoopStatus, UsageWindow
from src.models.stats import AnnotationWrite, ChartWrite, StatsFilters, TripwireWrite
from tests.python.pack._pack_parity_e2e_harness import (
    IID_ALPHA,
    IID_MEMBER_B,
    IID_MEMBER_C,
    PackParityMesh,
    PackParityNode,
    StarSessionLinks,
    build_large_home_layout,
    build_query,
    clear_stats_caches,
    install_mesh_monkeypatches,
    row_look_id,
    snapshot_agent_bar,
    sync_direct_sessions_as_shadows,
    u36,
    uid,
)


@pytest.fixture()
def e2e_mesh(tmp_path: Path, monkeypatch: Any) -> Any:
    peer_listing.reset()
    clear_stats_caches()
    with direction._TOWARD_LOCK:
        direction._ONE_WAY_TOWARD.clear()
    active_box, notified_topics, contained_ids = install_mesh_monkeypatches(monkeypatch)

    def factory(
        names: Tuple[str, ...] = ("a", "b", "c"), *, no_logins: Optional[Set[str]] = None,
        one_way: Optional[Set[str]] = None, now_s: Optional[float] = None,
    ) -> Tuple[PackParityMesh, List[str], Set[str]]:
        mesh = PackParityMesh(tmp_path, names, no_logins=no_logins, one_way=one_way, now_s=now_s)
        active_box["mesh"] = mesh
        return mesh, notified_topics, contained_ids

    yield factory
    peer_listing.reset()
    clear_stats_caches()
    with direction._TOWARD_LOCK:
        direction._ONE_WAY_TOWARD.clear()


def _import_p5_telemetry() -> Tuple[Any, Any]:
    try:
        return (
            importlib.import_module("src.core.pack.meshdata.telemetry_kind"),
            importlib.import_module("src.core.pack.globalsync.mesh_telemetry"),
        )
    except ModuleNotFoundError:
        pytest.skip("Slice P5 Track A (telemetry_kind / mesh_telemetry) not yet landed in this worktree")




def test_e2e_p1_p2_agent_bar_3node_star_mesh_parity(e2e_mesh: Any) -> None:
    default_rest = restrictions.Restrictions()
    assert default_rest.may_receive_pack_ui is True and default_rest.may_receive_global_setup is False

    m, _topics, _contained = e2e_mesh(("a", "b", "c"), no_logins={"b", "c"})
    m.pair_star()
    a, b, c = m["a"], m["b"], m["c"]
    assert b.restrictions.may_receive_pack_ui is True and b.restrictions.may_receive_global_setup is False
    assert c.restrictions.may_receive_pack_ui is True and c.restrictions.may_receive_global_setup is False

    with closing(b.open_db()) as conn:
        assert peer_hosts.get(conn, c.iid, include_mesh=True) is None
    with closing(c.open_db()) as conn:
        assert peer_hosts.get(conn, b.iid, include_mesh=True) is None

    m.step_all()
    m.now_ms += 1000

    with closing(b.open_db()) as conn:
        add_row(conn, uuid=u36(901), name="b_offset_1", epoch=1)
        conn.commit()
    with closing(c.open_db()) as conn:
        add_row(conn, uuid=u36(902), name="c_offset_1", epoch=1)
        add_row(conn, uuid=u36(903), name="c_offset_2", epoch=1)
        conn.commit()

    co_acme, co_temp, co_beta = uid(101), uid(102), uid(103)
    p_alpha_parent, p_alpha_child, p_b_arch, p_b_sleep, p_c_zero = uid(201), uid(202), uid(203), uid(204), uid(205)
    s_a1, s_a2, s_b_live, s_b_sleep, s_c_live = u36(1), u36(2), u36(3), u36(4), u36(5)
    ly1, ly2 = u36(51), u36(52)
    g_co, g_proj, g_sub = u36(61), u36(62), u36(63)
    rl1, rl2 = row_look_id(1), row_look_id(2)

    a_cid_acme = a.add_company("Acme Corp", co_acme, hue=210)
    a.add_company("TempCo", co_temp, hue=30)
    a_pid_parent = a.add_project("AlphaWeb", p_alpha_parent, root="/work/a/alphaweb", company_id=a_cid_acme, color="#112233")
    a.add_project("AlphaWebChild", p_alpha_child, root="/work/a/alphaweb/child", company_id=a_cid_acme, color="#223344")
    r_a1 = a.add_live_session(s_a1, "alpha_one", working_dir="/work/a/alphaweb", project_id=a_pid_parent, last_work_at="2026-11-26T10:00:00Z", tmux_created_epoch=1760000101)
    r_a2 = a.add_live_session(s_a2, "alpha_two", working_dir="/work/a/alphaweb", project_id=a_pid_parent, last_work_at="2026-11-26T10:05:00Z", tmux_created_epoch=1760000102)
    sync_direct_sessions_as_shadows(a, b, [s_a1, s_a2])
    sync_direct_sessions_as_shadows(a, c, [s_a1, s_a2])

    a.create_layout(ly1, "Core Pair", [r_a1, r_a2], style=("teal", "tide", "shimmer"), off_row_ids=[r_a2])
    a.create_layout(ly2, "Temp Layout", [r_a1], style=("rose", None, "pulse"))
    with closing(a.open_db()) as conn:
        for pos, (guid, gname, pkey) in enumerate(((g_co, "AcmeGrp", f"c:{a_cid_acme}"), (g_proj, "WebGrp", f"p:{a_pid_parent}"), (g_sub, "NestedGrp", f"g:{g_co}"))):
            conn.execute("INSERT INTO session_groups (group_uuid, name, position, created_at, updated_at, parent_key) VALUES (?, ?, ?, 't', 't', ?)", (guid, gname, pos, pkey))
        conn.commit()
        session_group_store.set_group_style(conn, g_co, "coral", "ember", "shimmer")
        session_group_store.set_group_icon(conn, g_co, "flask")
        session_group_store.set_group_rule(conn, g_co, ["running", "coffee"], "api", "v2")
        session_group_store.assign_session(conn, s_a1, g_co)
        assign_layout(conn, ly1, g_co)
        session_group_store.set_group_style(conn, g_proj, "#123456", None, "pulse")
        session_group_store.set_group_style(conn, g_sub, "gold", "dusk", "none")
        conn.commit()

    a.set_prefs({
        "theme": "matrix", "sidebar_density": "compact", "sidebar_layout": "rail",
        "sidebar_show_leaders": False, "sidebar_show_archived": True, "layout_tabs": [ly1],
        "stats_bar_rate": "min", "stats_bar_window": "5h",
        "drawer_arrangement": {
            "v": 1, "pinned": [f"layout:{ly1}", s_a1], "order": [], "bands": {}, "projects_open": False,
            "collapsed": ["companies", f"c:{a_cid_acme}", f"p:{a_pid_parent}", f"p:{a_pid_parent}:agents", f"g:{g_co}", f"layout:{ly1}"],
        },
    })
    a.looks.set_look(rl1, {"color": "cyan", "icon": "docs"})
    a.looks.set_look(rl2, {"color": "coral", "icon": "bolt"})

    b_cid_beta = b.add_company("BetaLabs", co_beta, hue=120)
    b.add_project("ArchivedProj", p_b_arch, root="/work/b/archived", company_id=b_cid_beta, color="#445566", archived_at="2026-11-25T00:00:00Z")
    b_pid_sleep = b.add_project("SleepProj", p_b_sleep, root="/work/b/sleep", company_id=b_cid_beta, color="#556677")
    b.add_live_session(s_b_live, "bravo_live", working_dir="/work/b/sleep", project_id=b_pid_sleep, last_work_at="2026-11-26T11:00:00Z", tmux_created_epoch=1760000201)
    b.add_asleep_session(s_b_sleep, "bravo_asleep", working_dir="/work/b/sleep", project_id=b_pid_sleep, last_work_at="2026-11-26T09:30:00Z", tmux_created_epoch=1760000202)
    c.add_project("ZeroSessProj", p_c_zero, root="/work/c/zero", color="#778899")
    c.add_live_session(s_c_live, "charlie_live", working_dir="/work/c/other", last_work_at="2026-11-26T12:00:00Z", tmux_created_epoch=1760000301)

    m.step_all()
    m.converge_star()
    m.step_all()
    m.converge_star()
    m.step_all()

    m.now_ms += 2000
    with closing(c.open_db()) as conn:
        conn.execute("UPDATE companies SET hue = 330 WHERE uid = ?", (co_acme,))
        conn.commit()
    with closing(a.open_db()) as conn:
        conn.execute("DELETE FROM companies WHERE uid = ?", (co_temp,))
        conn.commit()
    with closing(b.open_db()) as conn:
        layouts_store.delete_layout(conn, ly2)
        conn.commit()
    c.looks.forget(rl2)
    b.looks.set_look(rl1, {"color": "violet", "icon": "star"})

    m.step_all()
    assert a.panel_rows()[f"c:{co_temp}:gone"][0] is True
    assert b.panel_rows()[f"ly:{ly2}:gone"][0] is True
    assert c.workspace_rows()[f"rl:{rl2}"][0] == {"gone": True}
    m.converge_star()
    m.step_all()

    snap_a, snap_b, snap_c = snapshot_agent_bar(a), snapshot_agent_bar(b), snapshot_agent_bar(c)
    assert snap_a == snap_b == snap_c
    assert co_temp not in snap_a["companies"]
    assert snap_a["companies"] == {co_acme: ("Acme Corp", 330), co_beta: ("BetaLabs", 120)}
    assert snap_a["projects"][p_b_arch][3] is True
    assert snap_a["projects"][p_c_zero][0] == "ZeroSessProj"
    assert snap_a["projects"][p_alpha_child][4] == p_alpha_parent
    assert [ly[0] for ly in snap_a["layouts"]] == [ly1] and snap_a["layouts"][0][3] == [True, False]
    assert snap_a["groups"][g_co] == ("AcmeGrp", f"cu:{co_acme}", ("coral", "ember", "shimmer", "flask"), {"flags": ["running", "coffee"], "prefix": "api", "suffix": "v2"}, 2)
    assert snap_a["row_looks"] == {rl1: ("violet", "star")}

    with closing(b.open_db()) as conn:
        assert tuple(conn.execute("SELECT root, raw_path FROM projects WHERE uid = ?", (p_c_zero,)).fetchone()) == (f"peer://{c.iid}/{p_c_zero}", f"peer://{c.iid}/{p_c_zero}")

    asleep_from_b = peer_serve.serve_asleep_to_peer(b.open_db, caller_install_id=a.iid)
    assert len(asleep_from_b) == 1 and asleep_from_b[0]["tmux_session"] == "bravo_asleep"
    assert asleep_from_b[0]["last_work_at"] == "2026-11-26T09:30:00Z" and asleep_from_b[0]["tmux_created_epoch"] == 1760000202 and asleep_from_b[0]["project_uid"] == p_b_sleep

    links_a = StarSessionLinks(a, {b.iid: (b, CONNECTED), c.iid: (c, CONNECTED)})
    links_c = StarSessionLinks(c, {a.iid: (a, CONNECTED)}, hub_links={a.iid: links_a})
    rows_a = asyncio.run(peer_listing.for_caller(a.own_sessions, is_peer=False, open_db=a.open_db, links=links_a))
    assert {"alpha_one", "alpha_two", "bravo_live", "charlie_live"} <= {r.tmux_session for r in rows_a}
    by_name_c = {r.tmux_session: r for r in asyncio.run(peer_listing.for_caller(c.own_sessions, is_peer=False, open_db=c.open_db, links=links_c))}
    bravo_on_c = by_name_c["bravo_live"]
    assert bravo_on_c.hop == 1 and bravo_on_c.origin_install_id == b.iid and bravo_on_c.session_row_id is None
    assert bravo_on_c.last_work_at == "2026-11-26T11:00:00Z" and bravo_on_c.session.tmux_created_epoch == 1760000201
    with closing(c.open_db()) as conn:
        assert peer_forward.resolve(conn, bravo_on_c.session.id) is None




def test_e2e_p3_dashboards_charts_settings_3node_parity(e2e_mesh: Any) -> None:
    m, _topics, _contained = e2e_mesh(("a", "b", "c"), no_logins={"b", "c"})
    m.pair_star()
    a, b, c = m["a"], m["b"], m["c"]

    home_layout = build_large_home_layout()
    assert len(json.dumps(home_layout).encode("utf-8")) > 16384
    a.set_prefs({
        "home_layout": home_layout,
        "analytics_filters": {"range": "7d", "provider": "claude", "model": "claude-opus-4-6"},
        "analytics_timezone": "America/New_York",
        "timeline_filters": {"bookmarks": True, "compacts": False, "restarts": True, "sleeps": False, "restores": True},
        "widget_state": {"core.activity-log": {"level": "warn", "limit": 50}, "core.notes": {"pinned": True}},
    })

    ch_local_id, ch_pack_id = uuid.uuid4(), uuid.uuid4()
    stats_config.create_chart(a.stats, ChartWrite(id=ch_local_id, title="Alpha Local Burn", series=[{"metric": "total_tokens", "operation": "timeline", "filters": {"host": "local"}}], filters={"host": "local", "hosts": ["local", b.iid]}))
    stats_config.create_chart(a.stats, ChartWrite(id=ch_pack_id, title="Pack Total Tokens", series=[{"metric": "total_tokens", "operation": "timeline", "filters": {}}], filters={}))
    tw_keep = stats_tripwires.create_tripwire(a.stats, TripwireWrite(name="Keep Spike", query={"metric": "total_tokens", "operation": "summary", "filters": {"host": "local"}}, window_minutes=15, comparator=">", threshold=50000.0, for_minutes=5, cooldown_minutes=30, enabled=True))
    tw_drop = stats_tripwires.create_tripwire(a.stats, TripwireWrite(name="Drop Spike", query={"metric": "total_tokens", "operation": "summary", "filters": {}}, window_minutes=30, comparator=">", threshold=90000.0, for_minutes=5, cooldown_minutes=60, enabled=True))
    ann = stats_config.create_annotation(a.stats, AnnotationWrite(occurred_at=datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc), kind="manual", label="Shipped P3", scope={"host": "local", "provider": "claude"}, basis="manual"))
    stats_config.update_settings(a.stats, enabled=False, revision=stats_config.get_settings(a.stats)["revision"])

    with closing(a.open_db()) as conn:
        item_settings_store.write_item(conn, "widget", "core.stat-running", enabled=False)
        conn.execute(
            f"INSERT INTO {ITEM_SETTINGS_TABLE} (kind, item_id, enabled, schema_version, values_json, revision, updated_at) VALUES ('widget', 'custom.widget', 1, 1, ?, 2, '2026-11-26T00:00:00Z')",
            (json.dumps({"limit": 25, "api_key": "sk-secret-never-sync", "password": "pw-secret", "auth_token": "tok-secret", "cookie": "c=1", "nested": {"secret": "hidden", "ok": True}}),),
        )
        conn.commit()

    m.step_all()
    assert a.workspace_rows()["db:home:rows"][0]["chunked"] is True and "db:home:r.0" in a.workspace_rows() and "db:home:r.1" in a.workspace_rows()
    assert a.workspace_rows()[f"sc:{ch_local_id}"][0]["filters"]["host"] == a.iid
    assert a.workspace_rows()["ws:custom.widget"][0] == {"enabled": True, "settings": {"limit": 25, "nested": {"ok": True}}}
    m.converge_star()
    m.step_all()

    m.now_ms += 2000
    b_ch = stats_config.get_chart(b.stats, str(ch_pack_id))
    stats_config.update_chart(b.stats, str(ch_pack_id), ChartWrite(id=ch_pack_id, title="Pack Tokens (Edited on B)", series=[{"metric": "total_tokens", "operation": "timeline", "filters": {}}], filters={}), b_ch["revision"])
    stats_tripwires.delete_tripwire(c.stats, tw_drop["id"])
    m.step_all()
    m.converge_star()
    m.step_all()

    for node in (a, b, c):
        prefs = node.prefs()
        assert prefs["home_layout"] == home_layout
        assert prefs["analytics_filters"] == {"range": "7d", "provider": "claude", "model": "claude-opus-4-6"}
        assert prefs["analytics_timezone"] == "America/New_York"
        assert prefs["timeline_filters"] == {"bookmarks": True, "compacts": False, "restarts": True, "sleeps": False, "restores": True}
        assert prefs["widget_state"] == {"core.activity-log": {"level": "warn", "limit": 50}, "core.notes": {"pinned": True}}
        assert stats_config.get_chart(node.stats, str(ch_pack_id))["title"] == "Pack Tokens (Edited on B)"
        ch_loc = stats_config.get_chart(node.stats, str(ch_local_id))
        expected_host = "local" if node is a else a.iid
        assert ch_loc["filters"]["host"] == expected_host and ch_loc["series"][0]["filters"]["host"] == expected_host
        assert stats_tripwires.get_tripwire(node.stats, tw_keep["id"])["name"] == "Keep Spike"
        with pytest.raises(stats_config.NotFound):
            stats_tripwires.get_tripwire(node.stats, tw_drop["id"])
        assert stats_config.get_annotation(node.stats, ann["id"])["label"] == "Shipped P3"
        assert stats_config.get_settings(node.stats)["enabled"] is False

    for peer in (b, c):
        with closing(peer.open_db()) as conn:
            assert item_settings_store.read_item(conn, "widget", "core.stat-running").enabled is False
            row = conn.execute(f"SELECT enabled, values_json FROM {ITEM_SETTINGS_TABLE} WHERE kind='widget' AND item_id='custom.widget'").fetchone()
            assert row is not None and bool(row["enabled"]) is True
            assert json.loads(row["values_json"]) == {"limit": 25, "nested": {"ok": True}}
            for secret_word in ("api_key", "sk-secret", "password", "auth_token", "cookie", "hidden"):
                assert secret_word not in row["values_json"]




def test_e2e_p4_stats_rollup_v2_and_queries_3node_parity(e2e_mesh: Any) -> None:
    h_recent = (int(time.time()) // 3600) * 3600 - 3600
    day = 86400
    t_mark = h_recent - 10 * day
    m, _topics, _contained = e2e_mesh(("a", "b", "c"), now_s=float(h_recent + 3500))
    m.pair_star()
    a, b, c = m["a"], m["b"], m["c"]

    root_a, root_b, root_c = "/work/a/app", "/work/b/app", "/work/c/app"
    proj_a, proj_b, proj_c = project_key(root_a), project_key(root_b), project_key(root_c)
    a.add_project("AlphaApp", uid(301), root=root_a)
    b.add_project("BetaApp", uid(302), root=root_b)
    c.add_project("GammaApp", uid(303), root=root_c)

    a.seed_conversation_stats(
        path_key=101, conversation_id="conv-a", provider="claude", agent_kind="session", account_id="acct-alpha", subagent_type="primary",
        model="claude-opus", project_hash=proj_a, usage_points=[(h_recent + 60, (100, 10, 40, 20), 1700, 1), (h_recent + 15 * 60 + 60, (400, 20, 80, 50), 5500, 2)],
        turns=3, activity_points=[(h_recent + 60, (60.0, 45.0, 60.0, 1, 0, 5.0, 10.0))],
    )
    b.seed_conversation_stats(
        path_key=201, conversation_id="conv-b", provider="claude", agent_kind="subagent", account_id="acct-beta", subagent_type="research",
        model="claude-sonnet", project_hash=proj_b, usage_points=[(h_recent + 5 * 60 + 60, (150, 0, 50, 30), 2300, 1), (h_recent + 20 * 60 + 60, (250, 10, 40, 40), 3400, 1)],
        turns=4, activity_points=[(h_recent + 5 * 60 + 60, (120.0, 90.0, 100.0, 1, 1, 10.0, 20.0))],
    )
    c.seed_conversation_stats(
        path_key=301, conversation_id="conv-c", provider="codex", agent_kind="agent", account_id="acct-gamma", subagent_type="worker",
        model="gpt-5-codex", project_hash=proj_c, usage_points=[(h_recent + 10 * 60 + 60, (300, 0, 0, 60), 3600, 2)],
        turns=5, activity_points=[(h_recent + 10 * 60 + 60, (180.0, 120.0, 150.0, 1, 1, 15.0, 0.0))],
    )
    for node, pk in ((a, 199), (b, 299)):
        node.seed_conversation_stats(
            path_key=pk, conversation_id="conv-overlap", provider="claude", agent_kind="session", account_id="acct-alpha", subagent_type="primary",
            model="claude-opus", project_hash=proj_a, usage_points=[(h_recent + 25 * 60 + 60, (77, 0, 0, 0), 770, 1)], turns=1,
        )
    for i, (node, proj_h) in enumerate(((a, proj_a), (b, proj_b), (c, proj_c))):
        for k in range(2):
            node.seed_conversation_stats(path_key=400 + i * 10 + k, conversation_id=f"c-before-{node.name}-{k}", provider="claude", agent_kind="session", account_id="acct-alpha", subagent_type="primary", model="claude-sonnet", project_hash=proj_h, usage_points=[(t_mark - 2 * day + k * 3600 + 60, (100, 0, 0, 0), 1000 + i * 50, 1)], turns=1)
            node.seed_conversation_stats(path_key=500 + i * 10 + k, conversation_id=f"c-after-{node.name}-{k}", provider="claude", agent_kind="session", account_id="acct-alpha", subagent_type="primary", model="claude-opus", project_hash=proj_h, usage_points=[(t_mark + 2 * day + k * 3600 + 60, (600, 0, 0, 0), 6000 + i * 50, 1)], turns=1)

    a.seed_quota(minute_ts=h_recent, provider="claude", account_id="acct-shared", window="five_hour", utilization=45.0, fetched_at=float(h_recent + 20))
    b.seed_quota(minute_ts=h_recent, provider="claude", account_id="acct-shared", window="five_hour", utilization=45.0, fetched_at=float(h_recent + 30))
    a.seed_quota(minute_ts=h_recent, provider="claude", account_id="acct-alpha", window="five_hour", utilization=20.0, fetched_at=float(h_recent + 10))
    b.seed_quota(minute_ts=h_recent, provider="claude", account_id="acct-beta", window="five_hour", utilization=55.0, fetched_at=float(h_recent + 10))
    c.seed_quota(minute_ts=h_recent, provider="codex", account_id="acct-gamma", window="five_hour", utilization=80.0, fetched_at=float(h_recent + 10))

    stats_events.record("model_first_seen", "claude-opus", {"model": "claude-opus"}, store=a.stats, occurred_at=h_recent + 10)
    stats_events.record("model_first_seen", "claude-sonnet", {"model": "claude-sonnet"}, store=b.stats, occurred_at=h_recent + 20)
    stats_events.record("model_first_seen", "gpt-5-codex", {"model": "gpt-5-codex"}, store=c.stats, occurred_at=h_recent + 30)

    for node, conv_id, wdir in ((a, "conv-a", root_a), (b, "conv-b", root_b), (c, "conv-c", root_c)):
        with closing(node.open_db()) as conn:
            conn.execute("INSERT INTO sessions (session_uuid, tmux_name, working_dir, origin, created_at, updated_at, claude_session_uuid) VALUES (?, ?, ?, 'created', '2026-11-26', '2026-11-26', ?)", (conv_id, f"tmux_{conv_id}", wdir, conv_id))
            conn.commit()
    a.seed_mcp_call("a-1", h_recent + 10, "whoami", "ok", 50)
    b.seed_mcp_call("b-1", h_recent + 20, "whoami", "error", 90)
    b.seed_mcp_call("b-2", h_recent + 25, "sessions_list", "ok", 40)
    c.seed_mcp_call("c-1", h_recent + 30, "whoami", "ok", 60)
    for node in (a, b, c):
        node.rebuild_local_mcp_usage()

    ann_id = stats_config.create_annotation(a.stats, AnnotationWrite(occurred_at=datetime.fromtimestamp(t_mark, timezone.utc), label="Tune Prompt", kind="manual"))["id"]
    m.step_all()
    m.converge_star()
    m.step_all()
    m.pull_rollups_star()

    with closing(b.open_db()) as conn:
        assert conn.execute(f"SELECT COUNT(*) FROM {USAGE_5M_TABLE} WHERE peer_install_id = ?", (c.iid,)).fetchone()[0] >= 1
    with closing(c.open_db()) as conn:
        assert conn.execute(f"SELECT COUNT(*) FROM {USAGE_5M_TABLE} WHERE peer_install_id = ?", (b.iid,)).fetchone()[0] >= 1

    def _collect_p4_answers(node: PackParityNode) -> Dict[str, Any]:
        clear_stats_caches()
        q_5m = queries.execute(node.stats, build_query("total_tokens", h_recent, h_recent + 3600, resolution="5minute"))
        act_sum = queries.execute(node.stats, build_query("working_seconds", h_recent, h_recent + 3600, operation="summary", resolution="5minute"))["summary"]["value"]
        swim = queries.execute(node.stats, build_query("working_seconds", h_recent, h_recent + 3600, operation="timeline", resolution="5minute", group_by="conversation_id"))
        runway = queries.execute(node.stats, build_query("quota_utilization", h_recent, h_recent + 3600, operation="timeline", resolution="5minute", group_by="account_id", filters={"window": "five_hour"}))
        by_acct = {r["filter_value"]: r["value"] for r in queries.execute(node.stats, build_query("total_tokens", h_recent, h_recent + 3600, operation="ranking", resolution="hour", group_by="account_id"))["ranking"]}
        by_sub = {r["filter_value"]: r["value"] for r in queries.execute(node.stats, build_query("total_tokens", h_recent, h_recent + 3600, operation="ranking", resolution="hour", group_by="subagent_type"))["ranking"]}
        alpha_only = queries.execute(node.stats, build_query("total_tokens", h_recent, h_recent + 3600, operation="summary", resolution="hour", filters={"host": IID_ALPHA}))["summary"]["value"]
        ov_a = queries.execute(node.stats, build_query("total_tokens", h_recent, h_recent + 3600, operation="summary", resolution="hour", filters={"host": IID_ALPHA, "conversation_id": "conv-overlap"}))["summary"]["value"]
        ov_b = queries.execute(node.stats, build_query("total_tokens", h_recent, h_recent + 3600, operation="summary", resolution="hour", filters={"host": IID_MEMBER_B, "conversation_id": "conv-overlap"}))["summary"]["value"]
        convs = insights.conversations(node.stats, start=h_recent, end=h_recent + 3600, filters=StatsFilters(), scope="pack")
        imp = insights.impact(node.stats, annotation_id=ann_id, metric="estimated_cost_nano_usd", days=4, now=t_mark + 4 * day, scope="pack")
        evs = stats_events.list_events(node.stats, start=h_recent, end=h_recent + 100, kind=None, limit=20, cursor=0, scope="pack")
        cov = queries.coverage(node.stats)
        contrib = queries.contributions(node.stats, build_query("total_tokens", h_recent, h_recent + 3600, operation="summary", resolution="hour", scope="pack"), limit=20, cursor=0)
        dims = {d: {it["filter_value"] for it in queries.dimensions(node.stats, dimension=d, filters=StatsFilters(), start=None, end=None, limit=50, cursor=0, scope="pack")["items"]} for d in ("model", "provider", "account_id")}
        dims["project"] = {it["label"] for it in queries.dimensions(node.stats, dimension="project", filters=StatsFilters(), start=None, end=None, limit=50, cursor=0, scope="pack")["items"]}
        dims["host"] = {node.iid if it["filter_value"] == "local" else it["filter_value"] for it in queries.dimensions(node.stats, dimension="host", filters=StatsFilters(), start=None, end=None, limit=50, cursor=0, scope="pack")["items"]}
        now_dt = datetime.fromtimestamp(h_recent + 3600, timezone.utc)
        su = session_usage_rollup.build(7, now=now_dt, db=node.dir / "carnivore.db", stats_db=node.stats.db_path, scope="pack")
        mcp_rep = mcp_report.build(30, ["whoami", "sessions_list"], node.mcp_usage_db, now_dt, scope="pack", app_db=node.dir / "carnivore.db")
        return {
            "curve_5m": [(p["time"], p["value"]) for p in q_5m["series"][0]["points"] if p["value"] is not None],
            "act_sum": act_sum, "swim_convs": sorted(s["filter_value"] for s in swim["series"]),
            "quota_by_acct": {s["filter_value"]: [p["value"] for p in s["points"] if p["value"] is not None] for s in runway["series"]},
            "by_acct": by_acct, "by_sub": by_sub, "alpha_only": alpha_only, "ov_a": ov_a, "ov_b": ov_b,
            "conv_sig": sorted((it["conversation_id"], it["tokens"], it["cost_nano_usd"], it["project"], it["model"]) for it in convs["items"]),
            "impact": (imp["before"]["n"], imp["after"]["n"], imp["verdict"]),
            "events": [(e["occurred_at"], e["kind"], e["subject"], e["data"]) for e in evs["items"]],
            "coverage": (cov["earliest"], cov["latest"], cov["minute_rows"]),
            "contrib": sorted((it["conversation_id"], it["value"]) for it in contrib["items"]),
            "dims": dims,
            "session_usage": {sid: round(val["worked_s"], 1) for sid, val in su["by_session"].items()},
            "mcp": {r["tool"]: (r["total"], dict(r["by_outcome"])) for r in mcp_rep["tools"]},
        }

    ans_a, ans_b, ans_c = _collect_p4_answers(a), _collect_p4_answers(b), _collect_p4_answers(c)
    assert ans_a == ans_b == ans_c
    assert [v for _t, v in ans_a["curve_5m"]] == [170, 230, 360, 550, 340, 77]
    assert ans_a["act_sum"] == pytest.approx(255.0) and ans_a["swim_convs"] == ["conv-a", "conv-b", "conv-c"]
    assert ans_a["quota_by_acct"] == {"acct-shared": [45.0], "acct-alpha": [20.0], "acct-beta": [55.0], "acct-gamma": [80.0]}
    assert ans_a["by_acct"] == {"acct-alpha": 797, "acct-beta": 570, "acct-gamma": 360}
    assert ans_a["by_sub"] == {"primary": 797, "research": 570, "worker": 360}
    assert ans_a["alpha_only"] == 797 and ans_a["ov_a"] == 77 and ans_a["ov_b"] is None
    assert ans_a["impact"] == (6, 6, "higher") and ans_a["dims"]["host"] == {IID_ALPHA, IID_MEMBER_B, IID_MEMBER_C}
    assert {"AlphaApp", "BetaApp", "GammaApp"} <= ans_a["dims"]["project"]
    assert ans_a["session_usage"] == {"conv-a": 45.0, "conv-b": 90.0, "conv-c": 120.0}
    assert ans_a["mcp"]["whoami"] == (3, {"ok": 2, "error": 1}) and ans_a["mcp"]["sessions_list"] == (1, {"ok": 1})




def test_e2e_p5_live_telemetry_3node_star_mesh_parity(e2e_mesh: Any, monkeypatch: Any) -> None:
    telemetry_kind, mesh_telemetry = _import_p5_telemetry()

    now_s = float((int(time.time()) // 60) * 60)
    m, _topics, _contained = e2e_mesh(("a", "b", "c"), no_logins={"b", "c"}, now_s=now_s)
    m.pair_star()

    machine_readings: Dict[str, Dict[str, Any]] = {
        "a": {"cpu_percent": 32.0, "cpu_count": 12, "memory_percent": 50.0, "memory_used_bytes": 16 * 1024**3, "memory_total_bytes": 32 * 1024**3, "disk_percent": 40.0, "disk_free_bytes": 600 * 1024**3, "disk_total_bytes": 1000 * 1024**3, "load_1": 2.5, "load_5": 2.1, "load_15": 1.8, "uptime_seconds": 86400, "live_agents": 2},
        "b": {"cpu_percent": 48.0, "cpu_count": 8, "memory_percent": 62.5, "memory_used_bytes": 10 * 1024**3, "memory_total_bytes": 16 * 1024**3, "disk_percent": 50.0, "disk_free_bytes": 250 * 1024**3, "disk_total_bytes": 500 * 1024**3, "load_1": 3.0, "load_5": 2.5, "load_15": 2.0, "uptime_seconds": 43200, "live_agents": 1},
        "c": {"cpu_percent": 20.0, "cpu_count": 16, "memory_percent": 37.5, "memory_used_bytes": 24 * 1024**3, "memory_total_bytes": 64 * 1024**3, "disk_percent": 25.0, "disk_free_bytes": 1500 * 1024**3, "disk_total_bytes": 2000 * 1024**3, "load_1": 1.5, "load_5": 1.4, "load_15": 1.2, "uptime_seconds": 172800, "live_agents": 3},
    }
    labels = {"a": "Alpha-Mac", "b": "Bravo-Box", "c": "Charlie-Node"}
    reset_5h = datetime.fromtimestamp(now_s + 18000, timezone.utc)
    reset_7d = datetime.fromtimestamp(now_s + 604800, timezone.utc)

    def _acct(aid: str, name: str, provider: str, org_id: str, pct5: float, pct7: float) -> AccountUsage:
        return AccountUsage(
            id=aid, name=name, provider=provider, plan="max", credential_state="ok", identity=org_id,  # type: ignore[arg-type]
            fetched_at=datetime.fromtimestamp(now_s, timezone.utc),
            windows=[
                UsageWindow(kind="five_hour" if provider == "claude" else "primary", label="5h", used_pct=pct5, window_seconds=18000, resets_at=reset_5h),
                UsageWindow(kind="seven_day" if provider == "claude" else "secondary", label="7d", used_pct=pct7, window_seconds=604800, resets_at=reset_7d),
            ],
        )

    local_accounts: Dict[str, List[AccountUsage]] = {
        "a": [_acct("shared-cl", "Shared Claude", "claude", "org-shared", 40.0, 20.0), _acct("only-a", "Alpha Claude", "claude", "org-a", 15.0, 10.0)],
        "b": [_acct("shared-cl", "Shared Claude", "claude", "org-shared", 40.0, 20.0), _acct("only-b", "Bravo Codex", "codex", "org-b", 60.0, 30.0)],
        "c": [_acct("only-c", "Charlie Claude", "claude", "org-c", 75.0, 50.0)],
    }

    for idx, (n, model_name, fresh, cw, cr, out, cost) in enumerate((
        ("a", "claude-opus", 500, 100, 400, 200, 12000),
        ("b", "claude-sonnet", 300, 50, 250, 100, 7000),
        ("c", "gpt-5-codex", 600, 0, 200, 150, 9500),
    )):
        node = m[n]
        node.add_project(f"Live-{n.upper()}", uid(400 + idx), root=f"/work/{n}/live")
        node.seed_conversation_stats(
            path_key=700 + idx, conversation_id=f"live-conv-{n}", provider="codex" if n == "c" else "claude",
            agent_kind="session", account_id=f"acct-{n}", subagent_type="primary", model=model_name,
            project_hash=project_key(f"/work/{n}/live"), usage_points=[(int(now_s) - 60, (fresh, cw, cr, out), cost, 2)], turns=2,
        )

    assert telemetry_kind.KIND in importlib.import_module("src.core.pack.meshdata.kinds").KINDS
    payloads: Dict[str, Dict[str, Any]] = {}
    for n in ("a", "b", "c"):
        node = m[n]
        with closing(node.open_db()) as conn:
            payload = mesh_telemetry.collect(conn, node.stats, self_id=node.iid, label=labels[n], app_version="1.99.0", machine=machine_readings[n], ledger_accounts=local_accounts[n], now=now_s)
        assert telemetry_kind.valid(payload) is True
        payloads[n] = payload
        assert mesh_telemetry.publish_now(m.stores[n], m.roster(), m.signing[n], payload) is True

    m.converge_star()
    peers_by_node = {n: mesh_telemetry.fresh_peers(m.stores[n], m.roster(), m[n].iid, now=now_s) for n in ("a", "b", "c")}
    for n in ("a", "b", "c"):
        assert set(peers_by_node[n]) == {IID_ALPHA, IID_MEMBER_B, IID_MEMBER_C} - {m[n].iid}

    live_ans = {n: live_view.live_v2(m[n].stats, now=now_s, peer_telemetry=peers_by_node[n], scope="pack") for n in ("a", "b", "c")}
    assert live_ans["a"]["cache_hit_ratio_15m"] == pytest.approx(live_ans["b"]["cache_hit_ratio_15m"], abs=1e-6)
    assert live_ans["a"]["cache_hit_ratio_15m"] == pytest.approx(live_ans["c"]["cache_hit_ratio_15m"], abs=1e-6)
    assert live_ans["a"]["active_models_15m"] == live_ans["b"]["active_models_15m"] == live_ans["c"]["active_models_15m"] == ["claude-opus", "gpt-5-codex", "claude-sonnet"]
    for w in ("5m", "15m", "60m"):
        for f in ("tokens_per_minute", "estimated_usd_per_hour"):
            assert live_ans["a"]["burn"][w][f] == pytest.approx(live_ans["b"]["burn"][w][f], abs=2e-3)
            assert live_ans["a"]["burn"][w][f] == pytest.approx(live_ans["c"]["burn"][w][f], abs=2e-3)
    assert [(x["conversation_id"], x["tokens"], x["model"]) for x in live_ans["a"]["top_conversations_15m"]] == [(x["conversation_id"], x["tokens"], x["model"]) for x in live_ans["b"]["top_conversations_15m"]] == [(x["conversation_id"], x["tokens"], x["model"]) for x in live_ans["c"]["top_conversations_15m"]]
    assert [(x["conversation_id"], x["tokens"]) for x in live_ans["a"]["agents_5m"]] == [(x["conversation_id"], x["tokens"]) for x in live_ans["b"]["agents_5m"]] == [(x["conversation_id"], x["tokens"]) for x in live_ans["c"]["agents_5m"]]

    spec_1h = feed_model.WINDOWS["1h"]
    overlays = {
        n: feed_peers.overlay(
            feed_peers.PeerBook(), spec_1h, now_s, 100.0,
            feed_peers._telemetry_bars(payloads[n]["vitals_15m"]["feed_buckets_1m"], spec_1h, now_s) or [],
            payloads[n]["vitals_15m"]["feed_rate"], "ok", peer_telemetry=peers_by_node[n],
        )
        for n in ("a", "b", "c")
    }
    assert overlays["a"].bars == overlays["b"].bars == overlays["c"].bars
    assert overlays["a"].rate == overlays["b"].rate == overlays["c"].rate and overlays["a"].rate is not None and overlays["a"].rate["fresh"] > 0

    pack_settings = settings_doc.PackSettings(rev=(1, IID_ALPHA), master_install_id=IID_ALPHA)
    view_b = roster_mod.Roster(clock=lambda: now_s).view(self_snapshot=machine_readings["b"], self_id=IID_MEMBER_B, self_label=labels["b"], peers=[], settings=pack_settings, peer_telemetry=peers_by_node["b"])
    view_c = roster_mod.Roster(clock=lambda: now_s).view(self_snapshot=machine_readings["c"], self_id=IID_MEMBER_C, self_label=labels["c"], peers=[], settings=pack_settings, peer_telemetry=peers_by_node["c"])
    b_map, c_map = {r["install_id"]: r for r in view_b["machines"]}, {r["install_id"]: r for r in view_c["machines"]}
    assert set(b_map) == set(c_map) == {IID_ALPHA, IID_MEMBER_B, IID_MEMBER_C}
    assert (b_map[IID_MEMBER_C]["snapshot"]["cpu_percent"], b_map[IID_MEMBER_C]["snapshot"]["memory_percent"], b_map[IID_MEMBER_C]["snapshot"]["disk_percent"], b_map[IID_MEMBER_C]["snapshot"]["live_agents"]) == (20.0, 37.5, 25.0, 3)
    assert (c_map[IID_MEMBER_B]["snapshot"]["cpu_percent"], c_map[IID_MEMBER_B]["snapshot"]["memory_percent"], c_map[IID_MEMBER_B]["snapshot"]["disk_percent"], c_map[IID_MEMBER_B]["snapshot"]["live_agents"]) == (48.0, 62.5, 50.0, 1)

    monkeypatch.setattr(ledger_sync_store, "statuses_by_profile", lambda: {})
    monkeypatch.setattr(relay_accounts, "all_relay_rows", lambda stored=None: [])
    ledger_sigs: Dict[str, Any] = {}
    for n in ("a", "b", "c"):
        assembled = provider_ledger_routes._assemble_ledger_snapshot(
            LedgerSnapshot(accounts=local_accounts[n], total=LedgerTotal(accounts=len(local_accounts[n]), windows=[]), loop=LoopStatus(alive=True)),
            peer_telemetry=peers_by_node[n],
        )
        ledger_sigs[n] = (sorted((a_.name, a_.provider, tuple((w.label, w.used_pct) for w in a_.windows)) for a_ in assembled.accounts), assembled.total.model_dump())
    assert ledger_sigs["a"] == ledger_sigs["b"] == ledger_sigs["c"] and len(ledger_sigs["a"][0]) == 4

    ms_by_node: Dict[str, Any] = {}
    for n in ("a", "b", "c"):
        ms = machine_stats_routes.build_pack_machine_stats(
            {k: v for k, v in machine_readings[n].items() if k != "live_agents"},
            self_id=m[n].iid, self_label=labels[n], peer_telemetry=peers_by_node[n], self_live_agents=machine_readings[n]["live_agents"],
        )
        ms_by_node[n] = ([(e.install_id, e.label, e.cpu_percent, e.memory_percent, e.disk_percent, e.live_agents) for e in ms.machines], ms.pack_aggregate.model_dump() if ms.pack_aggregate else None)
    assert ms_by_node["a"] == ms_by_node["b"] == ms_by_node["c"]
    assert [row[0] for row in ms_by_node["a"][0]] == [IID_ALPHA, IID_MEMBER_B, IID_MEMBER_C] and ms_by_node["a"][1]["live_agents"] == 6




def test_e2e_air_gap_one_way_and_offline_resilience(e2e_mesh: Any) -> None:
    now_s = (int(time.time()) // 3600) * 3600 - 3600
    m, _topics, contained_ids = e2e_mesh(("a", "b", "c", "d"), no_logins={"b", "c"}, one_way={"d"}, now_s=float(now_s + 3500))
    m.pair_star(include_d=True)
    a, b, c, d = m["a"], m["b"], m["c"], m["d"]

    open_root, secret_root = "/work/b/open-proj", "/work/b/secret-vault"
    open_hash, secret_hash = project_key(open_root), project_key(secret_root)
    b_open_pid = b.add_project("OpenProj", uid(501), root=open_root, air_gap=0)
    b_secret_pid = b.add_project("SecretVault", uid(502), root=secret_root, air_gap=1)
    b.add_live_session(u36(811), "b_open_sess", working_dir=open_root, project_id=b_open_pid)
    b.add_live_session(u36(812), "b_secret_sess", working_dir=secret_root, project_id=b_secret_pid)

    gate_b = peer_air_gap.load_gate(b.dir)
    assert gate_b.active is True and gate_b.inside(secret_root) is True and gate_b.inside(f"{secret_root}/nested") is True and gate_b.inside(open_root) is False

    b.seed_conversation_stats(path_key=801, conversation_id="conv-open", provider="claude", agent_kind="session", account_id="acct-b", subagent_type="primary", model="claude-opus", project_hash=open_hash, usage_points=[(now_s + 60, (200, 0, 0, 50), 2500, 1)], turns=2, activity_points=[(now_s + 60, (60.0, 40.0, 60.0, 1, 0, 0.0, 0.0))])
    b.seed_conversation_stats(path_key=802, conversation_id="conv-secret", provider="claude", agent_kind="session", account_id="acct-b", subagent_type="primary", model="claude-opus", project_hash=secret_hash, usage_points=[(now_s + 60, (9999, 0, 0, 999), 99999, 5)], turns=9, activity_points=[(now_s + 60, (300.0, 250.0, 300.0, 1, 0, 0.0, 0.0))])

    clear_stats_caches()
    allow_b = rollup.allowed_projects(b.stats)
    assert allow_b is not None and open_hash in allow_b and secret_hash not in allow_b
    v2_b = v2_export.build_v2(b.stats, b.open_db, allow_projects=allow_b, now=float(now_s + 3500))
    assert secret_hash not in v2_store.v2_projects(v2_b) and "conv-secret" not in v2_b["conv_meta"] and "conv-open" in v2_b["conv_meta"]

    m.pull_rollups_star()
    for peer in (a, c):
        with closing(peer.open_db()) as conn:
            for tbl in (USAGE_TABLE, USAGE_5M_TABLE, ACTIVITY_TABLE, CONVERSATIONS_TABLE, PROJECTS_TABLE):
                assert conn.execute(f"SELECT COUNT(*) FROM {tbl} WHERE project = ?", (secret_hash,)).fetchone()[0] == 0, (peer.name, tbl)
            assert conn.execute(f"SELECT COUNT(*) FROM {PROJECTS_TABLE} WHERE name = 'SecretVault'").fetchone()[0] == 0
            assert conn.execute(f"SELECT COUNT(*) FROM {USAGE_TABLE} WHERE peer_install_id = ? AND project = ?", (b.iid, open_hash)).fetchone()[0] >= 1
            assert conn.execute(f"SELECT COUNT(*) FROM {USAGE_5M_TABLE} WHERE peer_install_id = ? AND project = ?", (b.iid, open_hash)).fetchone()[0] >= 1

    telemetry_kind, mesh_telemetry = _import_p5_telemetry()
    tel_now = float(now_s + 120)
    with closing(b.open_db()) as conn:
        b_tel = mesh_telemetry.collect(conn, b.stats, self_id=b.iid, label="b", now=tel_now)
    assert "conv-secret" not in json.dumps(b_tel) and "SecretVault" not in json.dumps(b_tel)
    assert mesh_telemetry.publish_now(m.stores["b"], m.roster(), m.signing["b"], b_tel) is True
    m.converge_star()
    for peer in (a, c):
        peer_tel = mesh_telemetry.fresh_peers(m.stores[peer.name], m.roster(), peer.iid, now=tel_now)
        assert b.iid in peer_tel and "conv-secret" not in json.dumps(peer_tel) and "SecretVault" not in json.dumps(peer_tel)

    contained_ids.add(d.iid)
    assert panel_kind.origin_ok(m.roster(), d.iid) is False and panel_kind.serve_ok(m.roster(), d.iid) is False
    assert workspace_kind.origin_ok(m.roster(), d.iid) is False and workspace_kind.serve_ok(m.roster(), d.iid) is False
    assert telemetry_kind.origin_ok(m.roster(), d.iid) is False and telemetry_kind.serve_ok(m.roster(), d.iid) is False
    with closing(d.open_db()) as conn:
        assert mesh_telemetry.publish_now(m.stores["d"], m.roster(), m.signing["d"], mesh_telemetry.collect(conn, d.stats, self_id=d.iid, label="d", now=tel_now)) is False

    a.add_company("AlphaCo", uid(601), hue=180)
    a.set_prefs({
        "theme": "matrix",
        "home_layout": {
            "v": 2, "active": "home", "analytics_seed": 2,
            "boards": [{"id": "home", "name": "Home", "layout": {"v": 6, "rows": [{"id": "r1", "kind": "px", "size": 220, "slots": [{"id": "running-sessions", "fr": 1.0}]}], "hidden": [], "heroCollapsed": False, "collapsed": []}}],
        },
    })
    ch_id = uuid.uuid4()
    stats_config.create_chart(a.stats, ChartWrite(id=ch_id, title="Offline Resilient Chart", series=[{"metric": "total_tokens", "operation": "summary", "filters": {}}], filters={}))
    d.add_company("RogueOneWayCo", uid(699), hue=10)
    d.set_prefs({"theme": "cyberpunk"})

    m.step_all(("a", "b", "c", "d"))
    m.converge_star(edges=[("a", "b"), ("a", "c"), ("a", "d")])
    m.step_all(("a", "b", "c", "d"))

    assert d.panel_rows() == {} and d.workspace_rows() == {} and d.prefs().get("theme") != "matrix"
    for node in (a, b, c):
        with closing(node.open_db()) as conn:
            assert conn.execute("SELECT COUNT(*) FROM companies WHERE uid = ?", (uid(699),)).fetchone()[0] == 0
        assert node.prefs().get("theme") == "matrix"
    d.pull_rollups_from(a)
    with closing(d.open_db()) as conn:
        assert conn.execute(f"SELECT COUNT(*) FROM {USAGE_TABLE}").fetchone()[0] == 0 and conn.execute(f"SELECT COUNT(*) FROM {USAGE_5M_TABLE}").fetchone()[0] == 0
    assert peer_serve.serve_to_peer(a.own_sessions, a.open_db, caller_install_id=d.iid) == []
    assert peer_serve.serve_relayed_to_peer({b.iid: b.own_sessions}, a.open_db, caller_install_id=d.iid) == []

    clear_stats_caches()
    b_before_5m = queries.execute(b.stats, build_query("total_tokens", now_s, now_s + 3600, resolution="5minute"))["series"][0]["points"]
    c_before_5m = queries.execute(c.stats, build_query("total_tokens", now_s, now_s + 3600, resolution="5minute"))["series"][0]["points"]
    b_before_bar, c_before_bar = snapshot_agent_bar(b), snapshot_agent_bar(c)

    a.online = False
    m.converge_star()
    b.pull_rollups_from(a)
    c.pull_rollups_from(a)

    for node, before_bar, before_5m, expected_total, expected_convs in (
        (b, b_before_bar, b_before_5m, 11248, ["conv-open", "conv-secret"]),
        (c, c_before_bar, c_before_5m, 250, ["conv-open"]),
    ):
        clear_stats_caches()
        assert snapshot_agent_bar(node) == before_bar
        assert node.prefs()["home_layout"]["active"] == "home"
        assert stats_config.get_chart(node.stats, str(ch_id))["title"] == "Offline Resilient Chart"
        assert queries.execute(node.stats, build_query("total_tokens", now_s, now_s + 3600, resolution="5minute"))["series"][0]["points"] == before_5m
        assert queries.execute(node.stats, build_query("total_tokens", now_s, now_s + 3600, operation="summary", resolution="hour"))["summary"]["value"] == expected_total
        assert sorted(it["conversation_id"] for it in insights.conversations(node.stats, start=now_s, end=now_s + 3600, filters=StatsFilters(), scope="pack")["items"]) == expected_convs
