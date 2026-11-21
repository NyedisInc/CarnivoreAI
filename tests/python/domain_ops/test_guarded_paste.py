from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.api import one_shot_routes
from src.core.sessions import guarded_paste
from src.core.sessions.guarded_paste import GateOptions, PasteFailed, PasteRefused, PasteSessionNotFound


def _state(*, session=None, backend=None) -> SimpleNamespace:
    registry = SimpleNamespace(get_session=lambda sid: session, get_backend=lambda sid: backend)
    return SimpleNamespace(services=SimpleNamespace(registry=registry), session_manager=None)


def _paste(state: SimpleNamespace, text: str = "hello", options: GateOptions = GateOptions()):
    return asyncio.run(guarded_paste.paste_through_gates(state, "ses_1", text, options))


def test_an_unknown_session_is_a_typed_not_found_and_never_an_http_error() -> None:
    with pytest.raises(PasteSessionNotFound) as seen:
        _paste(_state())
    assert seen.value.code == "session_not_found" and not isinstance(seen.value, HTTPException)


def test_a_session_with_no_backend_is_session_gone_and_counts_as_nothing_landed() -> None:
    with pytest.raises(PasteRefused) as seen:
        _paste(_state(session=SimpleNamespace(tmux_session="t")))
    assert seen.value.code == "session_gone" and seen.value.nothing_landed


def test_the_body_is_sanitised_before_any_pane_signal_is_read() -> None:
    class Backend:
        def list_pane_status_all(self):
            raise AssertionError("the pane was read before the body was sanitised")

    with pytest.raises(PasteRefused) as seen:
        _paste(_state(session=SimpleNamespace(tmux_session="t"), backend=Backend()), "a\x1bb")
    assert seen.value.code == "body_has_escape"


@pytest.mark.parametrize("refusal, status, detail", [
    (PasteSessionNotFound("session_not_found", "no session is registered as 'x'", "x"), 404,
     {"code": "session_not_found", "message": "no session is registered as 'x'"}),
    (PasteRefused("pane_dialog_open", "a dialog is open", "x"), 409, {"code": "pane_dialog_open", "message": "a dialog is open"}),
    (PasteRefused("paste_not_settled", "did not settle", "x"), 409, {"code": "paste_not_settled", "message": "did not settle"}),
])
def test_the_route_keeps_the_status_and_body_master_answered(refusal, status, detail) -> None:
    http = one_shot_routes.paste_refusal_to_http(refusal)
    assert (http.status_code, http.detail) == (status, detail)


def test_a_tmux_failure_keeps_its_500_and_its_error_code() -> None:
    http = one_shot_routes.paste_refusal_to_http(PasteFailed(guarded_paste.PASTE_FAILED, "boom", "x"))
    assert (http.status_code, http.detail["code"]) == (500, "session_paste_failed")


def test_the_facade_still_raises_http_for_the_unconverted_swarm_caller() -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=_state()))
    with pytest.raises(HTTPException) as seen:
        asyncio.run(one_shot_routes.paste_through_gates(request, "ses_1", "hello"))
    assert seen.value.status_code == 404 and seen.value.detail["code"] == "session_not_found"


MASTER_STATUS_BY_CODE = {
    guarded_paste.SESSION_NOT_FOUND: 404,
    guarded_paste.PASTE_FAILED: 500,
    **{code: 409 for code in (
        "pane_not_an_agent", "pane_dialog_open", "body_has_escape", "body_empty", "body_too_large", "body_not_utf8",
        "dialog_unreadable", "budget_held", guarded_paste.SESSION_GONE, guarded_paste.RECEIVER_INSTANCE_CHANGED,
        guarded_paste.PASTE_NOT_SETTLED, guarded_paste.PASTE_NOT_SUBMITTED, guarded_paste.PASTE_UNSUPPORTED)},
}


def _raised_for(code: str) -> PasteRefused:
    kind = {guarded_paste.SESSION_NOT_FOUND: PasteSessionNotFound, guarded_paste.PASTE_FAILED: PasteFailed}.get(code, PasteRefused)
    return kind(code, f"refused: {code}", "ses_1")


@pytest.mark.parametrize("code, status", sorted(MASTER_STATUS_BY_CODE.items()))
def test_every_paste_refusal_code_keeps_the_status_master_answered(code: str, status: int) -> None:
    http = one_shot_routes.paste_refusal_to_http(_raised_for(code))
    assert http.status_code == status
    assert http.detail["code"] == code
