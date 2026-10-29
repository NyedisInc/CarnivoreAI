
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ti_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ti_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core import toast_auto_ack, toast_history
from src.core.session_manager import SessionManager
from src.core.sessions.toast_inbox import ToastInbox
from src.models import Session, SessionStatus




class _StubSettings:

    def __init__(self, pin_path: Path, log_dir: Path) -> None:
        self._pin_path = pin_path
        self._log_dir = log_dir

    def get_pinned_themes_path(self) -> Path:
        return self._pin_path

    def get_unread_state_path(self) -> Path:
        return self._pin_path.parent / "unread_state.json"

    @property
    def log_directory(self) -> str:
        return str(self._log_dir)

    def get_session_metadata_path(self) -> Path:
        return self._log_dir / "session_metadata.json"


@pytest.fixture()
def inbox() -> ToastInbox:
    return ToastInbox()


@pytest.fixture()
def manager(monkeypatch, tmp_path: Path) -> SessionManager:
    (tmp_path / "logs").mkdir(exist_ok=True)
    monkeypatch.setattr(
        "src.core.session_manager.settings",
        _StubSettings(
            pin_path=tmp_path / "pinned_themes.json",
            log_dir=tmp_path / "logs",
        ),
    )
    return SessionManager()


def _register(manager: SessionManager, session_id: str, work: Path) -> Session:
    sess = Session(
        id=session_id,
        pty_pid=0,
        working_dir=str(work),
        status=SessionStatus.RUNNING,
        tmux_session=f"cloude_{session_id}",
    )
    manager._registry.sessions[session_id] = sess
    return sess


def _store(inbox: ToastInbox, session_id: str, *, kind: str, title: str,
           body: str | None = None, now: datetime | None = None):
    return inbox.store(
        session_id,
        kind=kind,
        title=title,
        body=body,
        color=None,
        session_label=None,
        session_name=None,
        now=now,
    )




def test_leg_a_the_facade_containers_are_the_inbox_containers(manager):
    assert manager._toast_inbox.pending is manager._toast_inbox.pending


def test_leg_b_the_facade_holds_no_door_onto_the_cluster(manager):
    moved = ["_pending_toasts", "_pending_startup_toasts"]

    leftovers = [name for name in moved if hasattr(manager, name)]
    assert leftovers == [], (
        f"{leftovers} resolve on the facade again; the toast cluster is "
        "reached through the inbox and nothing else"
    )
    assert manager._toast_inbox.pending is not None


def test_leg_c_writes_cross_in_both_directions(manager, tmp_path):
    _register(manager, "ses_x", tmp_path)

    manager.record_toast("ses_x", "Notification", "hello")
    assert list(manager._toast_inbox.pending) == ["ses_x"]

    manager._toast_inbox.pending.setdefault("ses_direct", [])
    assert "ses_direct" in manager._toast_inbox.pending


def test_leg_d_the_public_methods_read_and_write_the_inbox(manager, tmp_path):
    _register(manager, "ses_d", tmp_path)

    toast = manager.record_toast("ses_d", "PermissionRequest", "may i")
    assert manager._toast_inbox.pending["ses_d"][0] is toast

    assert manager._toast_inbox.get("ses_d", unacked_only=True) == [toast]
    assert manager._toast_inbox.ack("ses_d", toast.id, toast_auto_ack.ACK_REASON_DISMISSED) is True
    assert manager._toast_inbox.pending["ses_d"][0].acknowledged is True
    assert manager._toast_inbox.get("ses_d", unacked_only=True) == []


def test_leg_e_the_history_reader_sees_the_records_and_no_longer_guesses(
    manager, tmp_path
):
    _register(manager, "ses_h", tmp_path)
    toast = manager.record_toast("ses_h", "Stop", "Your turn")

    buckets = toast_history.buckets_from_inbox(manager._toast_inbox)

    assert buckets is manager._toast_inbox.pending, (
        "toast_history is reading something other than the inbox's records"
    )
    assert toast_history.collect_toasts(buckets) == [toast]

    with pytest.raises(AttributeError):
        toast_history.buckets_from_inbox(object())




def test_a_second_stop_replaces_the_first_and_keeps_its_id(inbox):
    first, was_superseded = _store(inbox, "s", kind="Stop", title="Your turn")
    assert was_superseded is False

    second, was_superseded = _store(
        inbox, "s", kind="Stop", title="Your turn", body="later"
    )

    assert was_superseded is True
    assert second is first
    assert second.id == first.id
    assert second.body == "later"
    assert len(inbox.bucket("s")) == 1


def test_an_acked_stop_is_never_superseded(inbox):
    first, _ = _store(inbox, "s", kind="Stop", title="Your turn")
    assert inbox.ack("s", first.id, reason="dismissed") is True

    second, was_superseded = _store(inbox, "s", kind="Stop", title="Your turn")

    assert was_superseded is False
    assert second.id != first.id
    assert len(inbox.bucket("s")) == 2
    assert first.acknowledged is True


def test_notifications_and_permissions_never_supersede(inbox):
    for kind in ("Notification", "PermissionRequest"):
        _store(inbox, kind, kind=kind, title="same title")
        _store(inbox, kind, kind=kind, title="same title")
        assert len(inbox.bucket(kind)) == 2, f"{kind} collapsed"


