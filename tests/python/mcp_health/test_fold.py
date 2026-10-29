
from datetime import datetime, timezone

from src.core.mcp_health.fold import STATE_DROPPED, STATE_FAILED, STATE_NEEDS_AUTH, extract_mcp_events
from src.core.mcp_health.fold import fold_mcp_health as _fold

from src.core.mcp_health.reconnect import ReconnectRefused, reconnect_command


def fold_mcp_health(records, since=None):
    return _fold(extract_mcp_events(records), since=since)


def _att(kind, ts="2026-10-10T10:00:00.000Z", **fields):
    return {"type": "attachment", "timestamp": ts, "attachment": {"type": kind, **fields}}


def _instr(removed=(), added=(), ts="2026-10-10T10:00:00.000Z"):
    return _att("mcp_instructions_delta", ts, removedNames=list(removed), addedNames=list(added), addedBlocks=[])


def _deferred(ts="2026-10-10T10:00:00.000Z", **kw):
    base = dict(addedNames=[], removedNames=[], addedLines=[])
    base.update(kw)
    return _att("deferred_tools_delta", ts, **base)


def test_no_mcp_record_is_none_not_empty():
    assert fold_mcp_health([]) is None
    assert fold_mcp_health([{"type": "user"}, _att("date", date="x")]) is None


def test_instruction_removal_drops_a_server_with_its_exact_name():
    health = fold_mcp_health([_instr(removed=["carnivore"])])
    assert [(d.name, d.state, d.exact) for d in health.dropped] == [("carnivore", STATE_DROPPED, True)]
    assert health.dropped[0].at is not None


def test_added_names_clears_it_and_empty_is_measured_ok():
    health = fold_mcp_health([_instr(removed=["carnivore"]), _instr(added=["carnivore"])])
    assert health is not None and health.dropped == ()


def test_tool_name_removal_drops_and_tool_name_addition_clears_across_spelling():
    gone = fold_mcp_health([_deferred(removedNames=["mcp__claude_ai_Claude_Docs__read", "ListMcpResourcesTool"])])
    assert [(d.name, d.exact) for d in gone.dropped] == [("claude_ai_Claude_Docs", False)]
    back = fold_mcp_health([_instr(removed=["claude.ai Claude Docs"]),
                            _deferred(addedNames=["mcp__claude_ai_Claude_Docs__read"])])
    assert back.dropped == ()


def test_failed_and_needs_auth_lists_win_and_pending_changes_nothing():
    health = fold_mcp_health([
        _deferred(removedNames=["mcp__a__t"], failedMcpServers=["a"], needsAuthMcpServers=["b"]),
        _deferred(pendingMcpServers=["a"]),
    ])
    assert {d.name: d.state for d in health.dropped} == {"a": STATE_FAILED, "b": STATE_NEEDS_AUTH}


def test_exact_name_survives_a_later_tool_name_removal_and_sidechains_are_ignored():
    side = _instr(removed=["ghost"])
    side["isSidechain"] = True
    health = fold_mcp_health([_instr(removed=["Claude Docs"]), _deferred(removedNames=["mcp__Claude_Docs__x"]), side])
    assert [(d.name, d.exact) for d in health.dropped] == [("Claude Docs", True)]


def test_malformed_records_never_raise():
    assert fold_mcp_health([None, 5, {"type": "attachment", "attachment": "x"},
                            _att("deferred_tools_delta", removedNames="nope")]) is None


def test_reconnect_command_picks_name_or_all_and_refuses_unmeasured():
    one = fold_mcp_health([_instr(removed=["carnivore"])])
    assert reconnect_command(one) == "/mcp reconnect carnivore"
    assert reconnect_command(one, "Carnivore") == "/mcp reconnect carnivore"
    many = fold_mcp_health([_instr(removed=["a", "b"])])
    assert reconnect_command(many) == "/mcp reconnect all"
    assert reconnect_command(many, "a") == "/mcp reconnect a"
    inexact = fold_mcp_health([_deferred(removedNames=["mcp__x__t"])])
    assert reconnect_command(inexact) == "/mcp reconnect all"
    for health, server in ((None, None), (fold_mcp_health([_instr(added=["a"])]), None), (one, "zzz")):
        try:
            reconnect_command(health, server)
        except ReconnectRefused as refusal:
            assert refusal.code
        else:
            raise AssertionError("expected a refusal")


