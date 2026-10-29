
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from src.api import account_gates, phone_link_routes, spectator_routes
from src.api.auth import require_auth
from src.config.relay import RelayConfig
from src.core.catalog import catalog_auth
from src.core.phone_link.manager import PhoneLinkManager


class _Manager(PhoneLinkManager):
    async def _start(self):
        pass

    async def _stop(self):
        pass


def _app(tmp_path):
    app = FastAPI()
    app.add_exception_handler(account_gates.AccountRequired, account_gates.account_required_handler)
    app.include_router(phone_link_routes.router, prefix="/api/v1")
    app.include_router(spectator_routes.router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: True
    app.state.services = SimpleNamespace(
        settings_reader=SimpleNamespace(state_dir=lambda: tmp_path),
        catalog=SimpleNamespace(api_base_url=lambda: "http://hosted.invalid"),
    )
    app.state.phone_link = _Manager(app=None, config=RelayConfig(), state_dir=tmp_path,
                                    db_path=tmp_path / "c.db", version="1.0.0")
    return app


def _sign_in(tmp_path):
    catalog_auth.save_session(tmp_path, {
        "login": "x", "access_token": "a", "refresh_token": "r",
        "expires_in": 3600, "refresh_expires_in": 86400}, "google")


@pytest.fixture
def client(tmp_path):
    app = _app(tmp_path)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
async def test_signed_out_pairing_window_is_refused_but_status_is_open(client):
    async with client as c:
        r = await c.post("/api/v1/phone-link/pairing-window")
        assert r.status_code == 403
        assert r.json() == {"code": "account_required", "feature": "phone_pairing",
                            "detail": "sign in with a carnivore account to use this"}
        assert (await c.get("/api/v1/phone-link")).status_code == 200
        on = await c.put("/api/v1/phone-link", json={"enabled": True})
        assert on.status_code == 403 and on.json()["feature"] == "phone_link"
        assert (await c.put("/api/v1/phone-link", json={"enabled": False})).status_code == 200
        mint = await c.post("/api/v1/sessions/ses_1/spectator-links", json={})
        assert mint.status_code == 403 and mint.json()["feature"] == "share_link"


@pytest.mark.asyncio
async def test_signed_in_the_mint_passes_the_gate(tmp_path):
    _sign_in(tmp_path)
    app = _app(tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/sessions/ses_1/spectator-links", json={})
        assert r.status_code != 403 or r.json().get("code") != "account_required"
        assert (await c.post("/api/v1/phone-link/pairing-window")).status_code == 409


def test_gate_ids_come_from_the_shared_file():
    assert {"share_link", "phone_link", "phone_pairing"} == set(account_gates.SERVER_ENFORCED)
    assert "rate" in account_gates.GATES


def test_gate_json_ships_under_src():
    from pathlib import Path

    src_root = Path(account_gates.__file__).resolve().parents[1]
    assert account_gates.GATES_PATH.is_file()
    assert account_gates.GATES_PATH.resolve().is_relative_to(src_root)
