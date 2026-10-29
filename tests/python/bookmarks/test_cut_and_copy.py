
from __future__ import annotations

import hashlib
import json

import pytest

from src.core.bookmarks import cut, transcript_index
from src.core.bookmarks.copy_writer import write_copy
from src.core.bookmarks.errors import EntryNotFound, TranscriptUnavailable
from tests.python.bookmarks import fixtures


@pytest.fixture
def index(tmp_path):
    return transcript_index.build_index(fixtures.write_transcript(tmp_path))


def _uuids(chain):
    return [n.uuid for n in chain]


def test_turns_follow_the_live_path_across_a_compaction_newest_first(index):
    assert [n.snippet for n in transcript_index.turns(index)] == ["third prompt", "second prompt", "first prompt"]
    assert transcript_index.latest_turn(index).uuid == "u3"
    assert index.leaf() == "a5"


def test_a_prompt_cuts_at_the_end_of_its_turn_with_parallel_results(index):
    chain = cut.kept_chain(index, "u1")
    assert _uuids(chain) == ["u1", "a1a", "a1b", "a1c", "r1", "r2", "a2", "sys1", "prog"]
    opened = {u for n in chain for u in n.tool_uses}
    assert opened <= {r for n in chain for r in n.tool_results}


def test_an_exact_point_is_completed_so_no_tool_call_is_left_open(index):
    chain = cut.kept_chain(index, "a1b")
    assert _uuids(chain) == ["u1", "a1a", "a1b", "a1c", "r1", "r2"]


def test_the_chain_stops_at_a_compact_boundary(index):
    assert _uuids(cut.kept_chain(index, "u3")) == ["cb", "cs", "u3", "a5"]
    assert _uuids(cut.kept_chain(index, "u2"))[-4:] == ["u2", "a3", "r3", "a4"]


def test_an_abandoned_branch_cuts_on_its_own_path(index):
    assert _uuids(cut.kept_chain(index, "ab1"))[-3:] == ["sys1", "ab1", "ab2"]


def test_sidechain_and_unknown_points_are_refused(index):
    for bad in ("side1", "nope"):
        with pytest.raises(EntryNotFound):
            cut.kept_chain(index, bad)


def test_the_copy_rekeys_relinks_and_leaves_the_source_byte_identical(tmp_path, index):
    before = hashlib.sha256(index.path.read_bytes()).hexdigest()
    new, path = write_copy(index, cut.kept_chain(index, "u2"), tmp_path / "dest")
    assert hashlib.sha256(index.path.read_bytes()).hexdigest() == before
    assert path.name == f"{new}.jsonl" and new != fixtures.SOURCE
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert all(r["sessionId"] == new for r in lines)
    msgs = [r for r in lines if "uuid" in r]
    assert [m["uuid"] for m in msgs] == ["u1", "a1a", "a1b", "a1c", "r1", "r2", "a2", "sys1", "u2", "a3", "r3", "a4"]
    assert msgs[0]["parentUuid"] is None
    assert all(msgs[i]["parentUuid"] == msgs[i - 1]["uuid"] for i in range(1, len(msgs)))
    assert all(m["forkedFrom"] == {"sessionId": fixtures.SOURCE, "messageUuid": m["uuid"]} for m in msgs)
    assert not any(m.get("isSidechain") for m in msgs)
    carried = [r for r in lines if r["type"] == "content-replacement"]
    assert carried == [{"type": "content-replacement", "sessionId": new, "replacements": [{"toolUseId": "t3", "path": "x"}]}]
    assert not [r for r in lines if r["type"] == "permission-mode"]


def test_the_copy_is_created_exclusively(tmp_path, index):
    chain = cut.kept_chain(index, "u1")
    new, path = write_copy(index, chain, tmp_path / "dest", new_session="22222222-2222-4222-8222-222222222222")
    first = path.read_bytes()
    with pytest.raises(TranscriptUnavailable):
        write_copy(index, chain, tmp_path / "dest", new_session=new)
    assert path.read_bytes() == first
