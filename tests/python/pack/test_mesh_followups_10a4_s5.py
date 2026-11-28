
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

pytest.importorskip("fastapi")

from src.api import pack_machines_routes as routes  # noqa: E402
from src.core.pack.machines import settings_doc  # noqa: E402

LEAK = "LEAK-sentinel-text"


def _bad(**changes):
    with pytest.raises(ValueError) as caught:
        settings_doc.edited(settings_doc.default_doc("iid-a"), changes, "iid-a")
    return caught.value


def test_s5_each_failure_has_its_own_code_and_no_exception_text(monkeypatch):
    assert routes._settings_invalid(_bad(placement_mode="nope")).detail["code"] == "settings_invalid_placement_mode"
    assert routes._settings_invalid(_bad(placement_model={"connection": "", "model": "m"})).detail["code"] == "settings_invalid_placement_model"
    plain = routes._settings_invalid(ValueError(LEAK)).detail
    assert plain["code"] == "settings_invalid" and LEAK not in str(plain)

    raised: list = [ValueError(LEAK)]

    async def fake_edit(wired, changes):
        raise raised[0]

    wired = type("W", (), {"runtime": type("R", (), {"install_id": "iid-a", "settings": staticmethod(lambda: settings_doc.default_doc("iid-a")),
                                                     "kick": staticmethod(lambda: None),
                                                     "held_list": staticmethod(lambda: None)})()})()
    monkeypatch.setattr(routes, "_wired", lambda: wired)
    monkeypatch.setattr(routes, "_edit", fake_edit)
    monkeypatch.setattr(routes.operating, "may_write", lambda own: False)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(routes.put_settings(routes.SettingsBody(auto_distribute=True), None))  # type: ignore[arg-type]
    assert caught.value.status_code == 503 and caught.value.detail["code"] == "settings_unavailable" and LEAK not in str(caught.value.detail)
    raised[0] = _bad(placement_mode="nope")
    with pytest.raises(HTTPException) as caught:
        asyncio.run(routes.put_settings(routes.SettingsBody(auto_distribute=True), None))  # type: ignore[arg-type]
    assert caught.value.status_code == 422 and caught.value.detail["code"] == "settings_invalid_placement_mode"
