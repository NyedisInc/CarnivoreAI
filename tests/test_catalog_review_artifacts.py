
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_ra_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_ra_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.api.catalog_views import item_view
from src.core.catalog.index_snapshot import EMPTY_SNAPSHOT
from src.models.catalog import CatalogItem, ReviewBlock

ARTIFACTS_PATH = ROOT / "tests" / "fixtures" / "catalog_review_artifacts.json"

ARTIFACTS = json.loads(ARTIFACTS_PATH.read_text(encoding="utf-8"))

EXPECTED_VERDICTS = {
    "fixture_blocked": "blocked",
    "fixture_blocked_with_override": "blocked",
    "live_skill_clean": "clean",
    "live_skill_blocked": "blocked",
    "live_skill_unavailable": None,
}


def artifact(name: str) -> dict:
    if name not in ARTIFACTS:
        raise AssertionError(f"the artifacts file carries no {name}")
    return ARTIFACTS[name]


def _item_carrying(review: dict) -> CatalogItem:
    return CatalogItem.model_validate(
        {
            "id": "alex/sme",
            "kind": "skill",
            "name": "sme",
            "publisher": "alex",
            "latest": "1.0.0",
            "card": {"title": "sme", "brief": "the sme skill"},
            "fm": {"description": "the sme skill"},
            "versions": [
                {
                    "v": "1.0.0",
                    "src": {
                        "repo": "carnivore-ai/catalog",
                        "path": "skills/alex/sme",
                        "commit": "a" * 40,
                    },
                    "digest": "b" * 64,
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
                    "review": review,
                }
            ],
        }
    )


def _round_tripped(review: dict) -> dict:
    view = item_view(
        _item_carrying(review),
        installed=None,
        snapshot=EMPTY_SNAPSHOT,
        untrusted=False,
    )
    return view.versions[0]["review"]


class TestTheFileItself:

    def test_all_five_documents_are_there(self):
        assert set(ARTIFACTS) == set(EXPECTED_VERDICTS)

    @pytest.mark.parametrize("name", sorted(EXPECTED_VERDICTS))
    def test_each_one_is_bound_to_a_version_by_a_digest(self, name):
        digest = artifact(name)["digest"]
        assert isinstance(digest, str)
        assert len(digest) == 64
        assert digest == digest.lower()


class TestEveryDocumentParses:

    @pytest.mark.parametrize("name", sorted(EXPECTED_VERDICTS))
    def test_it_parses_and_states_the_verdict_it_carries(self, name):
        block = ReviewBlock.model_validate(artifact(name))
        assert block.verdict == EXPECTED_VERDICTS[name]

    @pytest.mark.parametrize("name", sorted(EXPECTED_VERDICTS))
    def test_the_digest_it_carries_is_ignored_not_refused(self, name):
        assert "digest" in artifact(name)
        assert not hasattr(ReviewBlock.model_validate(artifact(name)), "digest")


class TestTheCleanDocument:

    def test_it_reads_clean_over_a_measured_zero_findings(self):
        block = ReviewBlock.model_validate(artifact("live_skill_clean"))
        assert block.status == "reviewed"
        assert block.verdict == "clean"
        assert block.warnings == []
        assert block.override is None

    def test_it_survives_the_round_trip_clean(self):
        payload = _round_tripped(artifact("live_skill_clean"))
        assert payload["verdict"] == "clean"
        assert payload["status"] == "reviewed"
        assert payload["warnings"] == []


class TestTheBlockedDocument:

    def test_the_finding_keeps_its_kind_file_and_line(self):
        block = ReviewBlock.model_validate(artifact("live_skill_blocked"))
        assert block.verdict == "blocked"
        assert len(block.warnings) == 1
        warning = block.warnings[0]
        assert warning.kind == "prompt_injection"
        assert warning.file == "SKILL.md"
        assert warning.line == 7

    def test_the_file_and_line_REACH_THE_BROWSER(self):
        payload = _round_tripped(artifact("live_skill_blocked"))
        assert payload["verdict"] == "blocked"
        assert payload["warnings"][0]["kind"] == "prompt_injection"
        assert payload["warnings"][0]["file"] == "SKILL.md"
        assert payload["warnings"][0]["line"] == 7

    def test_prompt_injection_is_a_kind_this_build_carries(self):
        assert ReviewBlock.model_validate(artifact("live_skill_blocked")).warnings[0].kind

    def test_the_gate_emitted_three_credential_findings(self):
        block = ReviewBlock.model_validate(artifact("fixture_blocked"))
        assert block.verdict == "blocked"
        assert [w.kind for w in block.warnings] == ["credential_access"] * 3
        assert [w.line for w in block.warnings] == [6, 7, 8]
        assert {w.file for w in block.warnings} == {"SKILL.md"}


class TestTheOverride:

    def test_the_override_never_changes_the_verdict(self):
        block = ReviewBlock.model_validate(artifact("fixture_blocked_with_override"))
        assert block.verdict == "blocked"
        assert block.override is not None
        assert block.override.reason == "corpus fixture, never published"
        assert block.override.by == "psyance"

    def test_the_reason_reaches_the_browser(self):
        payload = _round_tripped(artifact("fixture_blocked_with_override"))
        assert payload["verdict"] == "blocked"
        assert payload["override"]["reason"] == "corpus fixture, never published"

    def test_NEGATIVE_CONTROL_the_same_document_without_one_has_no_override(self):
        block = ReviewBlock.model_validate(artifact("fixture_blocked"))
        assert block.override is None
        assert _round_tripped(artifact("fixture_blocked"))["override"] is None


class TestTheUnavailableDocument:

    def test_it_carries_no_verdict_at_all(self):
        block = ReviewBlock.model_validate(artifact("live_skill_unavailable"))
        assert block.status == "unavailable"
        assert block.verdict is None

    def test_and_None_IS_NOT_clean(self):
        block = ReviewBlock.model_validate(artifact("live_skill_unavailable"))
        assert block.verdict != "clean"
        assert _round_tripped(artifact("live_skill_unavailable"))["verdict"] is None

    def test_it_carries_no_findings_and_no_summary_either(self):
        block = ReviewBlock.model_validate(artifact("live_skill_unavailable"))
        assert block.warnings is None
        assert block.summary is None
