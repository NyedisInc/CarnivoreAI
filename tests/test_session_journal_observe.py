
from src.core.session_journal_observe import (
    EVENT_DISAGREE,
    EVENT_GONE,
    EVENT_SEEN,
    STATE_GONE,
    STATE_LIVE,
    PaneFacts,
    instance_key,
    observe,
)

T0, T1, T2 = "2026-09-23T10:00:00Z", "2026-09-23T10:00:30Z", "2026-09-23T10:06:00Z"
ROW = {"session_uuid": "U", "id": 1, "title": "t", "claude_session_uuid": "rec",
       "working_dir": "/w", "agent_type": "claude-chrome"}


def _pane(**kw):
    base = dict(name="cloude_a", epoch=7, claude_pid=10, argv="claude --chrome",
                observed_flags=["--chrome"], conversation="meas",
                conversation_source="claude_pid_record", cwd="/w")
    base.update(kw)
    return PaneFacts(**base)


def _pass(j, panes, now, complete=True, ok=True):
    return observe(j, listing_ok=ok, listing_complete=complete, panes=panes,
                   rows_by_instance={("cloude_a", 7): ROW}, groups={"U": "Agents"}, now_iso=now)


def test_first_sight_writes_and_logs_the_disagreement():
    r = _pass({"sessions": {}}, [_pane()], T0)
    entry = r.journal["sessions"][instance_key("cloude_a", 7)]
    assert r.changed and entry["state"] == STATE_LIVE and entry["group"] == "Agents"
    assert [e for e, _ in r.events] == [EVENT_SEEN, EVENT_DISAGREE]


def test_a_quiet_pass_writes_nothing():
    j = _pass({"sessions": {}}, [_pane()], T0).journal
    r = _pass(j, [_pane()], T1)
    assert not r.changed and r.events == []


def test_the_heartbeat_advances_after_five_minutes():
    j = _pass({"sessions": {}}, [_pane()], T0).journal
    r = _pass(j, [_pane()], T2)
    assert r.changed
    assert r.journal["sessions"][instance_key("cloude_a", 7)]["last_seen_live"] == T2


def test_an_incomplete_listing_ends_nothing():
    j = _pass({"sessions": {}}, [_pane()], T0).journal
    for ok, complete in ((False, False), (True, False)):
        r = _pass(j, [], T1, complete=complete, ok=ok)
        assert r.journal["sessions"][instance_key("cloude_a", 7)]["state"] == STATE_LIVE
        assert not r.changed


def test_a_complete_listing_without_it_ends_it():
    j = _pass({"sessions": {}}, [_pane()], T0).journal
    r = _pass(j, [], T1)
    entry = r.journal["sessions"][instance_key("cloude_a", 7)]
    assert r.changed and entry["state"] == STATE_GONE and entry["gone_at"] == T1
    assert [e for e, _ in r.events] == [EVENT_GONE]


def test_an_unseen_process_keeps_the_conversation_last_measured():
    j = _pass({"sessions": {}}, [_pane()], T0).journal
    r = _pass(j, [_pane(conversation=None, conversation_source=None, claude_pid=None)], T1)
    assert r.journal["sessions"][instance_key("cloude_a", 7)]["conversation_measured"] == "meas"
