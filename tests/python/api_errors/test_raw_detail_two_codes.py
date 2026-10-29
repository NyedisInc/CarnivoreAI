
from __future__ import annotations

from src.core import config_files_create
from src.core.hosts.identity import RemoteRootConflict

from .conftest import LEAK, assert_fixed


def test_config_file_create_confirmation_keeps_the_acknowledge_key_and_hides_the_text(driver, monkeypatch):
    def gated(**_k):
        raise config_files_create.ConfirmationRequiredError(f"{LEAK} needs a yes", "executable")

    monkeypatch.setattr(config_files_create, "create_file", gated)
    response, events = driver.call("POST", "/config-files/create", None, json={"root": "user", "path": "a.sh", "content": "x"})
    detail = assert_fixed(response, 400, "confirmation_required", events)
    assert detail["acknowledge"] == "executable"
    assert "message" not in detail


def test_create_session_remote_root_conflict_answers_a_code_without_the_text(driver, monkeypatch):
    from src.api import session_crud_routes

    def conflict(*_a, **_k):
        raise RemoteRootConflict(f"host_key {LEAK!r} does not match")

    monkeypatch.setattr(session_crud_routes, "resolve_create_target", conflict)
    response, events = driver.call("POST", "/sessions", object(), json={})
    assert_fixed(response, 400, "remote_root_conflict", events)
