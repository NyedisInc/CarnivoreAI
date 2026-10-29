
from __future__ import annotations

from src.core import session_journal_store as store
from src.core import session_journal_task as task
from src.core.claude_folder_trust import TRUST_TRUSTED, TRUST_UNKNOWN, TRUST_WILL_ASK, folder_trust, load_trust_map
from src.core.session_journal_measure import Measurement
from src.core.session_journal_observe import PaneFacts, instance_key, observe
from src.core.session_restore_offer import (
    OFFER_OPEN,
    REASON_SESSIONS_GONE,
    REASON_TMUX_SERVER_GONE,
    build_offer,
    decline,
    fold_offer,
    offer_candidates,
    settle_accept,
)
from src.core.session_restore_startup_check import watch_for_startup_prompts

T0 = "2026-09-24T07:00:00Z"
OLD = "2026-09-05T12:00:00Z"
BOOT = 1790000000


def _row(uuid, name, epoch, **kw):
    row = {"session_uuid": uuid, "tmux_name": name, "tmux_created_epoch": epoch, "title": name,
           "lifecycle": "running", "lifecycle_source": "create", "last_seen_running_at": T0,
           "archived_at": None, "claude_session_uuid": f"{uuid}-c", "working_dir": "/w",
           "agent_type": "claude-skip-permissions"}
    row.update(kw)
    return row


def _pane(r):
    return PaneFacts(name=r["tmux_name"], epoch=r["tmux_created_epoch"], claude_pid=1,
                     argv="claude --dangerously-skip-permissions",
                     observed_flags=["--dangerously-skip-permissions"],
                     conversation=r["claude_session_uuid"], conversation_source="claude_pid_record", cwd="/w")


LIVE = [_row("A", "cloude_a", 1), _row("B", "cloude_b", 2), _row("C", "cloude_c", 3)]
OLD_ROW = _row("X", "cloude_x", 9, lifecycle="stopped", lifecycle_source="tmux_missing",
               last_seen_running_at=OLD, title="old one")
NEVER = _row("N", "cloude_n", 7, lifecycle="stopped", lifecycle_source="tmux_missing",
             last_seen_running_at=OLD, title="never journaled")
ROWS = LIVE + [OLD_ROW, NEVER]


def _journal_live(rows, now):
    return observe(store.empty_journal(), listing_ok=True, listing_complete=True,
                   panes=[_pane(r) for r in rows],
                   rows_by_instance={(r["tmux_name"], r["tmux_created_epoch"]): r for r in rows},
                   groups={}, now_iso=now).journal


def _m(panes, *, server=True):
    return Measurement(listing_ok=True, listing_complete=True,
                       listing_reason=None if server else "no_server", panes=panes, writers=[],
                       rows=ROWS, groups={}, rows_ok=True, writers_ok=True)


def _morning(tmp_path, monkeypatch):
    old_j = _journal_live([OLD_ROW], OLD)
    j = _journal_live(LIVE, T0)
    j["sessions"].update(old_j["sessions"])
    j["boot"] = {"epoch": BOOT, "source": "sysctl", "recorded_at": T0}
    old = offer_candidates(old_j, [OLD_ROW], live_instances=set())
    assert [c["session_uuid"] for c in old] == ["X"]
    j["offer"] = build_offer(old, reason=REASON_SESSIONS_GONE, now_iso=OLD, boot_epoch=BOOT, previous_boot_epoch=BOOT)
    store.save_journal(tmp_path, j)
    state = {"m": _m([_pane(r) for r in LIVE])}
    monkeypatch.setattr(task, "measure", lambda *a, **k: state["m"])
    return j["offer"]["id"], state


def _pass(tmp_path):
    task.observe_pass(tmp_path, None, "cloude", tmp_path / "db")
    return store.load_journal(tmp_path).journal


def test_the_morning_sequence(tmp_path, monkeypatch):
    old_id, state = _morning(tmp_path, monkeypatch)

    j = _pass(tmp_path)
    assert j["offer"]["id"] == old_id and j["offer"]["reason"] == REASON_SESSIONS_GONE

    state["m"] = _m([], server=False)
    j = _pass(tmp_path)
    offer = j["offer"]
    assert offer["state"] == OFFER_OPEN and offer["id"] != old_id and offer["folded_from"] == old_id
    assert offer["reason"] == REASON_TMUX_SERVER_GONE
    by = {c["session_uuid"]: c["reason"] for c in offer["candidates"]}
    assert by == {"A": REASON_TMUX_SERVER_GONE, "B": REASON_TMUX_SERVER_GONE,
                  "C": REASON_TMUX_SERVER_GONE, "X": REASON_SESSIONS_GONE}
    assert "restore_offer_folded" in store.human_log_path(tmp_path).read_text()

    assert _pass(tmp_path)["offer"]["id"] == offer["id"]

    assert settle_accept(j, old_id, [{"session_uuid": "X", "outcome": "reopened"}], T0) is False

    assert settle_accept(j, offer["id"], [{"session_uuid": "A", "outcome": "reopened"}], T0)
    assert j["declined"] == {}
    later = offer_candidates(j, ROWS, live_instances={("cloude_a", 1)})
    assert sorted(c["session_uuid"] for c in later) == ["B", "C", "X"], \
        "what was not reopened must still be offerable later, and N never"


