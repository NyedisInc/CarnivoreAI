
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.budget_hold import gate
from src.core.budget_hold.gate import hold_check, live_hold_check, raise_if_held
from src.core.budget_hold.store import HoldStore
from src.core.budget_hold.submit_detect import PASTE_END, PASTE_START, SubmitDetector
from src.core.session_one_shot_gate import BUDGET_HELD, OneShotRefused

P, E = PASTE_START, PASTE_END
_REAL_SWITCH_ON = gate.switch_on

DETECTOR_TABLE = [
    (["hello"], ("hello", False)),
    (["\r"], ("", True)),
    (["\n"], ("", True)),
    (["abc\rdef"], ("abc", True)),
    ([f"{P}one{E}"], (f"{P}one{E}", False)),
    ([f"{P}one\ntwo{E}"], ("", True)),
    ([f"{P}one\n{E}"], ("", True)),
    ([f"x{P}a\r{E}"], ("x", True)),
    ([f"{P}one{E}\r"], (f"{P}one{E}", True)),
    (["\x1bOM"], ("", True)),
    (["\x1b[13u"], ("", True)),
    (["\x1b"], ("\x1b", False)),
    (["\x03"], ("\x03", False)),
    (["\x1b[A"], ("\x1b[A", False)),
    (["\x1b", "\r"], ("", True)),
    ([f"{P}one", f"two{E}"], (f"two{E}", False)),
    ([f"{P}one", f"\ntwo{E}"], ("", True)),
    ([f"{P}one", f"two{E}", "\r"], ("", True)),
    (["\x1b[20", f"0~a\nb{E}"], ("", True)),
    ([f"{P}a\nb{E}", "x"], ("x", False)),
]


@pytest.mark.parametrize("frames,expected", DETECTOR_TABLE)
def test_detector_table(frames, expected):
    det = SubmitDetector()
    out = None
    for frame in frames:
        out = det.split(frame)
    assert out == expected


@pytest.fixture
def held(tmp_path, monkeypatch):
    store = HoldStore(tmp_path / "argent.db")
    store.set_hold("wi_1", "checkout rewrite", ["7"])
    store.set_hold("wi_2", "search cache", ["7", "8"])
    monkeypatch.setattr(gate, "STORE", store)
    monkeypatch.setattr(gate, "switch_on", lambda: True)
    return store


def _check(session_key, data, status="idle", startup="ready", **kw):
    return hold_check(session_key, data, status, startup, **kw)


def test_hold_refuses_enter_and_paste_and_names_every_item(held):
    for data in ("\r", "\n", f"{P}a\nb{E}", "text\r"):
        v = _check(7, data)
        assert v.held and set(v.item_names) == {"checkout rewrite", "search cache"}
    assert _check(7, "text\r").passable == "text"
    assert _check(8, "\r").item_names == ("search cache",)
    assert _check(7, "typing").held is False


@pytest.mark.parametrize("status", ["idle", "finished_unread", "unknown", None])
def test_prompt_ready_and_unmeasured_panes_are_held(held, status):
    assert _check(7, "\r", status=status).held


@pytest.mark.parametrize("kw", [
    {"status": "working"}, {"status": "working_subagent"}, {"status": "question"}, {"status": "notice"},
    {"startup": "folder_trust"}, {"exempt": True},
])
def test_exemptions_pass_untouched(held, kw):
    assert _check(7, "\r", **kw).held is False


def test_escape_ctrl_c_and_other_sessions_pass(held):
    assert not _check(7, "\x1b").held and not _check(7, "\x03").held
    assert not _check(99, "\r").held and not _check(None, "\r").held


def test_hold_persisted_across_a_restart(tmp_path, monkeypatch):
    path = tmp_path / "argent.db"
    HoldStore(path).set_hold("wi_1", "checkout rewrite", ["7"])
    monkeypatch.setattr(gate, "STORE", HoldStore(path))
    monkeypatch.setattr(gate, "switch_on", lambda: True)
    assert _check(7, "\r").held
    gate.STORE.clear_hold("wi_1")
    assert not _check(7, "\r").held and gate.STORE.snapshot() == []


def _config(tmp_path, monkeypatch, body):
    cfg = tmp_path / "config.json"
    if body is not None:
        cfg.write_text(body)
    from src.config import settings
    monkeypatch.setattr(settings, "auth_config_file", str(cfg))
    monkeypatch.setattr(gate, "_switch_cache", (None, False))
    return cfg


@pytest.mark.parametrize("body,expected", [
    (None, False), ("{}", False), (json.dumps({"argent": {"enabled": False}}), False),
    (json.dumps({"argent": {"enabled": True}}), True),
    ("{not json", True),
])
def test_switch_off_is_inert_and_unreadable_keeps_the_hold(tmp_path, monkeypatch, held, body, expected):
    _config(tmp_path, monkeypatch, body)
    monkeypatch.setattr(gate, "switch_on", _REAL_SWITCH_ON)
    assert hold_check(7, "\r", "idle", "ready").held is expected


def test_one_shot_gate_raises_budget_held_and_resume_is_exempt(held):
    info = SimpleNamespace(session_row_id=7, activity_status="idle", startup_gate="ready")
    with pytest.raises(OneShotRefused) as err:
        raise_if_held(info)
    assert err.value.code == BUDGET_HELD and "checkout rewrite" in err.value.message
    raise_if_held(info, exempt=True)
    raise_if_held(SimpleNamespace(session_row_id=7, activity_status="question", startup_gate="ready"))


def test_live_check_touches_nothing_while_no_hold_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "STORE", HoldStore(tmp_path / "argent.db"))

    class Boom:
        async def get_session_info(self, **_):
            raise AssertionError("the gate read a session with no hold set")

    assert asyncio.run(live_hold_check(Boom(), "ses_1", "\r")).held is False


def test_live_check_reads_the_row_when_held(held):
    class Mgr:
        async def get_session_info(self, session_id):
            return SimpleNamespace(session_row_id=7, activity_status="idle", startup_gate="ready")

    assert asyncio.run(live_hold_check(Mgr(), "ses_7", "go\r")).passable == "go"


def test_a_leaking_gate_fails_this_suite(held):
    def leaky(*_a, **_k):
        return gate.HoldVerdict(False, (), "\r")

    assert hold_check(7, "\r", "idle", "ready").held
    with pytest.raises(AssertionError):
        assert leaky(7, "\r", "idle", "ready").held


def test_no_timed_poll_or_release_in_the_module():
    src = "".join(p.read_text() for p in Path(gate.__file__).parent.glob("*.py"))
    assert "create_task" not in src and "asyncio.sleep" not in src and "call_later" not in src
    assert not any(name in src for name in ("def release", "def lift", "def override"))
