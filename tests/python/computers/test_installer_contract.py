
from __future__ import annotations

import ast
import asyncio
import errno
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ic_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ic_logs_"))
os.environ.setdefault("TOTP_SECRET", "JBSWY3DPEHPK3PXP")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-a-real-one-32b")

from src.core import setup_state  # noqa: E402
from src.core.computers import add_over_ssh, add_preview, forget, join_client, join_job, membership  # noqa: E402
from src.core.computers.join_client import JoinFailed, JoinOutcome  # noqa: E402
from src.core.federation import discovery  # noqa: E402
from src.core.pack.machines import settings_doc  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]


def _refuse(code: int):
    async def fake(*_a, **_k):
        raise OSError(code, "refused")

    return fake


def _probe(monkeypatch, code: int):
    monkeypatch.setattr(discovery.asyncio, "open_connection", _refuse(code))
    return asyncio.run(discovery.probe_join_ports([{"name": "a", "addresses": ["192.0.2.13"], "lp": 9000}], timeout=1.0))


@pytest.mark.parametrize("code", [errno.EHOSTUNREACH, errno.ENETUNREACH])
def test_probe_raises_local_network_blocked(monkeypatch, code):
    with pytest.raises(discovery.LocalNetworkBlocked):
        _probe(monkeypatch, code)


def test_probe_refused_port_is_just_no_pack(monkeypatch):
    assert _probe(monkeypatch, errno.ECONNREFUSED) == []


def _run(deps, **kw):
    job = join_job.JoinJob(state="connecting", running=True)
    pend = join_job._Pending(kw.get("code", "123456"), kw.get("parsed"), None, require_grant=False)
    asyncio.run(join_job._run_job(job, deps, "/relay.sock", pend, None))
    return job


def test_helper_reports_a_blocked_lan_as_local_network_blocked(monkeypatch):
    from src.core.computers import join_helper

    sent = []

    async def blocked(_status):
        raise discovery.LocalNetworkBlocked()

    async def door(request):
        sent.append(request)
        return {"state": "failed", "error": request["code"]}

    async def held():
        return {"state": "waiting_relay", "job": "J1"}, None

    monkeypatch.setattr(join_helper, "ask_held", held)
    monkeypatch.setattr(join_helper, "find_targets", blocked)
    monkeypatch.setattr(join_helper, "ask_once", door)
    asyncio.run(join_helper.serve(join_helper.Printer(machine=True, agent=False), first_request=None))
    assert sent[-1] == {"op": "relay_fail", "job": "J1", "code": "local_network_blocked"}


def _link_deps(join):
    async def reserve():
        return 47110

    async def release():
        return None

    return SimpleNamespace(join=join, identity=None, fed_key=None, public_key="", own_iid="me", own_label="x", open_db=None, links=None,
                           pack=None, app_version="", notify=None, reserve_port=reserve, release_port=release, addresses=lambda: ["x.local"])


_PARSED = SimpleNamespace(link_port=9000, hosts=["192.0.2.13", "192.0.2.17"], secret="s", invite_id="i", k="k")


def test_a_wrong_code_reports_tries_left():
    async def wrong(**_kw):
        raise JoinFailed("wrong_code", 2)

    job = _run(_link_deps(wrong), parsed=_PARSED)
    assert job.error == "wrong_code" and job.tries_left == 2 and job.status()["tries_left"] == 2


def test_joined_status_carries_the_main_iid():
    async def ok(**_kw):
        return JoinOutcome("iid-main-0001", "Studio", "new")

    job = _run(_link_deps(ok), parsed=_PARSED)
    assert job.status()["main_iid"] == "iid-main-0001" and job.status()["main_label"] == "Studio"


def test_join_client_maps_a_dead_relay_socket_to_unreachable(monkeypatch):
    monkeypatch.setattr(join_client.asyncio, "open_unix_connection", _refuse(errno.ENOENT))
    with pytest.raises(JoinFailed) as exc:
        asyncio.run(join_client.join(relay_path="/nope.sock", listen_port=47110, listen_addresses=["x.local"], mode="code", code="123456",
                                     identity=None, fed_key=None, public_key="", own_iid="a", own_label="b", open_db=None, links=None, pack=None))
    assert exc.value.code == "unreachable"


