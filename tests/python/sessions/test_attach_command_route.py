
from __future__ import annotations

import json
import os
import tempfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_attach_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_attach_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.api import remote_route_guard, session_attach_command_routes as routes  # noqa: E402
from src.core.mcp import tools  # noqa: E402
from src.core.mcp.caller import AgentCaller  # noqa: E402
from tests.socket_guard import TEST_SOCKET_NAME  # noqa: E402

TMUX = "/opt/test/bin/tmux"
NASTY = "a b'c\"d$e`f;g\nh=i|j&k(l)"
REMOTE_BACKEND_ID = "ses_on_far_host"


class FakeManager:

    def __init__(self, rows: dict) -> None:
        self.rows = rows
        self._registry = SimpleNamespace(backends={REMOTE_BACKEND_ID: SimpleNamespace(host_key="peer-far", tmux_session="far")})

    async def get_session_info(self, session_id: str):
        name = self.rows.get(session_id, "__missing__")
        if name == "__missing__":
            return None
        return SimpleNamespace(session=SimpleNamespace(id=session_id), tmux_session=name, host_key="local")

    def tmux_socket_name(self) -> str:
        return TEST_SOCKET_NAME


@pytest.fixture
def manager(monkeypatch) -> FakeManager:
    monkeypatch.setattr("src.api.session_attach_command_routes.tmux_argv_prefix",
                        lambda socket: [TMUX, "-L", socket])
    monkeypatch.setattr(remote_route_guard, "is_remote_backend", lambda backend: backend is not None)
    return FakeManager({
        "ses_created": "carnivore_made",
        "adopted:outside": "someone_elses_tmux",
        "ses_nasty": NASTY,
        "ses_asleep": None,
        "ses_toolong": "x" * 201,
    })


def _request(manager: FakeManager) -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session_manager=manager)))


def _expected(name: str, *flags: str) -> list:
    return [TMUX, "-L", TEST_SOCKET_NAME, "attach-session", *(flags or ("-f", "ignore-size")), "-t", "=" + name]


@pytest.mark.asyncio
async def test_created_and_adopted_ids_answer_their_stored_tmux_name(manager):
    created = await routes.get_session_attach_command(_request(manager), "ses_created")
    adopted = await routes.get_session_attach_command(_request(manager), "adopted:outside")
    assert created.argv == _expected("carnivore_made") and created.tmux_session == "carnivore_made"
    assert adopted.argv == _expected("someone_elses_tmux")
    assert created.socket == TEST_SOCKET_NAME


@pytest.mark.asyncio
async def test_a_name_full_of_metacharacters_is_one_element_and_nothing_is_joined(manager):
    answer = await routes.get_session_attach_command(_request(manager), "ses_nasty")
    assert answer.argv == _expected(NASTY) and answer.argv[-1] == "=" + NASTY
    assert len(answer.argv) == 8 and all(isinstance(part, str) for part in answer.argv)


@pytest.mark.asyncio
async def test_read_only_swaps_the_flags_for_dash_r(manager):
    answer = await routes.get_session_attach_command(_request(manager), "ses_created", read_only=True)
    assert answer.argv == _expected("carnivore_made", "-r") and answer.read_only is True


@pytest.mark.asyncio
@pytest.mark.parametrize("session_id", ["remote:peer-abc:carnivore_far", REMOTE_BACKEND_ID])
async def test_remote_sessions_answer_409_remote_host(manager, session_id):
    with pytest.raises(HTTPException) as caught:
        await routes.get_session_attach_command(_request(manager), session_id)
    assert caught.value.status_code == 409 and caught.value.detail["code"] == "remote_host"


@pytest.mark.asyncio
@pytest.mark.parametrize("session_id", ["ses_asleep", "ses_toolong"])
async def test_a_row_with_no_usable_tmux_name_answers_409(manager, session_id):
    with pytest.raises(HTTPException) as caught:
        await routes.get_session_attach_command(_request(manager), session_id)
    assert caught.value.status_code == 409 and caught.value.detail["code"] == "no_tmux_session"


@pytest.mark.asyncio
async def test_an_unknown_id_is_404(manager):
    with pytest.raises(HTTPException) as caught:
        await routes.get_session_attach_command(_request(manager), "ses_nope")
    assert caught.value.status_code == 404


@pytest.mark.asyncio
async def test_the_mcp_adapter_returns_the_same_argv_and_refuses_a_remote_id(manager, monkeypatch):
    infos = [SimpleNamespace(session=SimpleNamespace(id="ses_nasty"), tmux_session=NASTY, host_key="local"),
             SimpleNamespace(session=SimpleNamespace(id="remote:peer-abc:carnivore_far"),
                             tmux_session="carnivore_far", host_key="peer-abc")]

    async def listing(_manager):
        return infos

    monkeypatch.setattr("src.core.mcp.common._all_infos", listing)
    monkeypatch.setattr("src.core.mcp.write_tools._request", _request)
    caller = AgentCaller("ses_test", "cloude_test", "ses_test")
    assert tools.has_tool("session_attach_command")
    res = await tools.call_tool(manager, caller, "session_attach_command", {"target": "ses_nasty"})
    assert "isError" not in res, res
    assert json.loads(res["content"][0]["text"])["argv"] == _expected(NASTY)
    refused = await tools.call_tool(manager, caller, "session_attach_command", {"target": "remote:peer-abc:carnivore_far"})
    assert refused["isError"] is True
