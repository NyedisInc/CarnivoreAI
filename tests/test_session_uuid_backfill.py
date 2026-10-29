
from __future__ import annotations

from src.core.session_uuid_backfill import (
    KIND_FILL,
    KIND_REPLACE,
    OUTCOME_AMBIGUOUS,
    OUTCOME_COLLIDES,
    OUTCOME_CONFIDENT,
    OUTCOME_NO_CANDIDATE,
    OUTCOME_SOUND,
    UUID_ABSENT,
    UUID_PHANTOM,
    UUID_PRESENT,
    RowFacts,
    TranscriptFacts,
    classify_row,
    signal_families,
)
from src.core.session_uuid_backfill_rules import propose_for_row, sibling_uuid_map

NOW = 1_788_700_000.0
DIR = "-Users-x-Proj"
WD = "/Users/x/Proj"


def _t(uuid: str, **kw) -> TranscriptFacts:
    base = dict(
        path=f"/p/{DIR}/{uuid}.jsonl",
        project_dir=DIR,
        recorded_cwd=WD,
        first_ts=NOW - 10_000,
        last_ts=NOW - 100,
        mtime=NOW - 100,
    )
    base.update(kw)
    return TranscriptFacts(uuid=uuid, **base)


def _row(**kw) -> RowFacts:
    base = dict(
        row_id=1,
        working_dir=WD,
        tmux_name="cloude_Proj",
        tmux_created_epoch=int(NOW - 5_000),
    )
    base.update(kw)
    return RowFacts(**base)


def _propose(row, transcripts, **kw):
    kw.setdefault("claims", {})
    kw.setdefault("now", NOW)
    kw.setdefault("existing_dirs", [DIR])
    return propose_for_row(row, transcripts, **kw)




def test_no_candidate_when_the_transcript_genuinely_does_not_exist():
    row = _row(working_dir="/Users/x/NoSuchProject", tmux_name="cloude_Ghost")
    proposal = _propose(row, [_t("aaaa"), _t("bbbb")], existing_dirs=[DIR])

    assert proposal.outcome == OUTCOME_NO_CANDIDATE
    assert proposal.proposed_uuid is None
    assert proposal.writable is False


def test_no_candidate_when_there_are_no_transcripts_at_all():
    proposal = _propose(_row(), [])
    assert proposal.outcome == OUTCOME_NO_CANDIDATE
    assert proposal.proposed_uuid is None


def test_a_probe_transcript_is_never_a_match():
    proposal = _propose(_row(), [_t("probe", is_probe=True)])
    assert proposal.outcome == OUTCOME_NO_CANDIDATE




def test_classify_row_separates_absent_present_and_phantom():
    assert classify_row(_row(), []) == UUID_ABSENT
    assert classify_row(_row(recorded_uuid="u"), ["u"]) == UUID_PRESENT
    assert classify_row(_row(recorded_uuid="u"), ["other"]) == UUID_PHANTOM


def test_a_sound_row_is_left_entirely_alone():
    row = _row(recorded_uuid="aaaa")
    proposal = _propose(row, [_t("aaaa")])
    assert proposal.outcome == OUTCOME_SOUND
    assert proposal.writable is False




def test_pane_argv_is_decisive_even_among_many_neighbours():
    transcripts = [_t("aaaa"), _t("bbbb"), _t("cccc")]
    proposal = _propose(_row(), transcripts, argv_uuid="bbbb")

    assert proposal.outcome == OUTCOME_CONFIDENT
    assert proposal.proposed_uuid == "bbbb"
    assert proposal.kind == KIND_FILL
    assert "pane_argv" in proposal.evidence
    assert proposal.writable is True


def test_two_correlated_location_signals_do_not_clear_the_bar():
    lonely = _t("aaaa", last_ts=None, mtime=None)
    proposal = _propose(_row(), [lonely])

    assert signal_families(["project_dir", "recorded_cwd"]) == {"location"}
    assert proposal.outcome == OUTCOME_AMBIGUOUS
    assert proposal.writable is False


