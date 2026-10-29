
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.api import federation_discovery_routes as routes
from src.core.computers import join_helper, join_job
from src.core.federation import bonjour, discovery

_GOOD_CODE = "123456"


@pytest.fixture
def jobs(monkeypatch):
    state = {"v": "unpaired"}
    monkeypatch.setattr(join_job, "_deps", object())
    monkeypatch.setattr(join_job, "_job", None)
    monkeypatch.setattr(join_job, "_pending", None)
    monkeypatch.setattr(join_job, "_task", None)
    monkeypatch.setattr(join_job, "first_run_state", lambda: state["v"])
    monkeypatch.setattr(join_job, "set_join_running", lambda _v: None)
    return state


@pytest.mark.asyncio
async def test_1_a_look_never_replaces_a_provisional_join(jobs, monkeypatch):
    done = join_job.JoinJob(state="joined", main_label="main")
    monkeypatch.setattr(join_job, "_job", done)
    jobs["v"] = "join_pending"
    assert join_job.start_look(origin="local") is done and join_job.current_job() is done and done.state == "joined"


@pytest.mark.asyncio
async def test_2_a_rejected_join_leaves_a_running_look_alone(jobs):
    look = join_job.start_look(origin="local")
    for code, link, why in (("12", None, "bad_request"), (None, "not-a-link", "bad_link")):
        with pytest.raises(join_job.JoinNotAllowed) as err:
            join_job.start_join(code, link, origin="local", totp_ok=False)
        assert str(err.value.args[0]) == why
    assert look.running and look.state == "waiting_relay" and join_job.current_job() is look
    real = join_job.start_join(_GOOD_CODE, None, origin="local", totp_ok=False)
    assert real is not look and look.error == "superseded"
    join_job.end_waiting(real, "no_relay")


def test_3_two_packs_with_the_same_pn_read_differently():
    a = join_job._candidate({"name": "air", "fid": "aaaaaaaa", "fid_short": "aaaaaa", "pack_name": "Home"})
    b = join_job._candidate({"name": "evil", "fid": "bbbbbbbb", "fid_short": "bbbbbb", "pack_name": "Home"})
    assert a["label"] != b["label"] and a["label"] == "Home aaaaaa"


@pytest.mark.asyncio
async def test_4_the_helper_answer_is_bounded_and_the_peer_table_and_probe_are_capped(monkeypatch):
    sent = {}

    async def relay_failed(job, code, **extra):
        sent.update(extra)
        return {"state": "finding"}

    class Out:
        def step(self, *a, **k): pass
        def final(self, doc): pass

    packs = [{"name": "n" * 500, "fid": "f" * 500, "fid_short": "s" * 500, "pack_name": "p" * 500, "addresses": [("h", 1)]} for _ in range(40)]

    async def targets(status):
        return packs

    monkeypatch.setattr(join_helper, "find_targets", targets)
    monkeypatch.setattr(join_helper, "_relay_failed", relay_failed)
    await join_helper._serve_waiting(Out(), {"job": "j", "mode": "look"})
    cands = sent["candidates"]
    assert len(cands) == 16 and all(len(v) <= 64 for c in cands for v in c.values()) and len(cands[0]["pack_name"]) == 32
    assert len(json.dumps({"op": "relay_fail", "job": "j", "code": "found", "candidates": cands})) < 4096

    d = discovery.Discovery(config_path="/nonexistent/config.json")
    for i in range(discovery.MAX_PEERS + 20):
        txt = bonjour.encode_txt([("p", "1"), ("fid", "f" * 200), ("mid", "m%d" % i), ("lp", "9443")])
        d._on_resolve(0, "n%03d" % i, "h.local.", 22, txt)
    assert len(d._peers) == discovery.MAX_PEERS and all(len(p["fid"]) <= discovery.FID_MAX for p in d._peers.values())

    live = peak = 0

    async def fake_connect(addr, port, timeout, failures):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.01)
        live -= 1
        return True

    monkeypatch.setattr(discovery, "_can_connect", fake_connect)
    cands = [{"name": str(i), "lp": 9000, "addresses": ["203.0.113.%d" % j for j in range(20)]} for i in range(30)]
    got = await discovery.probe_join_ports(cands)
    assert len(got) == 30 and peak <= discovery.PROBE_CONCURRENCY
    one = await discovery.probe_join_ports(cands[:1])
    assert one[0]["join_address"] == "203.0.113.0"


def test_5_the_label_drops_bidi_and_zero_width_characters():
    got = join_job._candidate({"name": "a‮b​c", "fid": "x", "fid_short": "‮12", "pack_name": None})
    assert got["label"] == "abc 12" and all(ord(ch) < 128 for ch in got["label"])


@pytest.mark.asyncio
async def test_6_advertise_and_pack_name_land_in_one_commit(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from src.config import settings
    cfg = tmp_path / "config.json"
    cfg.write_text("{}")
    monkeypatch.setattr(settings, "auth_config_file", str(cfg))
    svc = discovery.Discovery(config_path=cfg)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(federation_discovery=svc)))
    commits = []
    real = discovery.config_writer.commit
    monkeypatch.setattr(discovery.config_writer, "commit", lambda path, mutate: (commits.append(1), real(path, mutate))[1])
    await routes.patch_settings(routes.AdvertiseRequest(advertise=False, pack_name="Home"), request, True)
    assert len(commits) == 1
    block = json.loads(Path(cfg).read_text())["federation"]
    assert block == {"advertise": False, "pack_name": "Home"}
