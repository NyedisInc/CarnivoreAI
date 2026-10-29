
from __future__ import annotations

import asyncio
import json
import shlex
import subprocess
import types

import pytest

from tests.python.computers.test_join_doors import _deps, _door, env, relay_join  # noqa: F401
from tests.python.computers.test_join_commit import world  # noqa: F401

from src.core.computers import add_over_ssh, add_preview, join_job, runtime, store
from src.core.federation import bonjour
from src.core.federation.discovery import Discovery



def _disc(tmp_path, name, fid_provider, uuid):
    return Discovery(config_path=tmp_path / "c.json", fid_provider=fid_provider, platform_uuid_provider=lambda: uuid,
                     name_provider=lambda: name, link_port_provider=lambda: 47110)


def _heard_by(tmp_path, main_disc):
    joiner = _disc(tmp_path, "studio", lambda: None, "uuid-joiner")
    joiner._on_resolve(0, "air", "air.local.", 47111, bonjour.encode_txt(main_disc.txt_pairs()))
    return joiner


@pytest.mark.asyncio
async def test_auto_picked_join_passes_expect_fid_from_main_own_txt(env, tmp_path, monkeypatch):  # noqa: F811
    main, join, srv, invites = env
    monkeypatch.setattr(runtime, "_ACTIVE", types.SimpleNamespace(fed_key=main.key, advertised_port=lambda: 47110))
    main_disc = _disc(tmp_path, "air", lambda: runtime.advertised_fid() or "stale-boot-fid", "uuid-main")
    assert dict(main_disc.txt_pairs())["fid"] == main.key.device_id
    joiner = _heard_by(tmp_path, main_disc)
    cand = joiner.candidates()[0]
    assert cand["fid"] == main.key.device_id and cand["fid_short"] == main.key.device_id[:6]
    inv = invites.mint("code")
    await srv.sync()
    await _deps(main, join, srv)
    door = await _door(tmp_path)
    try:
        mains = [{"name": cand["name"], "fid": cand["fid"], "fid_short": cand["fid_short"], "addresses": [("127.0.0.1", srv.port)]}]
        lines = await relay_join(door, srv, main, monkeypatch, {"op": "join", "code": inv.code}, mains=mains)
        assert lines[-1]["state"] == "joined" and lines[-1]["error"] is None
    finally:
        await door.stop()
        await srv.stop()


def test_advertised_fid_follows_a_key_that_changed_after_boot(tmp_path, monkeypatch):
    rt = types.SimpleNamespace(fed_key=types.SimpleNamespace(device_id="firstfid"), advertised_port=lambda: None)
    monkeypatch.setattr(runtime, "_ACTIVE", rt)
    disc = _disc(tmp_path, "air", lambda: runtime.advertised_fid() or "boot", "u")
    assert dict(disc.txt_pairs())["fid"] == "firstfid"
    rt.fed_key = types.SimpleNamespace(device_id="rotatedfid")
    assert dict(disc.txt_pairs())["fid"] == "rotatedfid"
    disc.refresh_fid("firstfid")
    assert dict(disc.txt_pairs())["fid"] == "rotatedfid"
    monkeypatch.setattr(runtime, "_ACTIVE", None)
    assert runtime.advertised_fid() is None and dict(disc.txt_pairs())["fid"] == "boot"


@pytest.mark.asyncio
async def test_a_job_without_a_relay_ends_no_relay_and_a_helper_failure_ends_it_with_its_code(env, monkeypatch):
    main, join, srv, _invites = env
    await _deps(main, join, srv)
    monkeypatch.setattr(join_job, "RELAY_WAIT_SECONDS", 0.05)
    job = join_job.start_join("123456", None, origin="local", totp_ok=True)
    assert job.state == "waiting_relay" and join_job.relay_request() == {"job": job.id, "mode": "code", "candidate_fid": None, "targets": []}
    await asyncio.sleep(0.2)
    assert (job.state, job.error, job.running) == ("failed", "no_relay", False) and join_job.relay_request() is None
    monkeypatch.setattr(join_job, "RELAY_WAIT_SECONDS", 60.0)
    job = join_job.start_join("123456", None, origin="local", totp_ok=True)
    join_job.fail_relay("no_pack")
    assert (job.state, job.error, job.running) == ("failed", "no_pack", False)
    job = join_job.start_join("123456", None, origin="local", totp_ok=True)
    join_job.fail_relay("several", [{"name": "a", "fid": "f1", "fid_short": "f1", "addresses": ["10.0.0.5"]}])
    assert (job.state, job.error, job.running) == ("finding", None, False) and job.candidates == [{"name": "a", "fid": "f1", "fid_short": "f1", "pack_name": None, "label": "a f1"}]
    with pytest.raises(join_job.JoinNotAllowed):
        join_job.fail_relay("no_pack")


def test_override_script_is_what_the_preview_checks(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"computers": {"installer_override": {"script": "/tmp/rc/install.sh", "dmg": "/tmp/c.dmg", "sha256": "a" * 64}}}))
    over = add_over_ssh.installer_override(cfg)
    assert over is not None and over["script"] == "/tmp/rc/install.sh"
    script = add_preview.probe_script(over["script"])
    assert "carnivore.ai/install.sh" not in script and "grep -c '^INSTALLER_PROTOCOL=2$' /tmp/rc/install.sh" in script
    assert "carnivore.ai/install.sh" in add_preview.probe_script(None)
    rc = tmp_path / "install.sh"
    rc.write_text("INSTALLER_PROTOCOL=2\n")
    last = add_preview.probe_script(str(rc)).strip().splitlines()[-1]
    out = subprocess.run(["/bin/sh", "-c", last], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "installer_protocol=1"
    cfg.write_text(json.dumps({"computers": {"installer_override": {"script": "/tmp/i.sh; rm", "dmg": "/tmp/c.dmg", "sha256": "a" * 64}}}))
    assert add_over_ssh.installer_override(cfg) is None
