
from __future__ import annotations

import inspect
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ph_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ph_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.sessions.probe_health import ProbeHealth, ProbeHealthRecorder
from src.core.tmux_listing import REASON_TIMEOUT, TmuxListing

MOVED_FIELDS = (
    "_last_probe_ok",
    "_last_probe_reason",
    "_last_probe_detail",
    "_last_probe_socket",
)


class _ProbeBackend:

    def __init__(self, listing, socket_name="cloude-test-s1"):
        self._listing = listing
        self.socket_name = socket_name

    def list_attachable_sessions(self, owned_names=None, owned_instances=None):
        return self._listing

    def list_pane_status_all(self):
        return TmuxListing.answered([])


def _manager_with_probe(monkeypatch, listing, *, recorder=None, socket_name="cloude-test-s1"):
    from src.core.session_manager import SessionManager

    monkeypatch.setattr(
        "src.core.session_manager.build_backend",
        lambda *a, **k: _ProbeBackend(listing, socket_name=socket_name),
    )
    rec = recorder if recorder is not None else ProbeHealthRecorder()
    mgr = SessionManager(probe_health=rec)
    return mgr, rec




def test_a_probe_that_never_ran_cannot_determine_and_never_reads_ok():
    rec = ProbeHealthRecorder()

    assert rec.health.ok is None, "never probed must be None"
    assert rec.health.ok is not True, "never probed must NEVER read as ok"
    assert rec.health.ok is not False, "never probed is not a failure either"
    assert rec.health.reason is None
    assert rec.health.detail is None


def test_a_failure_carries_the_listings_reason_and_detail_verbatim():
    rec = ProbeHealthRecorder()

    rec.record_failure(reason=REASON_TIMEOUT, detail="tmux busy")

    assert rec.health.ok is False
    assert rec.health.reason == REASON_TIMEOUT
    assert rec.health.detail == "tmux busy"


def test_a_success_clears_the_previous_failures_reason_and_detail():
    rec = ProbeHealthRecorder()
    rec.record_failure(reason=REASON_TIMEOUT, detail="tmux busy")

    rec.record_success()

    assert rec.health.ok is True
    assert rec.health.reason is None, "a success must not carry a stale reason"
    assert rec.health.detail is None


def test_record_success_cannot_be_handed_a_reason_at_all():
    params = list(inspect.signature(ProbeHealthRecorder.record_success).parameters)

    assert params == ["self"], f"record_success must take nothing but self, got {params}"


def test_record_failure_is_keyword_only_so_reason_and_detail_cannot_be_swapped():
    sig = inspect.signature(ProbeHealthRecorder.record_failure)
    kinds = {
        name: p.kind
        for name, p in sig.parameters.items()
        if name != "self"
    }

    assert kinds == {
        "reason": inspect.Parameter.KEYWORD_ONLY,
        "detail": inspect.Parameter.KEYWORD_ONLY,
    }


def test_the_configured_socket_answers_until_a_probe_binds_one():
    rec = ProbeHealthRecorder()

    assert rec.socket is None
    assert rec.socket_name(configured="cloude") == "cloude"


def test_the_probed_socket_wins_over_the_configured_one():
    rec = ProbeHealthRecorder()

    rec.record_socket("cloude-pinned")

    assert rec.socket == "cloude-pinned"
    assert rec.socket_name(configured="cloude") == "cloude-pinned"


def test_a_probe_exposing_no_socket_falls_back_to_the_configured_one():
    rec = ProbeHealthRecorder()

    rec.record_socket(None)

    assert rec.socket_name(configured="cloude") == "cloude"


def test_the_socket_is_recorded_independently_of_the_health():
    rec = ProbeHealthRecorder()

    rec.record_socket("cloude-pinned")
    rec.record_failure(reason=REASON_TIMEOUT, detail=None)

    assert rec.health.ok is False
    assert rec.socket_name(configured="cloude") == "cloude-pinned"




