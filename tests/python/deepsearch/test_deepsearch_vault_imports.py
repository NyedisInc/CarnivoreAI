
from __future__ import annotations

from src.cplugs.save.vault import adopt
from src.cplugs.save.vault.old_sources import review
from tests.python.cplugs.save.old_sources_helpers import incoming_point
from tests.python.deepsearch.helpers import rec
from tests.python.deepsearch.test_deepsearch_vault_read import _again, _groups, _register, rig  # noqa: F401

SHOWN, HELD_BACK = "11111111-aaaa-bbbb-cccc-000000000001", "22222222-aaaa-bbbb-cccc-000000000002"


def _import(rig, unit: str, word: str, labels: list) -> None:
    data = rec(0, f"this import talks about {word}") + rec(1, f"{word} again", "assistant")
    point = incoming_point(unit, data, tags={"imported": True, "labels": labels})
    assert adopt.adopt_points(rig.vault, [point], lambda _entry: None)[0].status == "adopted"


def test_a_junk_labeled_import_is_searchable_only_after_the_once_over_keeps_it(rig) -> None:
    _import(rig, SHOWN, "zebraprotocol", [])
    _import(rig, HELD_BACK, "quaggaprotocol", ["junk-20260930:trivial"])
    _register(rig)
    _again(rig)
    (shown,) = _groups(rig.world, "zebraprotocol")
    assert shown["conversation_id"] == SHOWN and all(hit["from_backup"] for hit in shown["hits"])
    assert _groups(rig.world, "quaggaprotocol") == []
    review.add_verdicts(rig.vault, [HELD_BACK], "junk", "20261022")
    _again(rig)
    assert _groups(rig.world, "quaggaprotocol") == []
    review.add_verdicts(rig.vault, [HELD_BACK], "keep", "20261023")
    _again(rig)
    (kept,) = _groups(rig.world, "quaggaprotocol")
    assert kept["conversation_id"] == HELD_BACK and all(hit["from_backup"] for hit in kept["hits"])
