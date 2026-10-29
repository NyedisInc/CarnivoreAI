
from __future__ import annotations

from tests.python.federation.test_peer_forward import world  # noqa: F401
from tests.test_project_create_route import _post


def test_an_ssh_root_reaches_the_manager_as_host_and_far_folder() -> None:
    response, manager = _post({"working_dir": "ssh://studio/home/alex/api", "auto_start_claude": True})
    assert response.status_code == 201, response.text
    assert manager.calls[0]["host_key"] == "studio"
    assert manager.calls[0]["working_dir"] == "/home/alex/api"


def test_a_root_naming_another_computer_than_host_key_is_a_400(world) -> None:  # noqa: F811
    response = world.http.post("/api/v1/sessions", json={"host_key": "odin", "working_dir": "ssh://studio/home/alex/api"})
    assert response.status_code == 400, response.text
    assert "does not match" in response.text
