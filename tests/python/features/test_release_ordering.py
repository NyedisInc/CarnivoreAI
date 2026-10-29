
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import features  # noqa: E402


def test_version_key_reads_digit_runs_as_integers_not_characters() -> None:
    assert features._version_key("v1.12.7") == (1, 12, 7)
    assert features._version_key("v1.12.10") == (1, 12, 10)
    assert features._version_key("v1.12.18") == (1, 12, 18)
    assert features._version_key("v1.12.7") < features._version_key("v1.12.10") < features._version_key("v1.12.18")


def test_mixed_single_and_double_digit_patches_sort_newest_first() -> None:
    tags = ["v1.12.7", "v1.12.18", "v1.12.9", "v1.12.10"]
    numeric_order = sorted(tags, key=features._version_key, reverse=True)
    assert numeric_order == ["v1.12.18", "v1.12.10", "v1.12.9", "v1.12.7"]

    string_order = sorted(tags, reverse=True)
    assert string_order != numeric_order, (
        "fixture no longer distinguishes numeric from string sort; "
        "pick tags that do before trusting this test"
    )


def test_render_markdown_update_log_headings_are_newest_first_numerically() -> None:
    releases = {
        "v1.12.7": [{"type": "fixed", "summary": "old", "date": "2026-08-01"}],
        "v1.12.18": [{"type": "fixed", "summary": "new", "date": "2026-09-20"}],
        "v1.12.10": [{"type": "fixed", "summary": "mid", "date": "2026-09-01"}],
    }
    markdown = features.render_markdown(areas=[], catalog={}, releases=releases)
    headings = [line for line in markdown.splitlines() if line.startswith("### v")]
    assert headings == ["### v1.12.18", "### v1.12.10", "### v1.12.7"]
