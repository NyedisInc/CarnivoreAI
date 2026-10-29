
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_cg_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_cg_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.api.catalog_views import item_view
from src.core.catalog.index_snapshot import EMPTY_SNAPSHOT
from src.models.catalog import CatalogItem, ItemVersion

COMMIT = "a" * 40
DIGEST = "b" * 64

LIVE_GRADE = {
    "grade": "B",
    "checked": 12,
    "failed": [
        {
            "rule": "description.trigger",
            "level": "recommended",
            "detail": "no stated trigger condition was found.",
        }
    ],
    "not_graded": ["compatibility.length", "metadata.shape"],
}


def _version(**overrides) -> dict:
    version = {
        "v": "1.0.0",
        "src": {
            "repo": "carnivore-ai/catalog",
            "path": "skills/acme/sme",
            "commit": COMMIT,
        },
        "digest": DIGEST,
        "size": 4096,
        "files": 3,
        "scripts": 0,
        "published_at": "2026-09-16T00:00:00Z",
        "sig": {
            "key_id": "5F522AB084F4E697",
            "sig": "c2ln",
            "tc": "timestamp:1789521723",
            "gsig": "Z3NpZw==",
        },
    }
    version.update(overrides)
    return version


def _item(**overrides) -> dict:
    item = {
        "id": "acme/sme",
        "kind": "skill",
        "name": "sme",
        "publisher": "acme",
        "latest": "1.0.0",
        "card": {"title": "sme", "brief": "the sme skill"},
        "fm": {"description": "the sme skill"},
        "versions": [_version()],
    }
    item.update(overrides)
    return item


class TestTheFieldIsTyped:

    def test_a_graded_version_keeps_every_part_of_its_grade(self):
        version = ItemVersion(**_version(grade=LIVE_GRADE))
        assert version.grade is not None
        assert version.grade.grade == "B"
        assert version.grade.checked == 12
        assert version.grade.not_graded == [
            "compatibility.length", "metadata.shape",
        ]
        assert len(version.grade.failed) == 1
        assert version.grade.failed[0].rule == "description.trigger"
        assert version.grade.failed[0].level == "recommended"

    def test_an_UNGRADED_version_says_so_and_is_never_an_F(self):
        version = ItemVersion(**_version(grade={
            "grade": "ungraded", "checked": 0, "failed": [], "not_graded": [],
        }))
        assert version.grade is not None
        assert version.grade.grade == "ungraded"
        assert version.grade.checked == 0

    def test_an_ABSENT_grade_is_None_and_is_never_fabricated(self):
        assert ItemVersion(**_version()).grade is None

    def test_a_grade_with_no_failures_keeps_its_EMPTY_list(self):
        version = ItemVersion(**_version(grade={
            "grade": "A", "checked": 12, "failed": [], "not_graded": [],
        }))
        assert version.grade is not None
        assert version.grade.failed == []


class TestALetterThisBuildHasNeverSeen:

    def test_an_unknown_letter_does_NOT_refuse_the_whole_version(self):
        version = ItemVersion(**_version(grade={
            "grade": "A+", "checked": 12, "failed": [], "not_graded": [],
        }))
        assert version.grade is not None
        assert version.grade.grade == "A+"

    def test_an_unknown_failure_LEVEL_does_not_refuse_it_either(self):
        version = ItemVersion(**_version(grade={
            "grade": "C",
            "checked": 12,
            "failed": [{"rule": "x", "level": "advisory", "detail": "d"}],
            "not_graded": [],
        }))
        assert version.grade is not None
        assert version.grade.failed[0].level == "advisory"

    def test_the_PAIRED_POSITIVE_a_real_malformed_version_IS_still_refused(self):
        import pytest

        with pytest.raises(ValueError):
            ItemVersion(**_version(digest="short", grade=LIVE_GRADE))


class TestItReachesTheBrowser:

    def test_the_grade_survives_the_parse_AND_the_view(self):
        item = CatalogItem.model_validate(
            _item(versions=[_version(grade=LIVE_GRADE)])
        )
        view = item_view(
            item, installed=None, snapshot=EMPTY_SNAPSHOT, untrusted=False
        )
        assert view.versions[0]["grade"] == LIVE_GRADE

    def test_NEGATIVE_CONTROL_an_ungraded_version_carries_no_grade_key_value(self):
        item = CatalogItem.model_validate(_item())
        view = item_view(
            item, installed=None, snapshot=EMPTY_SNAPSHOT, untrusted=False
        )
        assert view.versions[0]["grade"] is None
