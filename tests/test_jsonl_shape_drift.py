
from __future__ import annotations

from typing import Dict, List, Set

import pytest

from tests.jsonl_shape_rows import (
    ABOVE_WATERMARK_SQL,
    dimensions_for_row,
    fetch_exemplar,
    row_to_dict,
    signature_for_row,
)
from tests.jsonl_shape_support import (
    corpus_path,
    load_manifest,
    open_corpus_readonly,
    record_not_evaluated,
    signature_id,
)

GUARANTEE: str = (
    "no JSONL shape outside the reviewed manifest has entered the archive"
)

DRIFT_SCAN_MAX_ROWS: int = 50_000

RECIPE_MOVED: str = "none - the hashing recipe itself changed"


@pytest.fixture(scope="module")
def corpus():
    path = corpus_path()
    if path is None:
        pytest.skip(record_not_evaluated(
            GUARANTEE,
            "no corpus database is available on this machine, so NO drift "
            "scan ran and a newly ingested shape would go unreported. Set "
            "CLOUDE_FIDELITY_DB to a message-model database to scan."
        ))
    connection = open_corpus_readonly(path)
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def manifest():
    return load_manifest()


def test_no_appearance_newer_than_the_manifest_has_an_unknown_shape(
    corpus, manifest,
):
    known: Set[str] = {e["signature_id"] for e in manifest["signatures"]}
    watermark = manifest["corpus"]["watermark_max_appearance_id"]
    live_max = corpus.execute(
        "SELECT COALESCE(MAX(id), 0) FROM message_appearances"
    ).fetchone()[0]
    if live_max < watermark:
        pytest.skip(record_not_evaluated(
            GUARANTEE,
            f"this corpus's newest appearance is {live_max}, BEHIND the "
            f"manifest watermark {watermark}, so it is an older or "
            "different database and a drift scan against it would assert "
            "nothing about the archive the manifest describes"
        ))
    pending = live_max - watermark
    scanned = 0
    novel: Dict[str, Dict[str, object]] = {}
    for row in corpus.execute(ABOVE_WATERMARK_SQL, (watermark,)):
        if scanned >= DRIFT_SCAN_MAX_ROWS:
            break
        named = row_to_dict(row)
        scanned += 1
        found = signature_for_row(named)
        if found not in known and found not in novel:
            novel[found] = {
                "transcript_id": named["transcript_id"],
                "line_no": named["line_no"],
                "appearance_id": named["appearance_id"],
                "record_type": named["record_type"],
                "line_status": named["line_status"],
                "serializer_style": named["serializer_style"],
            }
    if pending > scanned:
        record_not_evaluated(
            GUARANTEE,
            f"{pending - scanned} appearances newer than id "
            f"{watermark + scanned} were NOT classified (scan capped at "
            f"{DRIFT_SCAN_MAX_ROWS} rows). Re-run the census to move the "
            "watermark forward."
        )
    assert not novel, (
        f"{len(novel)} shape(s) not present in the reviewed manifest "
        f"appeared among {scanned} newly ingested appearances. Each is "
        "UNREVIEWED, not proven broken - go look, then re-run the census "
        "to fold it in:\n" + "\n".join(
            f"  {sig}: transcript {info['transcript_id']} line "
            f"{info['line_no']} (appearance {info['appearance_id']}, "
            f"record_type {info['record_type']!r}, status "
            f"{info['line_status']!r}, style {info['serializer_style']!r})"
            for sig, info in sorted(novel.items())
        )
    )


def test_recomputed_signatures_match_the_manifest_exactly(corpus, manifest):
    entries: List[Dict[str, object]] = manifest["signatures"]
    mismatched: List[str] = []
    missing = 0
    for entry in entries:
        exemplar = entry["exemplar"]
        row = fetch_exemplar(
            corpus, exemplar["transcript_id"], exemplar["line_no"],
        )
        if row is None:
            missing += 1
            continue
        found = signature_for_row(row)
        if found != entry["signature_id"]:
            differing = sorted(
                key for key, value in dimensions_for_row(row).items()
                if value != entry["dimensions"].get(key)
            )
            moved = ", ".join(differing) if differing else RECIPE_MOVED
            mismatched.append(
                f"  {entry['signature_id']} recomputed as {found} "
                f"(dimensions that moved: {moved})"
            )
    assert not mismatched, (
        f"{len(mismatched)} of {len(entries)} signatures no longer "
        "recompute to their recorded id, so the drift check above is "
        "measuring something other than what the manifest describes:\n"
        + "\n".join(mismatched[:20])
    )
    assert missing == 0, (
        f"{missing} manifest exemplars resolved to no row in this corpus"
    )


def test_the_membership_check_can_reject_a_new_shape(manifest):
    known: Set[str] = {e["signature_id"] for e in manifest["signatures"]}
    entry = manifest["signatures"][0]
    dimensions = dict(entry["dimensions"])
    assert signature_id(dimensions) == entry["signature_id"], (
        "the manifest's own dimensions do not rehash to its own id"
    )
    assert entry["signature_id"] in known
    dimensions["record_type"] = "__a_record_type_that_does_not_exist__"
    assert signature_id(dimensions) not in known, (
        "a fabricated shape was reported as already known, so the "
        "membership test cannot detect drift and every pass is void"
    )


def test_the_manifest_watermark_is_stated_and_usable(manifest):
    corpus_meta = manifest["corpus"]
    assert corpus_meta["watermark_max_appearance_id"] > 0
    assert corpus_meta["watermark_max_body_id"] > 0
    assert corpus_meta["appearances"] == (
        corpus_meta["watermark_max_appearance_id"]
    ), "the appearance count and the watermark disagree"
    assert sum(e["count"] for e in manifest["signatures"]) == (
        corpus_meta["appearances"]
    ), "signature counts do not sum to the measured appearance total"
