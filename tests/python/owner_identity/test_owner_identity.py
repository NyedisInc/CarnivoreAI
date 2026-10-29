
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core import ui_preferences
from src.core.owner_identity import identity as owner_identity


@pytest.mark.parametrize(
    ("gecos", "expected"),
    [
        ("Joe Sugamele", "Joe Sugamele"),
        ("Joe Sugamele,,,", "Joe Sugamele"),
        ("  Joe Sugamele ,Room 4", "Joe Sugamele"),
        ("", None),
        (None, None),
        (",,,", None),
        ("   ", None),
        ("bad\x07name", None),
    ],
)
def test_parse_gecos(gecos, expected):
    assert owner_identity.parse_gecos(gecos) == expected


def test_full_name_comes_from_the_password_entry(monkeypatch):
    entry = SimpleNamespace(pw_gecos="Joe Sugamele,,,", pw_name="jsugamele")
    monkeypatch.setattr(owner_identity.pwd, "getpwuid", lambda uid: entry)
    assert owner_identity.os_account_full_name() == "Joe Sugamele"


def test_empty_gecos_falls_back_to_none_never_the_login_name(monkeypatch):
    entry = SimpleNamespace(pw_gecos="", pw_name="jsugamele")
    monkeypatch.setattr(owner_identity.pwd, "getpwuid", lambda uid: entry)
    assert owner_identity.os_account_full_name() is None


def test_a_uid_with_no_entry_is_none(monkeypatch):
    def missing(uid):
        raise KeyError(uid)

    monkeypatch.setattr(owner_identity.pwd, "getpwuid", missing)
    assert owner_identity.os_account_full_name() is None


@pytest.mark.parametrize("bad", ["", "   ", "x" * 61, "a\nb"])
def test_display_name_refuses_bad_values(bad):
    with pytest.raises(ValueError):
        ui_preferences.validate_changes({"owner_display_name": bad})


def test_display_name_is_trimmed_and_clearable():
    assert ui_preferences.validate_changes({"owner_display_name": "  Joe "}) == {"owner_display_name": "Joe"}
    assert ui_preferences.validate_changes({"owner_display_name": None}) == {"owner_display_name": None}


def test_auth_status_names_the_os_owner_and_null_when_unknown(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api import auth_routes
    from src.api.auth import require_auth

    app = FastAPI()
    app.include_router(auth_routes.status_router)
    app.dependency_overrides[require_auth] = lambda: None
    client = TestClient(app)

    monkeypatch.setattr(auth_routes, "os_account_full_name", lambda: "Joe Sugamele")
    body = client.get("/auth/status").json()
    assert body["success"] is True and body["owner_os_name"] == "Joe Sugamele"

    monkeypatch.setattr(auth_routes, "os_account_full_name", lambda: None)
    assert client.get("/auth/status").json()["owner_os_name"] is None
