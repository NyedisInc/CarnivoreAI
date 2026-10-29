
from src.core.boot_time import CHANGE_CANNOT_DETERMINE, CHANGE_REBOOTED, CHANGE_SAME_BOOT
from src.core.session_journal_observe import PaneFacts, instance_key, observe
from src.core.session_restore_offer import (
    OFFER_ACCEPTED,
    OFFER_DECLINED,
    REASON_REBOOT,
    REASON_SESSIONS_GONE,
    REASON_TMUX_SERVER_GONE,
    REASON_UNKNOWN_BOOT,
    build_offer,
    choose_reason,
    decline,
    offer_candidates,
    settle_accept,
)
from src.core.session_restore_rules import choose_wrapper, missing_flags, pick_conversation

T0 = "2026-09-23T10:00:00Z"


def _row(uuid, name, epoch, **kw):
    row = {"session_uuid": uuid, "tmux_name": name, "tmux_created_epoch": epoch,
           "title": name, "lifecycle": "running", "lifecycle_source": "create",
           "last_seen_running_at": T0, "archived_at": None, "claude_session_uuid": f"{uuid}-c",
           "working_dir": "/w", "agent_type": "claude-skip-permissions"}
    row.update(kw)
    return row


def _journal_with(*rows):
    panes = [PaneFacts(name=r["tmux_name"], epoch=r["tmux_created_epoch"], claude_pid=1,
                       argv="claude --dangerously-skip-permissions",
                       observed_flags=["--dangerously-skip-permissions"],
                       conversation=r["claude_session_uuid"], conversation_source="claude_pid_record",
                       cwd="/w") for r in rows]
    by = {(r["tmux_name"], r["tmux_created_epoch"]): r for r in rows}
    j = {"sessions": {}, "declined": {}, "offer": None}
    return observe(j, listing_ok=True, listing_complete=True, panes=panes,
                   rows_by_instance=by, groups={}, now_iso=T0).journal


def test_a_session_still_live_is_never_offered():
    a = _row("A", "cloude_a", 1)
    j = _journal_with(a)
    assert offer_candidates(j, [a], live_instances={("cloude_a", 1)}) == []


def test_a_journaled_session_measured_gone_is_offered_with_its_measured_conversation():
    a = _row("A", "cloude_a", 1)
    j = _journal_with(a)
    j["sessions"][instance_key("cloude_a", 1)]["conversation_measured"] = "MEASURED"
    got = offer_candidates(j, [a], live_instances=set())
    assert [c["session_uuid"] for c in got] == ["A"]
    assert got[0]["source"] == "journal" and got[0]["conversation_measured"] == "MEASURED"


def test_a_row_closed_by_the_user_is_never_offered():
    b = _row("B", "cloude_b", 2, lifecycle="stopped", lifecycle_source="closed_by_user")
    j = _journal_with(b)
    assert offer_candidates(j, [b], live_instances=set()) == []


def test_a_row_put_to_sleep_is_never_offered():
    lost = _row("S", "cloude_s", 5, lifecycle="stopped", lifecycle_source="tmux_missing")
    j = _journal_with(lost)
    assert [c["session_uuid"] for c in offer_candidates(j, [lost], live_instances=set())] == ["S"]
    slept = dict(lost, lifecycle_source="slept_by_user")
    assert offer_candidates(j, [slept], live_instances=set()) == []
    assert offer_candidates({"sessions": {}, "declined": {}}, [slept], live_instances=set(),
                            dead_instances={("cloude_s", 5)}) == []


def test_a_dead_pane_is_never_offered_and_a_server_loss_still_is():
    lost = _row("S", "cloude_s", 5, lifecycle="stopped", lifecycle_source="tmux_missing")
    j = _journal_with(lost)
    assert [c["session_uuid"] for c in offer_candidates(j, [lost], live_instances=set())] == ["S"]
    reaped = dict(lost, lifecycle_source="pane_dead")
    assert offer_candidates(j, [reaped], live_instances=set()) == []
    husk = dict(lost, lifecycle="running", lifecycle_source="create")
    assert offer_candidates(j, [husk], live_instances=set(), dead_instances={("cloude_s", 5)}) == []
    j["sessions"][instance_key("cloude_s", 5)].update(state="gone", gone_reason="pane_dead")
    assert offer_candidates(j, [husk], live_instances=set()) == []
    none = {"sessions": {}, "declined": {}}
    assert offer_candidates(none, [reaped], live_instances=set(), dead_instances={("cloude_s", 5)}) == []


def test_an_archived_row_is_never_offered():
    d = _row("D", "cloude_d", 4, lifecycle="stopped", lifecycle_source="tmux_missing",
             archived_at="2026-09-01T00:00:00Z")
    assert offer_candidates({"sessions": {}, "declined": {}}, [d], live_instances=set()) == []