def test_main_passes_setup_status_to_the_computers_runtime():
    tree = ast.parse((ROOT / "src" / "main.py").read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "ComputersRuntime"]
    assert calls and all("setup_status" in {k.arg for k in c.keywords} for c in calls)


def test_door_status_documents_the_real_fields():
    from src.core.computers import door

    assert "main_iid" in door.__doc__ and "tries_left" in door.__doc__


def test_add_job_records_the_doors_real_codes():
    assert add_over_ssh._error_code("wrong_code") == "wrong_code"
    assert add_over_ssh._error_code("no_pack") == "no_pack"
    assert add_over_ssh._error_code("zzz") == "remote_error"


def test_preview_probe_reads_the_root_health():
    assert '8000}/health"' in add_preview.PROBE_SCRIPT and "/api/v1/health" not in add_preview.PROBE_SCRIPT


@pytest.mark.parametrize(("held", "want"), [([("SHA256:other", "ED25519")], "changed"), ([("SHA256:fp", "RSA")], "same"), ([], "new")])
def test_known_status_any_key_of_any_type_makes_a_change(monkeypatch, held, want):
    async def lookup(_d):
        return "hosta", ["/k"]

    async def fps(_path, _name=None):
        return held

    monkeypatch.setattr(add_preview, "resolve_lookup", lookup)
    monkeypatch.setattr(add_preview, "fingerprints", fps)
    assert asyncio.run(add_preview.known_status(SimpleNamespace(), "SHA256:fp")) == want


def _state(tmp_path: Path, *, sentinel: bool, tombstone: bool) -> setup_state.SetupState:
    cfg = tmp_path / "config.json"
    cfg.write_text("{}")
    if sentinel:
        (tmp_path / setup_state.PAIRED_SENTINEL_NAME).write_text("")
    if tombstone:
        setup_state.pack_left_path(cfg).write_text("")
    return setup_state.evaluate_setup_state(cfg, "t", "j")


@pytest.mark.parametrize(("sentinel", "tombstone", "want"), [(False, False, "unpaired"), (False, True, "paired"), (True, False, "paired")])
def test_tombstone_keeps_a_left_computer_reading_as_set_up(tmp_path, monkeypatch, sentinel, tombstone, want):
    monkeypatch.setattr(setup_state, "current_setup_state", lambda: _state(tmp_path, sentinel=sentinel, tombstone=tombstone))
    monkeypatch.setattr(membership, "_join_running", False)
    monkeypatch.setattr(membership, "has_provisional_main", lambda: False)
    assert membership.first_run_state() == want


def test_leaving_writes_the_tombstone_and_a_door_join_then_needs_the_owner(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text("{}")
    setup_state.joined_marker_path(cfg).write_text("")
    (tmp_path / setup_state.PAIRED_SENTINEL_NAME).write_text("")
    saved = []
    pack = SimpleNamespace(settings=lambda: settings_doc.default_doc('own-iid-000000000'), mint=lambda changes, base=None: saved.append(changes) or True)
    forget._leave_local(cfg, tmp_path, "own-iid-000000000", pack)
    assert setup_state.pack_left_path(cfg).exists() and not (tmp_path / setup_state.PAIRED_SENTINEL_NAME).exists() and saved
    monkeypatch.setattr(setup_state, "current_setup_state", lambda: setup_state.evaluate_setup_state(cfg, "t", "j"))
    monkeypatch.setattr(membership, "_join_running", False)
    monkeypatch.setattr(membership, "has_provisional_main", lambda: False)
    assert membership.first_run_state() == "paired"


def test_pairing_an_authenticator_again_clears_the_tombstone(tmp_path, monkeypatch):
    from src.api import auth_routes

    sentinel = tmp_path / setup_state.PAIRED_SENTINEL_NAME
    tomb = tmp_path / setup_state.PACK_LEFT_NAME
    tomb.write_text("")
    monkeypatch.setattr(auth_routes, "_totp_paired_sentinel_path", lambda: sentinel)
    auth_routes._totp_seen_cache.clear()
    async def accept(_code):
        return None

    monkeypatch.setattr(auth_routes, "check_totp_code", accept)
    monkeypatch.setattr(auth_routes, "create_access_token", lambda: ("a", 60))
    monkeypatch.setattr(auth_routes, "create_refresh_token", lambda: ("r", "jti", 0))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    asyncio.run(auth_routes.redeem_totp_code(request, "123456"))
    assert sentinel.exists() and not tomb.exists()
