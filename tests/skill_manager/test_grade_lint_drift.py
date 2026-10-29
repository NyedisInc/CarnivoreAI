
from __future__ import annotations

import hashlib
import os
import urllib.request
from pathlib import Path

import pytest

COPY = Path(__file__).resolve().parents[2] / "src" / "core" / "catalog" / "grade_lint.py"
PINNED = "6bd0cf2141e8113ea4aa498e40f221db44758bc3a25213ce4ccaad632d3175e1"
RAW = "https://raw.githubusercontent.com/NyedisInc/CarnivoreAI-Catalog/main/tools/index_builder/grade.py"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_the_copy_matches_its_pinned_digest():
    assert _sha(COPY.read_bytes()) == PINNED, "grade_lint.py was edited; it must stay a verbatim copy"


def test_the_copy_matches_the_catalog_repository():
    clone = os.environ.get("CATALOG_REPO_DIR")
    try:
        if clone:
            upstream = (Path(clone) / "tools" / "index_builder" / "grade.py").read_bytes()
        else:
            with urllib.request.urlopen(RAW, timeout=10) as answer:  # noqa: S310
                upstream = answer.read()
    except OSError as exc:
        pytest.skip(f"could not read the upstream grader: {exc}")
    assert upstream, "the upstream grader read as empty"
    assert _sha(upstream) == _sha(COPY.read_bytes()), (
        "grade_lint.py drifted from CarnivoreAI-Catalog tools/index_builder/grade.py; refresh the copy"
    )