def test_transcript_facts_carry_the_fold():
    from src.core.attention.transcript_facts import classify_transcript_records

    facts = classify_transcript_records([_instr(removed=["carnivore"])])
    assert [d.name for d in _fold(facts.mcp_events).dropped] == ["carnivore"]
    assert classify_transcript_records([]).mcp_events == ()



def _t(text):
    from datetime import datetime
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def test_daily_briefing_stays_dropped_exact_after_the_process_start():
    recs = [
        _deferred("2026-10-10T20:38:50.482Z", removedNames=["mcp__carnivore__huddle_add"],
                  failedMcpServers=[{"name": "carnivore", "errorCode": "ECONNREFUSED"}]),
        _deferred("2026-10-11T01:12:42.970Z", removedNames=["mcp__carnivore__a"], addedNames=["mcp__carnivore__a"]),
        _instr(removed=["carnivore"], ts="2026-10-11T02:12:22.115Z"),
    ]
    health = fold_mcp_health(recs, since=_t("2026-10-11T01:12:21Z"))
    assert [(d.name, d.state, d.exact) for d in health.dropped] == [("carnivore", STATE_DROPPED, True)]


def test_fleet_first_record_removals_after_resume_are_reconciliation():
    gone = [f"mcp__{n}__t" for n in ("Claude_Preview", "ccd_directory", "computer-use", "shell")]
    recs = [
        _deferred("2026-06-15T13:27:58.366Z", addedNames=gone),
        _deferred("2026-10-11T02:06:28.192Z", removedNames=gone, addedNames=["mcp__carnivore__t"]),
        _instr(removed=["computer-use"], added=["carnivore"], ts="2026-10-11T02:06:28.192Z"),
        _deferred("2026-10-11T02:14:11.114Z", addedNames=["mcp__carnivore__t"]),
    ]
    assert fold_mcp_health(recs, since=_t("2026-10-11T02:05:44Z")).dropped == ()


def test_carnivore_connector_removal_in_the_first_record_after_resume_is_clean():
    names = [f"mcp__claude_ai_{n}__t" for n in ("Gmail", "Google_Calendar", "Google_Drive")]
    recs = [
        _deferred("2026-10-10T01:24:30.672Z", addedNames=names),
        _deferred("2026-10-10T11:53:52.600Z", removedNames=names),
    ]
    assert fold_mcp_health(recs, since=_t("2026-10-10T11:50:00Z")).dropped == ()


def test_old_process_drops_before_since_never_show():
    recs = [_deferred("2026-05-19T23:31:56.244Z", removedNames=["mcp__Control_Chrome__t"]),
            _instr(removed=["plugin_claude-mem_mcp-search"], ts="2026-05-31T00:30:49.302Z")]
    assert fold_mcp_health(recs, since=_t("2026-10-10T01:19:24Z")).dropped == ()


def test_never_connected_failed_server_is_a_drop_like_needs_auth():
    recs = [_deferred("2026-10-10T15:00:30Z", failedMcpServers=[{"name": "higgsfield"}], needsAuthMcpServers=["gh"])]
    health = fold_mcp_health(recs, since=_t("2026-10-10T12:00:00Z"))
    assert {d.name: d.state for d in health.dropped} == {"higgsfield": STATE_FAILED, "gh": STATE_NEEDS_AUTH}


def test_a_connected_server_that_fails_after_start_is_failed():
    recs = [_deferred("2026-10-10T12:00:10Z", addedNames=["mcp__carnivore__t"]),
            _deferred("2026-10-10T13:00:00Z", failedMcpServers=[{"name": "carnivore"}])]
    health = fold_mcp_health(recs, since=_t("2026-10-10T12:00:00Z"))
    assert [(d.name, d.state) for d in health.dropped] == [("carnivore", STATE_FAILED)]


