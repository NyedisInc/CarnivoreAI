
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_osr_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_osr_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import one_shot_routes
from src.api.auth import require_auth
from src.core.session_one_shot_gate import MAX_BODY_BYTES, PANE_DIALOG_OPEN
from src.core.session_startup_gate import GATE_AWAITING, GATE_READY, GATE_UNKNOWN
from src.core.session_status import STATUS_FINISHED_UNREAD, STATUS_IDLE, STATUS_NOTICE, STATUS_QUESTION, STATUS_UNKNOWN, STATUS_WORKING
from src.core.tmux_listing import TmuxListing
from src.core.tmux_one_shot import PasteNotSettledError
from src.models import Session, SessionInfo

TMUX_NAME = "cloude_one_shot_demo"
CREATED_ID = "ses_one_shot"
ADOPTED_ID = f"adopted:{TMUX_NAME}"

CODEX_PANE_COMMAND = "node"
SHELL_PANE_COMMAND = "zsh"


class FakeBackend:

    def __init__(
        self,
        *,
        pane_command: Optional[str] = CODEX_PANE_COMMAND,
        pane_dead: Optional[str] = "0",
        listing_ok: bool = True,
        raises: Optional[Exception] = None,
    ) -> None:
        self.tmux_session = TMUX_NAME
        self._pane_command = pane_command
        self._pane_dead = pane_dead
        self._listing_ok = listing_ok
        self._raises = raises
        self.pastes: List[str] = []
        self.listings = 0

    def list_pane_status_all(self) -> TmuxListing:
        self.listings += 1
        if not self._listing_ok:
            return TmuxListing(ok=False, reason="no_server")
        return TmuxListing.answered(
            [
                {
                    "name": TMUX_NAME,
                    "pane_dead": self._pane_dead,
                    "pane_current_command": self._pane_command,
                    "pid": 4321,
                    "status": "running",
                    "created_at_epoch": 1755000000,
                }
            ]
        )

    async def paste_and_submit(self, text: str, gate: Any = None) -> None:
        if gate is not None:
            await gate()
        if self._raises is not None:
            raise self._raises
        self.pastes.append(text)


class FakeRegistry:

    def __init__(self, sessions: Dict[str, Any], backends: Dict[str, Any]) -> None:
        self._sessions = sessions
        self._backends = backends

    def get_session(self, session_id: str) -> Optional[Any]:
        return self._sessions.get(session_id)

    def get_backend(self, session_id: str) -> Optional[Any]:
        return self._backends.get(session_id)


class FakeInfo:

    def __init__(
        self, activity_status: Optional[str], startup_gate: Optional[str],
        agent_type: Optional[str] = "codex", agent_family: Optional[str] = "codex",
    ) -> None:
        self.activity_status = activity_status
        self.startup_gate = startup_gate
        self.agent_type = agent_type
        self.agent_family = agent_family
        self.claude_session_uuid: Optional[str] = None


class FakeManager:

    def __init__(
        self, info: Optional[FakeInfo], later: Optional[FakeInfo] = None
    ) -> None:
        self._info = info
        self._later = later
        self.info_calls = 0

    async def get_session_info(
        self, session_id: Optional[str] = None
    ) -> Optional[FakeInfo]:
        self.info_calls += 1
        if self._later is not None and self.info_calls > 1:
            return self._later
        return self._info


def _session(session_id: str, *, agent_type: Optional[str] = "codex") -> Session:
    return Session(
        id=session_id,
        working_dir=str(Path(tempfile.gettempdir())),
        tmux_session=TMUX_NAME,
        agent_type=agent_type,
    )


