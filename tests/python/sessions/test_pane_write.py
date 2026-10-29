import asyncio
from types import SimpleNamespace

import pytest

from src.core.sessions.errors import SessionInputFailed
from src.core.sessions.pane_write import deliver_to_pane


class _Backend:
    def __init__(self, exc=None):
        self.exc, self.sent = exc, []

    async def write(self, data):
        if self.exc:
            raise self.exc
        self.sent.append(data)


def _run(coro):
    return asyncio.run(coro)


def test_delivery_stamps_activity_and_runs_callback():
    sess, b, calls = SimpleNamespace(last_activity=None), _Backend(), []
    assert _run(deliver_to_pane(b, sess, "s", b"x", what="input", after_delivery=lambda: calls.append(1))) is True
    assert b.sent == [b"x"] and sess.last_activity is not None and calls == [1]


@pytest.mark.parametrize("exc", [OSError("pipe"), RuntimeError("dead")])
def test_write_failure_is_input_failed_and_skips_bookkeeping(exc):
    sess, calls = SimpleNamespace(last_activity=None), []
    with pytest.raises(SessionInputFailed, match="Failed to send command"):
        _run(deliver_to_pane(_Backend(exc), sess, "s", b"x", what="command", after_delivery=lambda: calls.append(1)))
    assert sess.last_activity is None and calls == []


def test_bookkeeping_failure_surfaces_as_itself():
    def boom():
        raise KeyError("db")

    with pytest.raises(KeyError):
        _run(deliver_to_pane(_Backend(), SimpleNamespace(last_activity=None), "s", b"x", what="command", after_delivery=boom))


def test_non_write_error_propagates():
    with pytest.raises(ValueError):
        _run(deliver_to_pane(_Backend(ValueError("bug")), SimpleNamespace(last_activity=None), "s", b"x", what="input"))


def test_a_quoting_refusal_is_input_failed_not_a_bare_value_error():
    from src.core.hosts.tmux_quote import TmuxQuoteError

    sess = SimpleNamespace(last_activity=None)
    with pytest.raises(SessionInputFailed, match="Failed to send input"):
        _run(deliver_to_pane(_Backend(TmuxQuoteError("refused")), sess, "s", b"x", what="input"))
