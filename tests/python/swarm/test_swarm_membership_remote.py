
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from tests.python.swarm.test_swarm_membership import members  # noqa: F401
from tests.python.swarm.test_swarm_project_promote import _db, _row_id, env, world  # noqa: F401
from src.core.pack.machines import capabilities
from src.core.pack.span import body_host, remote_body
from src.core.swarm import membership, store

PEER = SimpleNamespace(key="studio", peer_install_id="iid-studio", label="studio")


@pytest.fixture()
def far(members, monkeypatch):
    row = _row_id(members, "other")
    _db(members, lambda c: c.execute("UPDATE sessions SET host_key = 'studio' WHERE id = ?", (row,)))
    _db(members, lambda c: c.execute("INSERT INTO peer_sessions (host_key, peer_session_uuid, peer_row_id, peer_name, session_id) "
                                     "VALUES ('studio', 'far-uuid-1', 7, 'carnivore_other', ?)", (row,)))
    caps = []
    monkeypatch.setattr(remote_body, "peer_for", lambda wanted: PEER)
    monkeypatch.setattr(remote_body.peer_links, "LINKS", SimpleNamespace(capabilities=lambda iid: list(caps)))
    members.caps, members.far_row = caps, row
    return members


def test_a_host_without_the_capability_gets_the_update_sentence_and_one_with_it_gets_the_adopt_packet(far):
    with pytest.raises(membership.MembershipRefused, match="studio has to be updated before a session there can join the swarm"):
        asyncio.run(membership.join(SimpleNamespace(), "u-other", confirm_restart=True))
    far.caps.append(capabilities.CAP_SWARM_ADOPT)
    far.live.add(far.far_row)
    agent = asyncio.run(membership.join(SimpleNamespace(), "u-other", confirm_restart=True))
    assert (agent["host_key"], agent["session_row_id"], agent["parent_id"]) == ("studio", far.far_row, far.leader["id"])
    assert far.slept == [] and [w.agent_id for w in far.woke] == [agent["id"]]

    old = remote_body._packet(agent, far.state, PEER.peer_install_id)
    assert "adopt_session_uuid" not in old
    packet = remote_body._packet(agent, far.state, PEER.peer_install_id, adopt=True)
    assert packet["adopt_session_uuid"] == "far-uuid-1"
    assert body_host.BodyPacket(**packet).adopt_session_uuid == "far-uuid-1"


def test_the_host_adopts_its_own_session_as_the_body_with_the_swarm_flags(world, monkeypatch):
    from src.core.pack.machines import config_state, restrictions

    uid = _db(world, lambda c: c.execute("SELECT uid FROM projects WHERE id = ?", (world.orion["id"],)).fetchone()[0])
    row = _row_id(world, "third")
    monkeypatch.setattr(config_state, "default", lambda: SimpleNamespace(restrictions=lambda: None))
    monkeypatch.setattr(restrictions, "enforce", lambda *a, **k: None)
    recreated = []

    async def recreate(request, state_dir, row_id, extra_env=None, argv=None):
        recreated.append((row_id, argv))
        return {"id": "ses_x", "tmux_name": "carnivore_third", "epoch": 1, "session_uuid": "u-third", "working_dir": str(world.folder)}

    monkeypatch.setattr(body_host, "_recreate", recreate)
    packet = body_host.BodyPacket(home_agent_id=41, project_uid=uid, rank="feature", slug="third-member", display_name="third",
                                  job="member: third", effort="medium", harness="claude", adopt_session_uuid="u-third")
    made = asyncio.run(body_host.host(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())), "iid-home", packet))
    assert made["session_uuid"] == "u-third" and recreated[0][0] == row and recreated[0][1][:2] == ["--agent", "third-member"]
    bound = _db(world, lambda c: c.execute("SELECT session_row_id, torn_down_at FROM swarm_remote_bodies WHERE home_agent_id = 41").fetchone())
    assert tuple(bound) == (row, None)
    with pytest.raises(body_host.BodyRefused):
        asyncio.run(body_host.host(SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())), "iid-home",
                                   packet.model_copy(update={"home_agent_id": 42})))


def test_leave_tears_the_host_body_down_and_wakes_the_far_session_plain(far, monkeypatch):
    from src.core.mcp import federated
    from src.core.swarm import body

    far.caps.append(capabilities.CAP_SWARM_ADOPT)
    agent = asyncio.run(membership.join(SimpleNamespace(), "u-other", confirm_restart=True))
    released, forwarded = [], []

    async def release(a):
        released.append(a["id"])

    async def forward(info, method, template, payload=None):
        forwarded.append(template)
        return {}

    async def live_info(app_state, a):
        return SimpleNamespace(activity_status="idle")

    monkeypatch.setattr(remote_body, "release", release)
    monkeypatch.setattr(federated, "forward", forward)
    monkeypatch.setattr(body, "live_info", live_info)
    out = asyncio.run(membership.leave(SimpleNamespace(), "u-other", confirm_restart=True))
    assert out["agent_id"] == agent["id"] and released == [agent["id"]] and forwarded == ["/sessions/{session_uuid}/wake"]
    parked = _db(far, lambda c: store.get_agent(c, agent["id"]))
    assert parked["parked_row_id"] == far.far_row and parked["session_row_id"] is None and far.plain == []