def _client(
    *,
    session_id: str = CREATED_ID,
    backend: Optional[FakeBackend] = None,
    agent_type: Optional[str] = "codex",
    memory_agent_type: Any = "same",
    activity_status: Optional[str] = STATUS_IDLE,
    startup_gate: Optional[str] = GATE_READY,
    info: Optional[FakeInfo] = None,
    no_info: bool = False,
    register_backend: bool = True,
    later_info: Optional[FakeInfo] = None,
) -> tuple:
    backend = backend or FakeBackend()
    app = FastAPI()
    app.include_router(one_shot_routes.router)
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}

    class _Services:
        registry = FakeRegistry(
            {session_id: _session(
                session_id, agent_type=agent_type if memory_agent_type == "same" else memory_agent_type)},
            {session_id: backend} if register_backend else {},
        )

    if no_info:
        resolved = None
    else:
        resolved = info or FakeInfo(activity_status, startup_gate, agent_type)

    app.state.services = _Services()
    app.state.session_manager = FakeManager(resolved, later_info)
    return TestClient(app), backend


def _post(client: TestClient, text: str, session_id: str = CREATED_ID):
    return client.post(f"/sessions/{session_id}/skills/one-shot", json={"text": text})




def test_a_live_agent_pane_accepts_the_body_and_reports_what_it_did() -> None:
    client, backend = _client()
    response = _post(client, "summarise this repo")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "pasted_bytes": len("summarise this repo"),
        "stripped_count": 0,
        "submitted": True,
    }
    assert backend.pastes == ["summarise this repo"]


