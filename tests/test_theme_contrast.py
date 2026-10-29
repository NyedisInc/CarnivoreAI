from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.helpers.guard_fold import assert_no_offenders

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.contrast.audit_themes import evaluate  # noqa: E402
from scripts.contrast.color_utils import list_theme_ids  # noqa: E402
from scripts.contrast.pairings import PAIRINGS  # noqa: E402

THEME_IDS = list_theme_ids()


def test_all_twelve_bundled_themes_discovered():
    assert len(THEME_IDS) >= 12, f"expected >=12 themes, found {len(THEME_IDS)}: {THEME_IDS}"


def _check_theme_contrast_pairings_pass(theme_id):
    rows = evaluate(theme_id)
    assert len(rows) == len(PAIRINGS), (
        f"{theme_id}: evaluated {len(rows)} rows, expected {len(PAIRINGS)} "
        "(pairings.py and audit_themes.py have drifted apart)"
    )

    cannot_evaluate = [r for r in rows if r["status"] == "COULD_NOT_EVALUATE"]
    failing = [r for r in rows if r["status"] == "FAIL"]

    if cannot_evaluate:
        detail = "; ".join(f"{r['pairing']}: {r['detail']}" for r in cannot_evaluate)
        pytest.fail(f"{theme_id}: could not evaluate {len(cannot_evaluate)} pairing(s): {detail}")

    if failing:
        detail = "; ".join(
            f"{r['pairing']} ratio={r['ratio']} need={r['threshold']} ({r['detail']})"
            for r in failing
        )
        pytest.fail(f"{theme_id}: {len(failing)} pairing(s) below WCAG threshold: {detail}")


def test_theme_contrast_pairings_pass() -> None:
    assert_no_offenders(
        "theme contrast pairings pass",
        THEME_IDS,
        _check_theme_contrast_pairings_pass,
    )


def test_matrix_sidebar_specifically_readable():
    rows = evaluate("matrix")
    sidebar_rows = [r for r in rows if r["pairing"].startswith("sidebar")]
    assert sidebar_rows, "no sidebar pairings found for matrix - pairings.py lost sidebar coverage"
    for r in sidebar_rows:
        assert r["status"] == "PASS", f"matrix {r['pairing']}: {r}"