def test_a_declined_offer_stays_declined():
    a = _row("A", "cloude_a", 1)
    j = _journal_with(a)
    cands = offer_candidates(j, [a], live_instances=set())
    j["offer"] = build_offer(cands, reason=REASON_REBOOT, now_iso=T0, boot_epoch=9, previous_boot_epoch=1)
    assert decline(j, j["offer"]["id"], T0)
    assert j["offer"]["state"] == OFFER_DECLINED
    assert offer_candidates(j, [a], live_instances=set()) == []
    assert not decline(j, j["offer"]["id"], T0), "a closed offer cannot be declined twice"


def test_the_same_row_dying_under_a_new_instance_is_offered_again():
    a = _row("A", "cloude_a", 1)
    j = _journal_with(a)
    declined = {"A": {"instance": instance_key("cloude_a", 1)}}
    reborn = dict(a, tmux_created_epoch=50)
    j2 = _journal_with(reborn)
    j2["declined"] = declined
    got = offer_candidates(j2, [reborn], live_instances=set())
    assert [c["instance"] for c in got] == [instance_key("cloude_a", 50)]
    j["declined"] = declined
    assert offer_candidates(j, [a], live_instances=set()) == [], "the declined instance stays declined"


def test_accepting_some_declines_nothing_and_closes_the_offer():
    a, b, c = _row("A", "cloude_a", 1), _row("B", "cloude_b", 2), _row("C", "cloude_c", 3)
    j = _journal_with(a, b, c)
    cands = offer_candidates(j, [a, b, c], live_instances=set())
    j["offer"] = build_offer(cands, reason=REASON_REBOOT, now_iso=T0, boot_epoch=9, previous_boot_epoch=1)
    results = [{"session_uuid": "A", "outcome": "reopened"}, {"session_uuid": "B", "outcome": "refused"}]
    assert settle_accept(j, j["offer"]["id"], results, T0)
    assert j["offer"]["state"] == OFFER_ACCEPTED
    assert j["declined"] == {}
    later = offer_candidates(j, [a, b, c], live_instances={("cloude_a", 1)})
    assert sorted(x["session_uuid"] for x in later) == ["B", "C"]


def test_an_open_offer_over_the_same_instances_keeps_its_id():
    a = _row("A", "cloude_a", 1)
    cands = offer_candidates(_journal_with(a), [a], live_instances=set())
    first = build_offer(cands, reason=REASON_REBOOT, now_iso=T0, boot_epoch=9, previous_boot_epoch=1)
    again = build_offer(cands, reason=REASON_REBOOT, now_iso=T0, boot_epoch=9, previous_boot_epoch=1, previous=first)
    assert again["id"] == first["id"]
    assert build_offer([], reason=REASON_REBOOT, now_iso=T0, boot_epoch=9, previous_boot_epoch=1) is None


def test_reason_words_follow_the_measurements():
    assert choose_reason(CHANGE_REBOOTED, False) == REASON_REBOOT
    assert choose_reason(CHANGE_CANNOT_DETERMINE, False) == REASON_UNKNOWN_BOOT
    assert choose_reason(CHANGE_SAME_BOOT, False) == REASON_TMUX_SERVER_GONE
    assert choose_reason(CHANGE_SAME_BOOT, True) == REASON_SESSIONS_GONE


def test_measured_conversation_outranks_the_record_and_says_so():
    assert pick_conversation("m", "r") == ("m", "measured", False)
    assert pick_conversation("m", "m") == ("m", "measured", True)
    assert pick_conversation(None, "r") == ("r", "recorded", False)
    assert pick_conversation(None, None) == (None, None, False)


SIGS = {
    "claude-skip-permissions": frozenset({"--dangerously-skip-permissions"}),
    "keyc": frozenset({"--dangerously-skip-permissions"}),
    "claude-chrome": frozenset({"--dangerously-skip-permissions", "--chrome"}),
}


def test_a_chrome_session_never_comes_back_without_chrome():
    obs = frozenset({"--dangerously-skip-permissions", "--chrome"})
    wid, _src, detail = choose_wrapper("claude-skip-permissions", obs, SIGS, "claude-skip-permissions")
    assert wid == "claude-chrome" and "record said" in detail
    assert missing_flags(obs, SIGS["claude-skip-permissions"]) == frozenset({"--chrome"})


def test_a_tie_is_broken_by_the_record_then_the_default():
    obs = frozenset({"--dangerously-skip-permissions"})
    assert choose_wrapper("keyc", obs, SIGS, "claude-skip-permissions")[0] == "keyc"
    assert choose_wrapper(None, obs, SIGS, "claude-skip-permissions")[0] == "claude-skip-permissions"


def test_no_evidence_is_named_as_a_guess():
    wid, src, _ = choose_wrapper(None, None, SIGS, "claude-skip-permissions")
    assert wid == "claude-skip-permissions" and src == "inferred_default_no_evidence"
    assert choose_wrapper(None, None, {}, None)[0] is None