def test_a_different_title_does_not_supersede(inbox):
    _store(inbox, "s", kind="Stop", title="Your turn")
    _store(inbox, "s", kind="Stop", title="Something else")
    assert len(inbox.bucket("s")) == 2


def test_find_supersedable_answers_none_for_an_empty_bucket(inbox):
    assert inbox.find_supersedable([], "Stop", "Your turn") is None




def test_ack_reports_the_transition_not_the_lookup(inbox):
    toast, _ = _store(inbox, "s", kind="Stop", title="Your turn")

    assert inbox.ack("s", toast.id, reason="dismissed") is True
    assert inbox.ack("s", toast.id, reason="dismissed") is False
    assert inbox.ack("s", "no_such_id", reason="dismissed") is False
    assert inbox.ack("no_such_session", toast.id, reason="dismissed") is False


def test_a_duplicate_ack_cannot_rewrite_the_reason(inbox):
    toast, _ = _store(inbox, "s", kind="PermissionRequest", title="may i")
    inbox.ack("s", toast.id, reason=toast_auto_ack.ACK_REASON_DISMISSED)

    inbox.ack("s", toast.id, reason=toast_auto_ack.ACK_REASON_ANSWERED)

    assert toast.ack_reason == toast_auto_ack.ACK_REASON_DISMISSED


def test_acking_is_scoped_to_the_session(inbox):
    mine, _ = _store(inbox, "mine", kind="Stop", title="Your turn")
    _store(inbox, "yours", kind="Stop", title="Your turn")

    assert inbox.ack("yours", mine.id, reason="dismissed") is False
    assert mine.acknowledged is False




def test_the_cap_drops_only_the_oldest_acked(inbox):
    made = []
    for i in range(inbox.ACKED_CAP + 10):
        toast, _ = _store(inbox, "s", kind="Notification", title=f"n{i}")
        inbox.ack("s", toast.id, reason="dismissed")
        made.append(toast)

    bucket = inbox.bucket("s")
    assert len(bucket) == inbox.ACKED_CAP
    assert bucket[0] is made[-1]
    assert made[0] not in bucket


def test_the_unacked_half_is_never_capped(inbox):
    count = inbox.ACKED_CAP * 3
    for i in range(count):
        _store(inbox, "s", kind="Notification", title=f"n{i}")

    assert len(inbox.get("s", unacked_only=True)) == count


def test_pruning_an_unknown_session_is_a_noop(inbox):
    inbox.prune("never_seen")
    assert inbox.pending == {}


def test_a_read_does_not_create_a_bucket(inbox):
    assert inbox.bucket("nobody") == []
    assert inbox.get("nobody") == []
    assert inbox.has("nobody") is False
    assert inbox.pending == {}


def test_dropping_a_session_leaves_the_others_alone(inbox):
    _store(inbox, "a", kind="Stop", title="Your turn")
    _store(inbox, "b", kind="Stop", title="Your turn")

    inbox.drop_session("a")

    assert inbox.has("a") is False
    assert len(inbox.bucket("b")) == 1


def test_get_returns_a_copy_so_a_caller_cannot_mutate_the_store(inbox):
    toast, _ = _store(inbox, "s", kind="Stop", title="Your turn")
    got = inbox.get("s")

    got.clear()

    assert len(inbox.bucket("s")) == 1
    assert inbox.bucket("s")[0] is toast




def test_a_duplicated_stop_acks_by_kind_and_not_the_toast_it_just_raised(
    manager, tmp_path
):
    _register(manager, "ses_e", tmp_path)

    permission = manager.record_toast("ses_e", "PermissionRequest", "may i")
    notice = manager.record_toast("ses_e", "Notification", "look at me")

    cutoff = datetime.utcnow()
    your_turn = manager.record_toast("ses_e", "Stop", "Your turn")

    first = manager.auto_ack_toasts("ses_e", "Stop", cutoff=cutoff)

    assert set(first) == {permission.id, notice.id}
    assert your_turn.id not in first, (
        "the Stop acked the toast it had just raised"
    )
    assert manager._toast_inbox.get("ses_e", unacked_only=True) == [your_turn]

    assert manager.auto_ack_toasts("ses_e", "Stop", cutoff=cutoff) == []
    assert manager._toast_inbox.get("ses_e", unacked_only=True) == [your_turn]


def test_a_stop_does_not_ack_a_permission_raised_after_it(manager, tmp_path):
    _register(manager, "ses_f", tmp_path)
    cutoff = datetime.utcnow() - timedelta(seconds=5)
    later = manager.record_toast("ses_f", "PermissionRequest", "may i")

    assert manager.auto_ack_toasts("ses_f", "Stop", cutoff=cutoff) == []
    assert later.acknowledged is False


def test_wiping_a_session_clears_its_records_through_the_inbox(
    manager, tmp_path
):
    _register(manager, "ses_w", tmp_path)
    manager.record_toast("ses_w", "Stop", "Your turn")

    manager._wipe_session_state("ses_w")

    assert manager._toast_inbox.has("ses_w") is False
    assert manager._toast_inbox.get("ses_w") == []