def test_the_facade_keeps_no_copy_of_the_moved_probe_fields():
    from src.core.session_manager import SessionManager

    mgr = SessionManager()

    survivors = [f for f in MOVED_FIELDS if hasattr(mgr, f)]
    assert survivors == [], (
        f"the facade kept its own copy of {survivors}; the state must MOVE, "
        "not copy"
    )


def test_the_injected_recorder_is_the_object_the_manager_holds():
    from src.core.session_manager import SessionManager

    rec = ProbeHealthRecorder()
    mgr = SessionManager(probe_health=rec)

    assert mgr._probe_health is rec, "the manager must hold the injected object"


def test_a_write_on_the_recorder_is_visible_through_the_facade():
    from src.core.session_manager import SessionManager

    rec = ProbeHealthRecorder()
    mgr = SessionManager(probe_health=rec)
    assert mgr._probe_health.health.ok is None

    rec.record_failure(reason=REASON_TIMEOUT, detail="tmux busy")

    health = mgr._probe_health.health
    assert health.ok is False, "the facade must READ THROUGH, not cache"
    assert health.reason == REASON_TIMEOUT
    assert health.detail == "tmux busy"


def test_a_write_on_the_recorders_socket_is_visible_through_the_facade():
    from src.core.session_manager import SessionManager

    rec = ProbeHealthRecorder()
    mgr = SessionManager(probe_health=rec)

    rec.record_socket("cloude-pinned")

    assert mgr.tmux_socket_name() == "cloude-pinned"
    assert mgr.tmux_socket_name() == "cloude-pinned"


def test_the_real_failed_probe_path_writes_through_to_the_injected_recorder(
    monkeypatch,
):
    mgr, rec = _manager_with_probe(
        monkeypatch, TmuxListing.unavailable(REASON_TIMEOUT)
    )
    assert rec.health.ok is None

    listing = mgr.list_attachable_sessions()

    assert listing.ok is False
    assert rec.health.ok is False, "the real probe path must record on the recorder"
    assert rec.health.reason == REASON_TIMEOUT
    assert rec.socket == "cloude-test-s1", "the bound socket must be recorded too"
    assert mgr._probe_health.health == rec.health


def test_the_real_successful_probe_path_writes_through_to_the_injected_recorder(
    monkeypatch,
):
    mgr, rec = _manager_with_probe(monkeypatch, TmuxListing.answered([]))
    rec.record_failure(reason=REASON_TIMEOUT, detail="stale")

    listing = mgr.list_attachable_sessions()

    assert listing.ok is True
    assert rec.health.ok is True
    assert rec.health.reason is None, "a success must clear the stale failure"
    assert rec.health.detail is None




def test_probe_health_is_still_importable_from_session_manager():
    from src.core.session_manager import ProbeHealth as ReExported

    assert ReExported is ProbeHealth
    assert ReExported(ok=None).ok is None


def test_session_manager_still_constructs_with_no_arguments():
    from src.core.session_manager import SessionManager

    mgr = SessionManager()

    assert isinstance(mgr._probe_health.health, ProbeHealth)
    assert mgr._probe_health.health.ok is None


def test_every_collaborator_argument_is_keyword_only_and_optional():
    from src.core.session_manager import SessionManager

    sig = inspect.signature(SessionManager.__init__)
    for name, p in sig.parameters.items():
        if name == "self":
            continue
        assert p.kind is inspect.Parameter.KEYWORD_ONLY, f"{name} must be keyword-only"
        assert p.default is not inspect.Parameter.empty, f"{name} must be optional"


def test_list_attachable_sessions_with_socket_names_the_probed_socket(monkeypatch):
    mgr, _rec = _manager_with_probe(
        monkeypatch, TmuxListing.unavailable(REASON_TIMEOUT)
    )

    socket, listing = mgr.list_attachable_sessions_with_socket()

    assert socket == "cloude-test-s1"
    assert listing.ok is False