def test_window_that_starts_after_the_process_start_has_no_reconciliation_to_excuse():
    recs = [_instr(removed=["carnivore"], ts="2026-10-11T02:12:22.115Z")]
    assert [d.name for d in fold_mcp_health(recs, since=_t("2026-10-10T01:12:21Z")).dropped] == ["carnivore"]




def _user(content, ts):
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": content}}


def _reconnect_records(stdout, ts="2026-10-11T15:27:46.598Z"):
    return [
        _user("<local-command-caveat>Caveat: The messages below were generated by the user while running local "
              "commands.</local-command-caveat>", "2026-10-11T15:27:46.600Z"),
        _user("<command-name>/mcp</command-name>\n            <command-message>mcp</command-message>\n"
              "            <command-args>reconnect carnivore</command-args>", "2026-10-11T15:27:46.597Z"),
        _user(f"<local-command-stdout>{stdout}</local-command-stdout>", ts),
    ]


_DROP_FAILED = _deferred(
    ts="2026-10-11T14:30:00.000Z", removedNames=["mcp__carnivore__huddle_add"],
    failedMcpServers=[{"name": "carnivore", "errorCode": "ECONNREFUSED", "error": "ECONNREFUSED: x"}])
_DROP_INSTR = _instr(removed=["carnivore"], ts="2026-10-11T14:30:00.000Z")
_BASE = [_instr(added=["carnivore"], ts="2026-10-10T19:43:41.000Z")]


def test_reconnect_stdout_clears_the_drop_with_no_attachment_after_it():
    records = _BASE + [_DROP_INSTR, _DROP_FAILED] + _reconnect_records("Reconnected to carnivore.")
    health = fold_mcp_health(records)
    assert health is not None and health.dropped == ()
    assert [d.name for d in fold_mcp_health(_BASE + [_DROP_INSTR, _DROP_FAILED]).dropped] == ["carnivore"]


def test_reconnect_stdout_heals_a_content_block_list_too():
    rec = _user([{"type": "text", "text": "<local-command-stdout>Reconnected to carnivore.</local-command-stdout>"}],
                "2026-10-11T15:27:46.598Z")
    assert fold_mcp_health(_BASE + [_DROP_INSTR, rec]).dropped == ()


def test_failed_reconnect_lines_do_not_heal():
    for line in ("Reconnected to carnivore, but fetching tools failed (detail withheld on this connection).",
                 "Couldn't reconnect \"carnivore\" (failed).", "carnivore requires authentication."):
        health = fold_mcp_health(_BASE + [_DROP_INSTR] + _reconnect_records(line))
        assert [d.name for d in health.dropped] == ["carnivore"], line


def test_reconnect_all_heals_only_when_every_server_came_back():
    full = fold_mcp_health(_BASE + [_DROP_INSTR] + _reconnect_records("Reconnected 1 of 1 MCP server"))
    assert full.dropped == ()
    partial = fold_mcp_health(_BASE + [_DROP_INSTR] + _reconnect_records("Reconnected 1 of 2 MCP servers"))
    assert [d.name for d in partial.dropped] == ["carnivore"]


def test_a_drop_after_the_reconnect_marks_again_and_a_stdout_is_not_a_first_record():
    records = _BASE + [_DROP_INSTR] + _reconnect_records("Reconnected to carnivore.") + [
        _instr(added=["x"], ts="2026-10-11T15:30:00.000Z"),
        _instr(removed=["carnivore"], ts="2026-10-11T15:40:00.000Z")]
    started = fold_mcp_health(records, since=datetime(2026, 10, 11, 15, 0, tzinfo=timezone.utc))
    assert [d.name for d in started.dropped] == ["carnivore"]


def test_reconnect_heals_and_listing_row_diff_carries_the_change():
    from src.api.mcp_health_listing import mcp_health_info
    from src.core.listing_push.diff import diff, keyed
    before = mcp_health_info(fold_mcp_health(_BASE + [_DROP_INSTR]))
    after = mcp_health_info(fold_mcp_health(_BASE + [_DROP_INSTR] + _reconnect_records("Reconnected to carnivore.")))
    key = lambda r: r["name"]  # noqa: E731
    rows = lambda h: keyed([{"name": "s", "mcp_health": h.model_dump(mode="json")}], key)  # noqa: E731
    change = diff(rows(before), rows(after))
    assert change is not None and "mcp_health" in str(change)
    assert diff(rows(after), rows(after)) is None



