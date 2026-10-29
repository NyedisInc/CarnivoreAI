
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_famdisp_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_famdisp_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.agent_families import (
    AGENT_FAMILY_NAMES,
    DEFAULT_FAMILY,
    get_family,
    resolve_agent_type,
)
from src.core.agent_family_display import (
    DISPLAY_FAMILY_SOURCES,
    FAMILY_SOURCE_DERIVED_DEEPEST,
    FAMILY_SOURCE_FINGERPRINT,
    FAMILY_SOURCE_RESERVED_NAME,
    FAMILY_SOURCE_UNKNOWN,
    FAMILY_SOURCE_WRAPPER,
    resolve_family_for_display,
)
from src.core.agent_wrappers import AgentWrapper


def _w(wid, family="claude", **kw):
    base = {"id": wid, "family": family, "label": wid, "script": f"{wid} run"}
    base.update(kw)
    return AgentWrapper(**base)



def test_launch_and_display_resolvers_disagree_on_an_unknown_wrapper_id():
    bogus = "deleted-wrapper-that-no-longer-exists"
    wrappers = [_w("cld", family="claude")]

    launch_family = get_family(bogus)
    assert launch_family.name == DEFAULT_FAMILY == "claude"

    display_family, source = resolve_family_for_display(bogus, wrappers)
    assert display_family is None
    assert source == FAMILY_SOURCE_UNKNOWN

    resolved_family, explicit_wrapper = resolve_agent_type(bogus, wrappers)
    assert resolved_family.name == "claude"
    assert explicit_wrapper is None


def test_get_family_launch_behaviour_is_unchanged_for_every_family_name():
    for name in AGENT_FAMILY_NAMES:
        assert get_family(name).name == name
    assert get_family(None).name == DEFAULT_FAMILY
    assert get_family("").name == DEFAULT_FAMILY
    assert get_family("totally-unrecognized").name == DEFAULT_FAMILY



def test_reserved_name_source_is_a_direct_family_name_match():
    family, source = resolve_family_for_display("codex", [])
    assert family is not None and family.name == "codex"
    assert source == FAMILY_SOURCE_RESERVED_NAME


def test_wrapper_source_is_an_explicit_stored_choice():
    wrappers = [_w("mywrap", family="hermes")]
    family, source = resolve_family_for_display("mywrap", wrappers)
    assert family is not None and family.name == "hermes"
    assert source == FAMILY_SOURCE_WRAPPER


def test_derived_deepest_source_is_a_wrapper_with_no_recorded_family():
    wrappers = [{"id": "legacy-wrap"}]
    family, source = resolve_family_for_display("legacy-wrap", wrappers)
    assert family is not None and family.name == DEFAULT_FAMILY
    assert source == FAMILY_SOURCE_DERIVED_DEEPEST


def test_fingerprint_source_requires_the_caller_to_say_so():
    family, source = resolve_family_for_display("openclaw", [], from_fingerprint=True)
    assert family is not None and family.name == "openclaw"
    assert source == FAMILY_SOURCE_FINGERPRINT

    family2, source2 = resolve_family_for_display("openclaw", [])
    assert source2 == FAMILY_SOURCE_RESERVED_NAME
    assert source2 != source


def test_unknown_source_covers_missing_blank_and_unresolvable():
    for bad_value in (None, "", "   ", "not-a-family-or-wrapper-id"):
        family, source = resolve_family_for_display(bad_value, [])
        assert family is None
        assert source == FAMILY_SOURCE_UNKNOWN


def test_unknown_source_when_wrapper_matches_but_family_is_unrecognized():
    wrappers = [{"id": "future-wrap", "family": "some-future-family"}]
    family, source = resolve_family_for_display("future-wrap", wrappers)
    assert family is None
    assert source == FAMILY_SOURCE_UNKNOWN



def test_no_source_outside_the_declared_five_is_ever_returned():
    wrappers = [
        _w("cld", family="claude"),
        _w("codexwrap", family="codex"),
        {"id": "legacy"},
        {"id": "future", "family": "nonsense"},
    ]
    probes = [None, "", "claude", "codex", "hermes", "openclaw", "shell",
              "cld", "codexwrap", "legacy", "future", "garbage-id"]
    for value in probes:
        for fp in (False, True):
            _, source = resolve_family_for_display(value, wrappers, from_fingerprint=fp)
            assert source in DISPLAY_FAMILY_SOURCES, (value, fp, source)


def test_default_family_is_never_smuggled_into_an_unknown_result():
    wrappers = [_w("cld", family="claude")]
    probes = ["bogus", "", None, "not-a-wrapper", "12345"]
    for value in probes:
        family, source = resolve_family_for_display(value, wrappers)
        if source == FAMILY_SOURCE_UNKNOWN:
            assert family is None, (
                f"source was 'unknown' but a family was still returned: {family}"
            )