def test_the_fold_is_needed(tmp_path, monkeypatch):
    old_id, state = _morning(tmp_path, monkeypatch)
    monkeypatch.setattr(task, "fold_offer", lambda previous, fresh, **k: (previous, False))
    state["m"] = _m([], server=False)
    j = _pass(tmp_path)
    assert j["offer"]["id"] == old_id and len(j["offer"]["candidates"]) == 1


def test_only_what_was_running_is_offered_and_idle_does_not_matter():
    j = _journal_live([OLD_ROW], OLD)
    got = offer_candidates(j, ROWS, live_instances=set())
    assert [c["session_uuid"] for c in got] == ["X"]


def test_an_explicit_decline_is_still_remembered_per_instance():
    j = _journal_live(ROWS[:4], T0)
    cands = offer_candidates(j, ROWS, live_instances=set())
    j["offer"] = build_offer(cands, reason=REASON_TMUX_SERVER_GONE, now_iso=T0, boot_epoch=BOOT, previous_boot_epoch=BOOT)
    assert decline(j, j["offer"]["id"], T0)
    assert offer_candidates(j, ROWS, live_instances=set()) == []


def test_fold_keeps_one_candidate_per_row_and_prefers_the_new_instance():
    prev = build_offer(offer_candidates(_journal_live([OLD_ROW], OLD), [OLD_ROW], live_instances=set()),
                       reason=REASON_SESSIONS_GONE, now_iso=OLD, boot_epoch=BOOT, previous_boot_epoch=BOOT)
    reborn = dict(OLD_ROW, tmux_created_epoch=99, lifecycle="running", lifecycle_source="create")
    fresh = offer_candidates(_journal_live([reborn], T0), [reborn], live_instances=set())
    offer, minted = fold_offer(prev, fresh, reason=REASON_TMUX_SERVER_GONE, now_iso=T0, boot_epoch=BOOT)
    assert minted and [c["instance"] for c in offer["candidates"]] == [instance_key("cloude_x", 99)]


def test_fold_with_nothing_open_and_nothing_lost_is_none():
    assert fold_offer(None, [], reason=REASON_TMUX_SERVER_GONE, now_iso=T0, boot_epoch=BOOT) == (None, False)


def test_folder_trust_reads_parents_and_refuses_to_guess(tmp_path):
    assert folder_trust("/a/b/c", {"/a/b/c": False}) == TRUST_WILL_ASK
    assert folder_trust("/a/b/c", {"/a": True, "/a/b/c": False}) == TRUST_TRUSTED
    assert folder_trust("/a/b/c", {}) == TRUST_WILL_ASK
    assert folder_trust("/a/b/c", None) == TRUST_UNKNOWN
    assert folder_trust(None, {"/": True}) == TRUST_UNKNOWN
    f = tmp_path / "claude.json"
    f.write_text('{"projects": {"/p": {"hasTrustDialogAccepted": true}, "/q": {}}}')
    before = f.read_bytes()
    assert load_trust_map(f) == {"/p": True, "/q": False}
    assert f.read_bytes() == before, "the file is read, never written"
    assert load_trust_map(tmp_path / "missing.json") is None
    (tmp_path / "bad.json").write_text("{")
    assert load_trust_map(tmp_path / "bad.json") is None


def test_the_startup_look_is_bounded_and_matches_only_the_dialog():
    tails = {"t": "Quick safety check: Is this a project you created or one you trust?",
             "n": "  ? for shortcuts", "u": None}
    calls = []
    clock = {"t": 0.0}

    def capture(*, socket, name, lines):
        calls.append(name)
        return tails[name]

    def sleep(s):
        clock["t"] += s

    got = watch_for_startup_prompts(["t", "n", "u"], socket="s", window=3.0, interval=1.0,
                                    capture=capture, clock=lambda: clock["t"], sleep=sleep)
    assert got == {"t": True, "n": False, "u": None}
    assert calls.count("t") == 1, "a matched pane is not read again"
    assert calls.count("n") <= 4 and clock["t"] <= 3.0, "the window bounds the look"