def test_idle_only_refuses_a_working_pane_before_paste() -> None:
    client, backend = _client(activity_status=STATUS_WORKING)
    response = client.post(
        f"/sessions/{CREATED_ID}/skills/one-shot",
        json={"text": "hello", "idle_only": True},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == PANE_DIALOG_OPEN
    assert backend.pastes == []


def test_idle_only_accepts_finished_unread_and_still_refuses_notice() -> None:
    client, backend = _client(activity_status=STATUS_FINISHED_UNREAD)
    assert client.post(f"/sessions/{CREATED_ID}/skills/one-shot", json={"text": "hi", "idle_only": True}).status_code == 200
    assert backend.pastes == ["hi"]
    client, backend = _client(activity_status=STATUS_NOTICE)
    response = client.post(f"/sessions/{CREATED_ID}/skills/one-shot", json={"text": "hi", "idle_only": True})
    assert response.status_code == 409 and response.json()["detail"]["code"] == PANE_DIALOG_OPEN
    assert backend.pastes == []


def test_a_gate_that_turns_false_before_the_locked_paste_stops_the_paste() -> None:
    client, backend = _client(later_info=FakeInfo(STATUS_QUESTION, GATE_READY))
    response = _post(client, "summarise this repo")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "pane_dialog_open"
    assert backend.pastes == []


def test_the_body_handed_to_the_backend_carries_no_trailing_newline() -> None:
    client, backend = _client()
    assert _post(client, "line one\nline two").status_code == 200
    assert backend.pastes == ["line one\nline two"]
    assert not backend.pastes[0].endswith("\n")


def test_stripped_control_characters_are_counted_in_the_response() -> None:
    client, backend = _client()
    response = _post(client, "keep\x00this\x07clean")
    assert response.status_code == 200
    assert response.json()["stripped_count"] == 2
    assert response.json()["pasted_bytes"] == len("keepthisclean")
    assert backend.pastes == ["keepthisclean"]


def test_an_adopted_session_id_works_exactly_like_a_created_one() -> None:
    client, backend = _client(session_id=ADOPTED_ID)
    response = _post(client, "hello", session_id=ADOPTED_ID)
    assert response.status_code == 200, response.text
    assert backend.pastes == ["hello"]


def test_a_claude_pane_reporting_its_version_string_is_accepted() -> None:
    client, backend = _client(backend=FakeBackend(pane_command="2.1.266"))
    assert _post(client, "hello").status_code == 200
    assert backend.pastes == ["hello"]




def test_a_shell_pane_answers_pane_not_an_agent_and_pastes_nothing() -> None:
    client, backend = _client(backend=FakeBackend(pane_command=SHELL_PANE_COMMAND))
    response = _post(client, "rm -rf something")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "pane_not_an_agent"
    assert backend.pastes == []


def test_a_dead_pane_answers_pane_not_an_agent() -> None:
    client, backend = _client(backend=FakeBackend(pane_dead="1"))
    response = _post(client, "hello")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "pane_not_an_agent"
    assert backend.pastes == []


def test_a_listing_that_could_not_run_answers_pane_not_an_agent() -> None:
    client, backend = _client(backend=FakeBackend(listing_ok=False))
    response = _post(client, "hello")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "pane_not_an_agent"
    assert backend.pastes == []


def test_no_agent_record_on_the_row_answers_pane_not_an_agent() -> None:
    client, backend = _client(agent_type=None)
    response = _post(client, "hello")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "pane_not_an_agent"
    assert backend.pastes == []


def test_an_adopted_row_with_a_recorded_launch_passes_without_a_fingerprint(monkeypatch) -> None:
    monkeypatch.setattr(one_shot_routes, "registered_agent_in_foreground", lambda **_: False)
    client, backend = _client(agent_type="claude-chrome", memory_agent_type=None)
    response = _post(client, "hello")
    assert response.status_code == 200, response.text
    assert backend.pastes == ["hello"]


def test_no_record_anywhere_but_a_proven_foreground_claude_passes(monkeypatch) -> None:
    seen: Dict[str, Any] = {}

    def proof(**kwargs: Any) -> bool:
        seen.update(kwargs)
        return True

    monkeypatch.setattr(one_shot_routes, "registered_agent_in_foreground", proof)
    client, backend = _client(agent_type=None)
    response = _post(client, "hello")
    assert response.status_code == 200, response.text
    assert seen["claude_session_uuid"] is None
    assert backend.pastes == ["hello"]


def test_no_record_and_no_proof_still_refuses(monkeypatch) -> None:
    monkeypatch.setattr(one_shot_routes, "registered_agent_in_foreground", lambda **_: False)
    client, backend = _client(agent_type=None)
    response = _post(client, "hello")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "pane_not_an_agent"
    assert backend.pastes == []


def test_a_session_waiting_on_the_user_answers_pane_dialog_open() -> None:
    client, backend = _client(activity_status=STATUS_QUESTION)
    response = _post(client, "hello")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "pane_dialog_open"
    assert STATUS_QUESTION in response.json()["detail"]["message"]
    assert backend.pastes == []


def _screen(monkeypatch, verdict: str) -> None:
    from src.core.approvals import dialog_gate

    async def fake(app, session_id, *, capture=None):
        return verdict

    monkeypatch.setattr(dialog_gate, "dialog_verdict", fake)


def test_an_unknown_status_is_not_reported_as_a_dialog_when_the_screen_shows_none(monkeypatch) -> None:
    _screen(monkeypatch, "clear")
    client, backend = _client(activity_status=STATUS_UNKNOWN)
    assert _post(client, "hello").status_code == 200
    assert backend.pastes == ["hello"]
    for verdict, code in (("open", "pane_dialog_open"), ("unreadable", "dialog_unreadable")):
        _screen(monkeypatch, verdict)
        client, backend = _client(activity_status=STATUS_UNKNOWN)
        response = _post(client, "hello")
        assert (response.status_code, response.json()["detail"]["code"]) == (409, code)
        assert backend.pastes == []


def test_a_status_that_is_not_unknown_and_not_confirmed_keeps_its_refusal_whatever_the_screen_shows(monkeypatch) -> None:
    _screen(monkeypatch, "clear")
    client, backend = _client(activity_status="dead")
    assert _post(client, "hello").json()["detail"]["code"] == "pane_dialog_open"
    client, backend = _client(info=FakeInfo(STATUS_UNKNOWN, GATE_READY, "codex", agent_family="gemini"))
    assert _post(client, "hello").json()["detail"]["code"] == "pane_dialog_open"
    assert backend.pastes == []


def test_a_session_the_manager_cannot_resolve_answers_pane_dialog_open() -> None:
    client, backend = _client(no_info=True)
    response = _post(client, "hello")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "pane_dialog_open"
    assert backend.pastes == []


def test_the_dialog_rung_reads_the_state_live_on_every_request() -> None:
    client, _ = _client()
    manager = client.app.state.session_manager
    _post(client, "hello")
    _post(client, "hello again")
    assert manager.info_calls == 6




def test_a_session_parked_on_its_folder_trust_prompt_is_refused() -> None:
    client, backend = _client(startup_gate=GATE_AWAITING)
    response = _post(client, "trust this folder")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "pane_dialog_open"
    assert GATE_AWAITING in response.json()["detail"]["message"]
    assert backend.pastes == []


def test_a_startup_gate_that_could_not_be_determined_is_refused() -> None:
    client, backend = _client(startup_gate=GATE_UNKNOWN)
    response = _post(client, "hello")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "pane_dialog_open"
    assert backend.pastes == []


def test_the_two_live_signals_are_wrapper_fields_not_session_fields() -> None:
    assert "activity_status" in SessionInfo.model_fields
    assert "startup_gate" in SessionInfo.model_fields
    assert "agent_type" in SessionInfo.model_fields




def test_an_escape_byte_is_refused_before_the_pane_is_even_read() -> None:
    client, backend = _client()
    response = _post(client, "danger\x1b[2J")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "body_has_escape"
    assert backend.pastes == []
    assert backend.listings == 0


def test_an_empty_body_is_refused() -> None:
    client, backend = _client()
    response = _post(client, "   ")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "body_empty"
    assert backend.pastes == []


def test_a_lone_surrogate_body_is_a_409_and_never_a_500() -> None:
    client, backend = _client()
    response = client.post(
        f"/sessions/{CREATED_ID}/skills/one-shot",
        content=b'{"text": "hello \\ud800 world"}',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "body_not_utf8"
    assert backend.pastes == []
    assert backend.listings == 0


def test_an_oversize_body_is_refused() -> None:
    client, backend = _client()
    response = _post(client, "x" * (MAX_BODY_BYTES + 1))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "body_too_large"
    assert backend.pastes == []




def test_a_paste_that_never_settled_answers_paste_not_settled() -> None:
    client, _ = _client(
        backend=FakeBackend(raises=PasteNotSettledError("pane never changed"))
    )
    response = _post(client, "hello")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "paste_not_settled"


def test_a_backend_with_no_paste_channel_answers_paste_unsupported() -> None:
    client, _ = _client(backend=FakeBackend(raises=NotImplementedError("no tmux")))
    response = _post(client, "hello")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "paste_unsupported"


def test_a_tmux_command_failure_is_a_500_not_a_refusal() -> None:
    client, _ = _client(backend=FakeBackend(raises=RuntimeError("tmux exploded")))
    response = _post(client, "hello")
    assert response.status_code == 500
    assert "tmux exploded" not in response.text
    assert response.json()["detail"]["code"] == "session_paste_failed"




def test_an_unknown_session_is_a_404() -> None:
    client, _ = _client()
    response = _post(client, "hello", session_id="ses_does_not_exist")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "session_not_found"


def test_a_session_with_no_live_backend_answers_session_gone() -> None:
    client, _ = _client(register_backend=False)
    response = _post(client, "hello")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "session_gone"




def test_the_route_requires_authentication() -> None:
    app = FastAPI()
    app.include_router(one_shot_routes.router)
    with TestClient(app) as client:
        response = client.post(
            f"/sessions/{CREATED_ID}/skills/one-shot", json={"text": "hello"}
        )
    assert response.status_code in (401, 403), response.text


def test_every_refusal_carries_a_code_and_a_message() -> None:
    client, _ = _client(backend=FakeBackend(pane_command=SHELL_PANE_COMMAND))
    detail = _post(client, "hello").json()["detail"]
    assert set(detail) == {"code", "message"}
    assert detail["message"].strip()
