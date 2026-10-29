
from __future__ import annotations

from src.cplugs.huddle import service
from src.cplugs.host import runtime
from tests.python.cplugs.huddle.test_task_manager_routes import app  # noqa: F401

ROWS = [{"id": "ses_a", "key": "key-a", "name": "a"}, {"id": "ses_b", "key": "key-b", "name": "b"}]


def count_opens(ctx, monkeypatch) -> list:
    opened: list = []
    real = ctx.storage._open

    def counting(write: bool):
        opened.append(write)
        return real(write)

    monkeypatch.setattr(ctx.storage, "_open", counting)
    return opened


def test_send_choice_opens_one_connection_and_answers_the_same(app, monkeypatch):
    ctx = runtime.host_for(app).context("huddle")
    service.store(ctx).add("12", "seed the database", actor="joe")
    opened = count_opens(ctx, monkeypatch)

    scoped = service.send_choice(ctx, ROWS, "12")
    assert opened == [False], "one read connection for the whole call"

    opened.clear()
    unscoped = service._send_choice(ctx, ROWS, "12")
    assert len(opened) <= 1, "no connection per helper: the thread's reused read connection serves them all"
    assert scoped == unscoped


def test_a_write_inside_a_read_scope_still_gets_its_own_connection(app, monkeypatch):
    ctx = runtime.host_for(app).context("huddle")
    service.store(ctx).add("12", "seed", actor="joe")
    opened = count_opens(ctx, monkeypatch)
    with ctx.storage.read_scope():
        ctx.storage.connect(False).close()
        writer = ctx.storage.connect(True)
        writer.close()
        ctx.storage.connect(False).close()
    assert opened == [False, True]
