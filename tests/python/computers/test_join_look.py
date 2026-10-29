
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api import federation_discovery_routes as routes
from src.config import settings
from src.core.computers import join_helper, join_job
from src.core.federation import bonjour, discovery
from tests.python.computers.test_join_commit import world  # noqa: F401
from tests.python.computers.test_join_doors import _ask, _deps, _door, env  # noqa: F401


def test_pn_only_with_a_name_and_a_link_port_and_sanitized():
    assert ("pn", "Home Pack") in discovery.build_txt_pairs("f", None, 9443, "Home Pack")
    assert all(k != "pn" for k, _ in discovery.build_txt_pairs("f", None, 9443, None))
    assert all(k != "pn" for k, _ in discovery.build_txt_pairs("f", None, None, "Home Pack"))
    assert dict(discovery.build_txt_pairs("f", None, 9443, "<b>x</b>"))["pn"] == "bxb"
    assert all(k != "pn" for k, _ in discovery.build_txt_pairs("f", None, 9443, "<>"))


def test_hostile_pn_is_cleaned_on_read():
    assert discovery.sanitize_pack_name("  a\n\tb  <script>") == "a b script"
    assert discovery.sanitize_pack_name("x" * 100) == "x" * 32
    assert discovery.sanitize_pack_name("‮\u0000") is None and discovery.sanitize_pack_name(7) is None
    d = discovery.Discovery(config_path="/nonexistent/config.json")
    txt = bonjour.encode_txt([("p", "1"), ("fid", "abcdef123"), ("mid", "m"), ("lp", "9443"), ("pn", "Evil\n<img>")])
    d._on_resolve(0, "air", "air.local.", 22, txt)
    d._peers["air"]["addresses"] = ["192.0.2.13"]
    assert d.candidates()[0]["pack_name"] == "Evil img"


def test_label_is_the_pack_name_else_name_and_fid_short():
    assert join_job._candidate({"name": "air", "fid": "abcdef123", "fid_short": "abcdef", "pack_name": "Home"})["label"] == "Home abcdef"
    got = join_job._candidate({"name": "air", "fid": "abcdef123", "fid_short": "abcdef", "pack_name": "<>"})
    assert got == {"name": "air", "fid": "abcdef123", "fid_short": "abcdef", "pack_name": None, "label": "air abcdef"}


@pytest.mark.asyncio
async def test_patch_pack_name_validates_persists_and_clears(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text("{}")
    monkeypatch.setattr(settings, "auth_config_file", str(cfg))
    svc = discovery.Discovery(config_path=cfg)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(federation_discovery=svc)))
    patch = lambda **kw: routes.patch_settings(routes.AdvertiseRequest(**kw), request, True)  # noqa: E731
    for bad in ("x" * 33, "a<b", "a  b"):
        with pytest.raises(HTTPException) as err:
            await patch(pack_name=bad)
        assert err.value.status_code == 422 and err.value.detail["code"] == "bad_pack_name"
    assert (await patch(pack_name=" Home ")) ["pack_name"] == "Home"
    assert json.loads(cfg.read_text())["federation"]["pack_name"] == "Home"
    assert (await routes.get_settings(request, True))["pack_name"] == "Home"
    assert (await patch(pack_name=None))["pack_name"] is None
    assert "pack_name" not in json.loads(cfg.read_text())["federation"]


@pytest.mark.asyncio
async def test_a_look_ends_finding_with_candidates_and_never_blocks_a_join(env, tmp_path, monkeypatch):
    main, join, srv, invites = env
    spake = []

    async def never(**kw):
        spake.append(kw)
        raise AssertionError("a look must not start SPAKE2")

    deps = await _deps(main, join, srv, join=never)
    door = await _door(tmp_path)
    packs = [{"name": "air", "fid": "abcdef123456", "fid_short": "abcdef", "pack_name": "Home Pack", "addresses": [("127.0.0.1", 1)]},
             {"name": "hosta", "fid": "123456abcdef", "fid_short": "123456", "pack_name": None, "addresses": [("127.0.0.1", 1)]}]
    seen = {}

    async def targets(status):
        seen.update(status)
        return packs

    monkeypatch.setattr(join_helper, "door_path", lambda: door.path)
    monkeypatch.setattr(join_helper, "find_targets", targets)
    job = join_job.start_look(origin="local")
    assert job.state == "waiting_relay" and join_job.relay_request()["mode"] == "look"
    assert join_job.start_look(origin="local") is job
    await asyncio.to_thread(join_helper.main, ["--attach"])
    assert seen["mode"] == "look" and seen["candidate_fid"] is None
    status = join_job.current_job().status()
    assert status["state"] == "finding" and status["error"] is None
    assert status["candidates"] == [
        {"name": "air", "fid": "abcdef123456", "fid_short": "abcdef", "pack_name": "Home Pack", "label": "Home Pack abcdef"},
        {"name": "hosta", "fid": "123456abcdef", "fid_short": "123456", "pack_name": None, "label": "hosta 123456"}]
    assert join_job.candidate_view() == status["candidates"] and not spake

    nobody = join_job.start_look(origin="local")
    assert nobody is not job
    real = join_job.start_join("123456", None, origin="local", totp_ok=False)
    assert real is not nobody and real.state == "waiting_relay" and nobody.error == "superseded" and not spake
    with pytest.raises(join_job.JoinNotAllowed):
        await join_job.attach_relay("/x", "h", None, nobody.id)
    join_job.end_waiting(real, "no_relay")
    await door.stop()


@pytest.mark.asyncio
async def test_a_look_with_nobody_answering_fails_no_pack(env, tmp_path, monkeypatch):
    main, join, srv, invites = env
    await _deps(main, join, srv)
    door = await _door(tmp_path)

    async def targets(_status):
        return []

    monkeypatch.setattr(join_helper, "door_path", lambda: door.path)
    monkeypatch.setattr(join_helper, "find_targets", targets)
    join_job.start_look(origin="settings")
    await asyncio.to_thread(join_helper.main, ["--attach"])
    assert join_job.current_job().status()["state"] == "failed" and join_job.current_job().error == "no_pack"
    await door.stop()