def test_the_app_injected_mcp_config_neither_blocks_a_wrapper_nor_counts_as_dropped(monkeypatch):
    from src.core import session_imported_restart
    from src.core.session_agent_infer import flag_signature
    from src.core.session_journal_measure import Measurement
    from src.core.session_restore_eval import BLOCK_NO_WRAPPER, evaluate_candidate

    class _Dir:
        refuses, working_dir, detail = False, "/w", ""

    monkeypatch.setattr(session_imported_restart, "resume_directory", lambda *a, **k: _Dir())
    argv = "claude --dangerously-skip-permissions --chrome --mcp-config /x.json"
    options = [{"id": i, "label": i} for i in SIGS]
    row = _row("A", "cloude_a", 5)
    m = Measurement(listing_ok=True, listing_complete=True, listing_reason="no_server",
                    panes=[], writers=[], rows=[row], groups={}, rows_ok=True, writers_ok=True)
    legacy = ["--chrome", "--dangerously-skip-permissions", "--mcp-config"]
    for flags in (sorted(flag_signature(argv)), legacy):
        cand = {"session_uuid": "A", "instance": "cloude_a@5", "tmux_name": "cloude_a",
                "folder": "/w", "conversation_measured": None, "observed_flags": flags}
        out = evaluate_candidate(cand, row, m, (SIGS, "claude-skip-permissions", options))
        assert out["blocked"] != BLOCK_NO_WRAPPER, out["detail"]
        assert out["selectable"] is True, out
        assert out["wrapper_default"] == "claude-chrome"
        assert out["wrapper_drops"]["claude-chrome"] == []
        assert "--mcp-config" not in out["observed_flags"]


def test_a_shell_row_reopens_as_a_fresh_shell_but_a_claude_row_without_a_conversation_stays_blocked():
    from src.core.session_journal_measure import Measurement
    from src.core.session_restore_eval import BLOCK_NO_CONVERSATION, evaluate_candidate

    options = [{"id": i, "label": i} for i in SIGS]
    m = Measurement(listing_ok=True, listing_complete=True, listing_reason="no_server",
                    panes=[], writers=[], rows=[], groups={}, rows_ok=True, writers_ok=True)

    def run(**kw):
        row = _row("A", "cloude_a", 5, claude_session_uuid=None, **kw)
        cand = {"session_uuid": "A", "instance": "cloude_a@5", "tmux_name": "cloude_a",
                "folder": "/w", "conversation_measured": None, "observed_flags": None}
        return evaluate_candidate(cand, row, m, (SIGS, "claude-skip-permissions", options))

    shell = run(agent_family="shell", agent_type="shell")
    assert shell["selectable"] is True, shell
    assert shell["wrapper_default"] == "shell-default"
    assert "shell-default" in {o["id"] for o in shell["wrapper_options"]}
    assert shell["wrapper_source"] == "shell_family_default"

    claude = run(agent_family="claude")
    assert claude["selectable"] is False and claude["blocked"] == BLOCK_NO_CONVERSATION


def test_the_mini_terminal_row_as_the_database_stores_it_reopens_as_a_shell(tmp_path):
    from contextlib import closing

    from src.core.db import connect, db_path_for
    from src.core.db_migration import ensure_db_migrated
    from src.core.session_journal_measure import Measurement, read_rows
    from src.core.session_restore_eval import evaluate_candidate

    ensure_db_migrated(tmp_path, 4, "0.8.2")
    path = db_path_for(tmp_path)
    stamp = "2026-09-30T13:11:41.342525Z"
    with closing(connect(path)) as conn:
        conn.execute(
            "INSERT INTO sessions (session_uuid, origin, tmux_socket, tmux_name, "
            "tmux_created_epoch, working_dir, agent_type, agent_family, "
            "agent_family_source, claude_session_uuid, lifecycle, lifecycle_source, "
            "last_seen_running_at, title, created_at, updated_at) "
            "VALUES (?, 'adopted', 'cloude', ?, ?, ?, 'shell-default', 'shell', "
            "'launched', NULL, 'stopped', 'tmux_missing', ?, 'Mini Terminal', ?, ?)",
            ("MT", "carnivore_console-mungt8yj", 1790734040, "/Users/example", stamp, stamp, stamp),
        )
        conn.commit()

    ok, rows, groups = read_rows(path)
    assert ok and len(rows) == 1, rows
    row = rows[0]
    assert row["agent_family"] == "shell"
    m = Measurement(listing_ok=True, listing_complete=True, listing_reason="no_server",
                    panes=[], writers=[], rows=rows, groups=groups, rows_ok=True, writers_ok=True)
    cand = {"session_uuid": "MT", "instance": "carnivore_console-mungt8yj@1790734040",
            "tmux_name": "carnivore_console-mungt8yj", "folder": "/Users/example",
            "conversation_measured": None, "observed_flags": None}
    options = [{"id": i, "label": i} for i in SIGS]
    out = evaluate_candidate(cand, row, m, (SIGS, "claude-skip-permissions", options))
    assert out["selectable"] is True, out
    assert out["blocked"] is None
    assert out["wrapper_default"] == "shell-default"
    assert out["wrapper_source"] == "shell_family_default"
    assert "shell-default" in {o["id"] for o in out["wrapper_options"]}