def _chat(ts, kind="assistant"):
    return {"type": kind, "timestamp": ts, "message": {"role": kind, "content": []}}


def _tail_fold(records, since):
    from src.core.mcp_health.fold import window_start
    return _fold(extract_mcp_events(records), since=since, window_from=window_start(records))


def test_resume_whose_old_mcp_records_fell_out_of_the_tail_is_still_reconciliation():
    names = ["mcp__claude_ai_Gmail__authenticate", "mcp__claude_ai_Google_Calendar__authenticate",
             "mcp__claude_ai_Google_Drive__read_file_content"]
    recs = [
        _chat("2026-09-28T20:06:48.645Z"),
        _chat("2026-10-12T13:02:30.000Z", "user"),
        _deferred("2026-10-12T13:02:59.952Z", removedNames=names, addedNames=["mcp__carnivore__t"]),
        _instr(added=["carnivore"], ts="2026-10-12T13:02:59.952Z"),
    ]
    since = _t("2026-10-12T13:02:08Z")
    assert _fold(extract_mcp_events(recs), since=since).dropped != ()
    assert _tail_fold(recs, since).dropped == ()


def test_a_real_drop_after_the_first_record_still_counts_when_the_tail_cut_history():
    recs = [
        _chat("2026-09-28T20:06:48.645Z"),
        _deferred("2026-10-12T13:02:59.952Z", addedNames=["mcp__carnivore__t"]),
        _instr(removed=["carnivore"], ts="2026-10-12T14:30:00.000Z"),
    ]
    assert [d.name for d in _tail_fold(recs, _t("2026-10-12T13:02:08Z")).dropped] == ["carnivore"]


def test_a_window_wholly_after_the_process_start_applies_no_excuse():
    recs = [_deferred("2026-10-12T14:00:00.000Z", removedNames=["mcp__x__t"])]
    assert [d.name for d in _tail_fold(recs, _t("2026-10-12T13:02:08Z")).dropped] == ["x"]


def _use(ts, call_id, tool):
    return {"type": "assistant", "timestamp": ts,
            "message": {"role": "assistant", "content": [{"type": "tool_use", "id": call_id, "name": tool, "input": {}}]}}


def _result(ts, call_id, is_error=False):
    block = {"type": "tool_result", "tool_use_id": call_id, "content": "x"}
    if is_error:
        block["is_error"] = True
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": [block]}}


def test_a_successful_mcp_tool_call_heals_a_drop_and_an_errored_one_does_not():
    drop = _instr(removed=["claude.ai Gmail"], ts="2026-10-12T10:00:00.000Z")
    ok = [drop, _use("2026-10-12T10:05:00.000Z", "t1", "mcp__claude_ai_Gmail__search_threads"),
          _result("2026-10-12T10:05:02.000Z", "t1")]
    assert fold_mcp_health(ok).dropped == ()
    bad = [drop, _use("2026-10-12T10:05:00.000Z", "t1", "mcp__claude_ai_Gmail__search_threads"),
           _result("2026-10-12T10:05:02.000Z", "t1", is_error=True)]
    assert [d.name for d in fold_mcp_health(bad).dropped] == ["claude.ai Gmail"]
    not_mcp = [drop, _use("2026-10-12T10:05:00.000Z", "t1", "Bash"), _result("2026-10-12T10:05:02.000Z", "t1")]
    assert len(fold_mcp_health(not_mcp).dropped) == 1


def test_a_tool_call_before_the_drop_does_not_hide_it():
    recs = [_use("2026-10-12T09:00:00.000Z", "t1", "mcp__carnivore__t"), _result("2026-10-12T09:00:01.000Z", "t1"),
            _instr(removed=["carnivore"], ts="2026-10-12T10:00:00.000Z")]
    assert [d.name for d in fold_mcp_health(recs).dropped] == ["carnivore"]
