
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import feature_capture  # noqa: E402
import features_media  # noqa: E402


def test_script_uses_the_key_the_drawer_reads() -> None:
    ts = (REPO / "web/src/lib/drawer/resize.ts").read_text(encoding="utf-8")
    key = re.search(r"STORAGE_KEY = '([^']+)'", ts).group(1)
    assert key in feature_capture.drawer_width_script(420)
    assert "'420'" in feature_capture.drawer_width_script(420)


def test_subagent_counts_spec_is_wide_enough_and_valid() -> None:
    spec = json.loads((REPO / "features/capture/subagent-counts.json").read_text(encoding="utf-8"))
    assert spec["drawer_width"] - 27 > 300
    errors, _ = features_media.validate_capture_spec(spec, "subagent-counts", "subagent-counts.json")
    assert errors == []


def test_out_of_range_drawer_width_is_refused() -> None:
    spec = {"feature": "x", "drawer_width": 900, "shots": []}
    errors, _ = features_media.validate_capture_spec(spec, "x", "x.json")
    assert any("drawer_width" in e for e in errors)