def test_session_info_and_attachable_session_carry_the_display_pair():
    from src.models import AttachableSession, SessionInfo, SessionStats, Session, SessionStatus
    from datetime import datetime

    info = SessionInfo(
        session=Session(
            id="s1",
            working_dir="/tmp",
            status=SessionStatus.RUNNING,
            agent_type="deleted-wrapper",
        ),
        stats=SessionStats(),
        agent_type="deleted-wrapper",
        agent_family=None,
        agent_family_source="unknown",
    )
    assert info.agent_family is None
    assert info.agent_family_source == "unknown"

    row = AttachableSession(
        name="cloude_x",
        created_by_cloude=True,
        created_at_epoch=1,
        window_count=1,
    )
    assert row.agent_family is None
    assert row.agent_family_source is None


def test_session_carries_fingerprint_provenance_and_defaults_false():
    from src.models import Session, SessionStatus

    launched = Session(id="s1", working_dir="/tmp", status=SessionStatus.RUNNING,
                        agent_type="claude")
    assert launched.agent_type_via_fingerprint is False

    adopted = Session(id="s2", working_dir="/tmp", status=SessionStatus.RUNNING,
                       agent_type="codex", agent_type_via_fingerprint=True)
    assert adopted.agent_type_via_fingerprint is True



import pytest  # noqa: E402


class _StubSettings:

    def __init__(self, log_dir, wrappers=None):
        self._log_dir = log_dir
        self.port = 5001
        self._wrappers = wrappers or []

    def load_auth_config(self):
        from types import SimpleNamespace
        return SimpleNamespace(agents=SimpleNamespace(wrappers=self._wrappers))

    def get_pinned_themes_path(self):
        return self._log_dir / "pinned_themes.json"

    def get_unread_state_path(self):
        return self._log_dir / "unread_state.json"

    @property
    def log_directory(self):
        return str(self._log_dir)

    def get_session_metadata_path(self):
        return self._log_dir / "session_metadata.json"


class _FakeBackend:
    def __init__(self, tmux_session):
        self.tmux_session = tmux_session

    def is_alive(self):
        return True


def _bare_manager_with_wrappers(monkeypatch, tmp_path, wrappers=None):
    from src.core.session_manager import SessionManager

    (tmp_path / "logs").mkdir(exist_ok=True)
    stub = _StubSettings(log_dir=tmp_path / "logs", wrappers=wrappers)
    monkeypatch.setattr("src.core.session_manager.settings", stub)
    return SessionManager()


@pytest.mark.asyncio
async def test_session_info_for_unresolvable_agent_type_renders_unknown(monkeypatch, tmp_path):
    from src.models import Session, SessionStatus

    mgr = _bare_manager_with_wrappers(monkeypatch, tmp_path)
    sess = Session(
        id="ses_x",
        working_dir=str(tmp_path),
        status=SessionStatus.RUNNING,
        tmux_session="cloude_ses_x",
        agent_type="wrapper-that-was-deleted",
    )
    mgr._registry.sessions["ses_x"] = sess
    mgr._registry.backends["ses_x"] = _FakeBackend("cloude_ses_x")
    mgr._registry.subscribers.setdefault("ses_x", [])
    monkeypatch.setattr(
        mgr, "_build_tmux_status_map",
        lambda: {"cloude_ses_x": {"status": "idle", "pid": 1}},
    )

    info = await mgr.get_session_info(session_id="ses_x")
    assert info is not None
    assert info.agent_type == "wrapper-that-was-deleted"
    assert info.agent_family is None
    assert info.agent_family_source == "unknown"


@pytest.mark.asyncio
async def test_session_info_for_resolvable_agent_type_renders_the_fact(monkeypatch, tmp_path):
    from src.models import Session, SessionStatus

    mgr = _bare_manager_with_wrappers(monkeypatch, tmp_path)
    sess = Session(
        id="ses_y",
        working_dir=str(tmp_path),
        status=SessionStatus.RUNNING,
        tmux_session="cloude_ses_y",
        agent_type="codex",
    )
    mgr._registry.sessions["ses_y"] = sess
    mgr._registry.backends["ses_y"] = _FakeBackend("cloude_ses_y")
    mgr._registry.subscribers.setdefault("ses_y", [])
    monkeypatch.setattr(
        mgr, "_build_tmux_status_map",
        lambda: {"cloude_ses_y": {"status": "idle", "pid": 1}},
    )

    info = await mgr.get_session_info(session_id="ses_y")
    assert info is not None
    assert info.agent_family == "codex"
    assert info.agent_family_source == "reserved_name"
