
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_rv_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_rv_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.api.catalog_views import item_view
from src.core.catalog.index_snapshot import EMPTY_SNAPSHOT
from src.models.catalog import CatalogItem, ItemVersion, ReviewBlock

COMMIT = "a" * 40
DIGEST = "b" * 64

BLOCKED_REVIEW = {
    "status": "reviewed",
    "verdict": "blocked",
    "summary": "it reads the user's aws credentials before deploying.",
    "warnings": [
        {
            "kind": "credential_access",
            "detail": "SKILL.md instructs the agent to cat ~/.aws/credentials.",
            "file": "SKILL.md",
            "line": 12,
        }
    ],
    "model": "google/gemini-2.5-flash-lite",
    "reviewed_at": "2026-09-19T00:00:00Z",
    "override": {
        "reason": "internal fixture, published deliberately for the test corpus.",
        "by": "acme",
        "at": "2026-09-19T00:05:00Z",
    },
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
        "published_at": "2026-09-19T00:00:00Z",
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


class TestTheVerdictIsTyped:

    @pytest.mark.parametrize("verdict", ["clean", "flagged", "blocked"])
    def test_each_verdict_in_the_closed_list_parses(self, verdict):
        block = ReviewBlock(status="reviewed", verdict=verdict, warnings=[])
        assert block.verdict == verdict

    def test_a_verdict_OUTSIDE_the_closed_list_is_refused(self):
        for bad in ["clen", "passed", "CLEAN", "", "ok"]:
            with pytest.raises(ValidationError):
                ReviewBlock(status="reviewed", verdict=bad, warnings=[])

    def test_a_NON_STRING_verdict_is_refused_too(self):
        for bad in [42, True, ["clean"], {"verdict": "clean"}]:
            with pytest.raises(ValidationError):
                ReviewBlock(status="reviewed", verdict=bad, warnings=[])

    def test_an_ABSENT_verdict_parses_and_is_None(self):
        block = ReviewBlock(
            status="reviewed",
            summary="nothing damaging was found.",
            warnings=[],
            model="google/gemini-2.5-flash-lite",
            reviewed_at="2026-09-16T01:23:43Z",
        )
        assert block.verdict is None

    def test_an_UNAVAILABLE_review_has_no_verdict_and_none_is_fabricated(self):
        block = ReviewBlock(status="unavailable")
        assert block.verdict is None
        assert block.warnings is None
        assert block.override is None


class TestTheFourNewWarningKinds:

    @pytest.mark.parametrize(
        "kind",
        [
            "network",
            "file_delete",
            "credential_access",
            "shell_exec",
            "obfuscation",
            "privilege",
            "other",
            "prompt_injection",
            "settings_write",
            "description_mismatch",
            "opaque_payload",
            "instructions_write",
        ],
    )
    def test_every_kind_the_builder_may_write_parses(self, kind):
        block = ReviewBlock(
            status="reviewed",
            verdict="flagged",
            warnings=[{"kind": kind, "detail": "a sentence"}],
        )
        assert block.warnings[0].kind == kind

    def test_an_UNKNOWN_kind_from_a_newer_build_PARSES_and_keeps_its_verdict(self):
        for verdict in ("flagged", "blocked"):
            block = ReviewBlock(
                status="reviewed",
                verdict=verdict,
                warnings=[{"kind": "future_kind", "detail": "d"}],
            )
            assert block.warnings[0].kind == "future_kind"
            assert block.verdict == verdict

    @pytest.mark.parametrize("kind", ["a2a_forward", "mcp_v2_write", "kind1"])
    def test_a_kind_with_a_digit_parses_and_the_item_stays_listed(self, kind):
        block = ReviewBlock(
            status="reviewed",
            verdict="flagged",
            warnings=[{"kind": kind, "detail": "d"}],
        )
        assert block.warnings[0].kind == kind

    @pytest.mark.parametrize(
        "kind", ["", "Has-Caps", "with space", "x" * 65, "a/b", "a-b"]
    )
    def test_a_kind_outside_the_bounded_shape_is_still_refused(self, kind):
        with pytest.raises(ValidationError):
            ReviewBlock(
                status="reviewed",
                verdict="flagged",
                warnings=[{"kind": kind, "detail": "d"}],
            )


class TestFileAndLine:

    def test_a_finding_keeps_its_file_and_its_line(self):
        block = ReviewBlock(**BLOCKED_REVIEW)
        assert block.warnings[0].file == "SKILL.md"
        assert block.warnings[0].line == 12

    def test_a_finding_with_NO_LINE_is_kept_whole(self):
        block = ReviewBlock(
            status="reviewed",
            verdict="flagged",
            warnings=[{"kind": "network", "detail": "fetches mdn", "file": "SKILL.md"}],
        )
        assert block.warnings[0].file == "SKILL.md"
        assert block.warnings[0].line is None

    def test_a_finding_with_NO_FILE_is_still_accepted_by_this_reader(self):
        block = ReviewBlock(
            status="reviewed",
            verdict="flagged",
            warnings=[{"kind": "network", "detail": "calls out"}],
        )
        assert block.warnings[0].file is None
        assert block.warnings[0].line is None


class TestTheOverride:

    def test_an_override_keeps_its_reason_its_author_and_its_time(self):
        block = ReviewBlock(**BLOCKED_REVIEW)
        assert block.override is not None
        assert block.override.reason.startswith("internal fixture")
        assert block.override.by == "acme"
        assert block.override.at == "2026-09-19T00:05:00Z"

    def test_an_override_with_NO_REASON_is_refused(self):
        for bad in [{}, {"by": "someone"}, {"reason": ""}, {"reason": "   "}]:
            with pytest.raises(ValidationError):
                ReviewBlock(
                    status="reviewed", verdict="blocked", warnings=[], override=bad
                )

    def test_an_ABSENT_override_is_None_and_is_never_fabricated(self):
        block = ReviewBlock(status="reviewed", verdict="blocked", warnings=[])
        assert block.override is None


class TestItReachesTheBrowser:

    def test_the_whole_verdict_block_survives_the_parse_AND_the_view(self):
        item = CatalogItem.model_validate(
            _item(versions=[_version(review=BLOCKED_REVIEW)])
        )
        view = item_view(item, installed=None, snapshot=EMPTY_SNAPSHOT, untrusted=False)
        review = view.versions[0]["review"]
        assert review["verdict"] == "blocked"
        assert review["warnings"][0]["file"] == "SKILL.md"
        assert review["warnings"][0]["line"] == 12
        assert review["override"]["reason"].startswith("internal fixture")
        assert review["override"]["by"] == "acme"

    def test_NEGATIVE_CONTROL_a_verdictless_review_carries_no_verdict_out(self):
        item = CatalogItem.model_validate(
            _item(versions=[_version(review={"status": "reviewed", "warnings": []})])
        )
        view = item_view(item, installed=None, snapshot=EMPTY_SNAPSHOT, untrusted=False)
        review = view.versions[0]["review"]
        assert review["verdict"] is None
        assert review["override"] is None
