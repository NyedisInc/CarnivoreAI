from src.core.session_manager import SessionManager
from src.core.session_view_clears import clear_view_state, view_marks_read
from src.core.sessions.ports import SessionManagerSurface


def test_real_session_manager_carries_every_member_the_collaborators_reach() -> None:
    assert isinstance(SessionManager(), SessionManagerSurface)


def test_view_clears_fail_loudly_when_a_member_moves() -> None:
    class Moved:
        class _R:
            backends: dict = {}
            def get_backend(self, sid):  # noqa: D401
                return None
        _registry = _R()

    try:
        clear_view_state(Moved(), session_id="ses_1", tmux_name="cloude_x")
    except AttributeError:
        return
    raise AssertionError("a missing _unread_store must raise, not be skipped")


def test_view_marks_read_still_passes_when_no_watcher_has_started() -> None:
    class Early:
        _attention_watcher = None

    assert view_marks_read(Early(), "ses_1") is True
