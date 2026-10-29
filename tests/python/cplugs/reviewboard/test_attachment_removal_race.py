
from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path

from src.cplugs.huddle import files as huddle_files, store_files
from src.cplugs.huddle.rules import TaskManagerError
from src.cplugs.huddle.store_files import Located
from tests.python.cplugs.reviewboard.harness import BASE, task_manager_store
from tests.python.cplugs.reviewboard.test_attachment_removal import _message, two  # noqa: F401
from tests.python.cplugs.reviewboard.test_attachments import board, client, env  # noqa: F401


def test_a_reply_posted_while_the_removal_is_paused_before_the_unlink_never_dangles(env, client, board, two, monkeypatch):
    item, victim = board["item"], two[0]["file_id"]
    storage, store = env.host.storage("huddle"), task_manager_store(env)
    attached = huddle_files.parts_of(huddle_files.attach(storage, item, [victim]))
    at_unlink, resume = threading.Event(), threading.Event()
    real_unlink = Path.unlink

    def paused_unlink(self, *args, **kwargs):
        if victim in self.name:
            at_unlink.set()
            assert resume.wait(timeout=10)
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", paused_unlink)
    answers = {}
    remover = threading.Thread(target=lambda: answers.update(removed=client.delete(f"{BASE}/boards/{board['slug']}/attachments/{victim}")))
    remover.start()
    assert at_unlink.wait(timeout=10), "the removal never reached its unlink"
    try:
        answers["reply"] = store.post(item, "see that file", actor="joe", kind="reply", parts=attached)
    except TaskManagerError as exc:
        answers["refused"] = exc
    resume.set()
    remover.join(timeout=20)
    assert answers["removed"].status_code == 200
    on_disk = any((storage.path / "files" / str(item)).glob(f"{victim}-*"))
    if "reply" in answers:
        linked = [f["id"] for f in _message(env, item, answers["reply"]["message"]["id"]).get("files") or []]
        assert not linked or on_disk, "the reply links bytes that were deleted"
    else:
        assert answers["refused"].code == "task_manager_file_removed" and answers["refused"].status == 409


class FailingCommit:

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def __getattr__(self, name: str):
        return getattr(self._conn, name)

    def __enter__(self) -> "FailingCommit":
        return self

    def __exit__(self, *exc) -> None:
        self._conn.rollback()
        raise sqlite3.OperationalError("database is locked")


def test_a_commit_that_fails_after_the_rename_puts_the_bytes_back(env, client, board, two, monkeypatch):
    item, mid, victim = board["item"], two[0]["message_id"], two[0]["file_id"]
    storage, store = env.host.storage("huddle"), task_manager_store(env)
    path = huddle_files.locate(storage, item, victim)
    before, names = _message(env, item, mid), sorted(p.name for p in path.parent.iterdir())
    real = type(store)._connect
    monkeypatch.setattr(type(store), "_connect", lambda self, write: FailingCommit(real(self, write)) if write else real(self, write))
    try:
        store.forget_file(item, mid, victim, lambda: Located(path))
    except sqlite3.OperationalError:
        pass
    else:
        raise AssertionError("the commit was meant to fail")
    assert sorted(p.name for p in path.parent.iterdir()) == names, "the bytes are back under their own name, nothing left aside"
    assert _message(env, item, mid) == before, "the thread is unchanged"


def test_a_leftover_set_aside_file_is_unlinked_by_a_retried_removal(env, client, board, two):
    item, victim = board["item"], two[0]["file_id"]
    storage = env.host.storage("huddle")
    path = huddle_files.locate(storage, item, victim)
    leftover = huddle_files.aside_name(path)
    path.rename(leftover)
    r = client.delete(f"{BASE}/boards/{board['slug']}/attachments/{victim}")
    assert r.status_code == 200 and r.json()["bytes"]["deleted"] is True and not leftover.exists()


def test_the_sweep_leaves_a_fresh_set_aside_copy_and_takes_an_old_one(env, client, board, two, monkeypatch):
    item = board["item"]
    storage = env.host.storage("huddle")
    first, second = (huddle_files.locate(storage, item, t["file_id"]) for t in two)
    fresh, old = huddle_files.aside_name(first), huddle_files.aside_name(second)
    first.rename(fresh)
    second.rename(old)
    now = time.time()
    assert huddle_files.sweep_orphans(storage, now=now) == 0 and fresh.exists() and old.exists(), "both are inside the grace period"
    os.utime(old, (now - huddle_files.ASIDE_GRACE_S - 1,) * 2)
    real_unlink, seen = Path.unlink, []

    def vanished_first(self, *args, **kwargs):
        if not seen:
            seen.append(self)
            raise FileNotFoundError(self.name)
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", vanished_first)
    vanishing, unlinked = (storage.path / "files" / str(item) / f"{huddle_files.ASIDE_PREFIX}{name}" for name in ("yy-older", "zz-older"))
    for other in (vanishing, unlinked):
        other.write_bytes(b"x")
        os.utime(other, (now - 1000,) * 2)
    swept = huddle_files.sweep_orphans(storage, now=now)
    assert swept == 1, "the first unlink finds its file gone (it does not count), the sweep goes on and unlinks the second"
    assert not unlinked.exists(), "the second old copy of an unnamed file was unlinked"
    assert vanishing.exists(), "the first is still on disk: only the stubbed unlink pretended it was gone"
    assert fresh.exists(), "a copy inside the grace period stays"
    assert old.exists(), "an old copy of a file a message still names stays: the only bytes there are (#2655)"


def test_a_retry_that_waits_on_a_failed_first_removal_still_deletes_the_bytes(env, client, board, two, monkeypatch):
    item, mid, victim = board["item"], two[0]["message_id"], two[0]["file_id"]
    store = task_manager_store(env)
    storage = env.host.storage("huddle")
    path = huddle_files.locate(storage, item, victim)
    asided, go = threading.Event(), threading.Event()
    real_aside, real_connect, opened = store_files._set_aside, type(store)._connect, []

    def held_aside(*args, **kwargs):
        out = real_aside(*args, **kwargs)
        asided.set()
        assert go.wait(timeout=10)
        return out

    def first_connection_fails(self, write):
        conn = real_connect(self, write)
        if write and not opened:
            opened.append(1)
            return FailingCommit(conn)
        return conn

    monkeypatch.setattr(store_files, "_set_aside", held_aside)
    monkeypatch.setattr(type(store), "_connect", first_connection_fails)
    first = threading.Thread(target=lambda: _swallow(lambda: store.forget_file(item, mid, victim, lambda: Located(path))))
    first.start()
    assert asided.wait(timeout=10)
    answers = {}
    retry = threading.Thread(target=lambda: answers.update(r=client.delete(f"{BASE}/boards/{board['slug']}/attachments/{victim}")))
    retry.start()
    time.sleep(0.3)
    go.set()
    first.join(timeout=20)
    retry.join(timeout=20)
    assert answers["r"].status_code == 200 and answers["r"].json()["bytes"]["deleted"] is True, answers["r"].text
    assert not any((storage.path / "files" / str(item)).glob(f"*{victim}-*")), "no bytes left under any name"


def _swallow(call) -> None:
    try:
        call()
    except sqlite3.OperationalError:
        pass