def test_two_independent_families_do_clear_the_bar():
    proposal = _propose(_row(), [_t("aaaa")])
    assert proposal.outcome == OUTCOME_CONFIDENT
    assert proposal.proposed_uuid == "aaaa"


def test_a_tie_between_two_qualified_candidates_is_never_broken():
    proposal = _propose(_row(), [_t("aaaa"), _t("bbbb", last_ts=NOW - 1)])
    assert proposal.outcome == OUTCOME_AMBIGUOUS
    assert set(proposal.candidates) == {"aaaa", "bbbb"}
    assert proposal.writable is False


def test_evidence_without_a_winner_is_ambiguous_not_absent():
    thin = [_t(u, last_ts=None, mtime=None) for u in ("aaaa", "bbbb")]
    proposal = _propose(_row(), thin)

    assert proposal.outcome == OUTCOME_AMBIGUOUS
    assert len(proposal.candidates) == 2




def test_a_uuid_another_row_claims_is_refused_and_reported_as_a_pair():
    row = _row(row_id=7, recorded_uuid="phantom")
    proposal = _propose(row, [_t("aaaa")], claims={"aaaa": 4}, argv_uuid="aaaa")

    assert proposal.outcome == OUTCOME_COLLIDES
    assert proposal.collides_with == 4
    assert proposal.proposed_uuid == "aaaa"
    assert proposal.writable is False


def test_a_row_does_not_collide_with_its_own_claim():
    row = _row(row_id=7, recorded_uuid="aaaa")
    proposal = _propose(row, [_t("aaaa")], claims={"aaaa": 7})
    assert proposal.outcome == OUTCOME_SOUND




def test_a_phantom_is_never_overwritten_on_timing_evidence_alone():
    row = _row(recorded_uuid="phantom")
    proposal = _propose(row, [_t("aaaa")])

    assert proposal.row_class == UUID_PHANTOM
    assert proposal.outcome == OUTCOME_AMBIGUOUS
    assert proposal.writable is False


def test_a_phantom_is_replaced_only_on_the_panes_own_argv():
    row = _row(recorded_uuid="phantom")
    proposal = _propose(row, [_t("aaaa")], argv_uuid="aaaa")

    assert proposal.outcome == OUTCOME_CONFIDENT
    assert proposal.kind == KIND_REPLACE
    assert proposal.proposed_uuid == "aaaa"




def test_sibling_rows_are_found_across_two_cwd_spellings(tmp_path):
    home = tmp_path / "home"
    real = home / "Library" / "Dev" / "Media"
    real.mkdir(parents=True)
    link = home / "Development"
    link.symlink_to(home / "Library" / "Dev")

    left = RowFacts(row_id=4, working_dir=str(real), recorded_uuid="real-uuid")
    right = RowFacts(row_id=7, working_dir=str(link / "Media"))

    assert sibling_uuid_map([left, right])[7] == {"real-uuid"}
    assert sibling_uuid_map([left, right])[4] == set()


def test_a_row_is_never_its_own_sibling():
    row = RowFacts(row_id=1, working_dir=WD, recorded_uuid="u")
    assert sibling_uuid_map([row])[1] == set()


def test_timing_alone_does_not_make_a_transcript_a_candidate():
    row = _row(working_dir="/Users/x/Elsewhere")
    proposal = _propose(row, [_t("aaaa")], existing_dirs=[DIR])

    assert proposal.outcome == OUTCOME_NO_CANDIDATE
    assert proposal.candidates == []


def test_a_title_match_alone_does_not_anchor_either():
    row = _row(working_dir="/Users/x/Elsewhere", title="Agent - Proj")
    proposal = _propose(
        row, [_t("aaaa", name="Agent - Proj")], existing_dirs=[DIR]
    )
    assert proposal.outcome == OUTCOME_NO_CANDIDATE


def test_a_single_weak_but_anchored_candidate_is_ambiguous_not_absent():
    anchored_only = _t(
        "aaaa", recorded_cwd=None, last_ts=None, mtime=None
    )
    proposal = _propose(_row(), [anchored_only])

    assert proposal.outcome == OUTCOME_AMBIGUOUS
    assert proposal.candidates == ["aaaa"]
    assert proposal.writable is False
