
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_tfid_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_tfid_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core import theme_feedback_ids
from src.core.skills.ledger_types import GLOBAL_PROJECT_PATH, SCOPE_GLOBAL, SCOPE_PROJECT, InstalledItem
from src.models.themes import ThemeManifest


def _manifest(theme_id: str, source: str, **overrides) -> ThemeManifest:
    fields = {
        "id": theme_id,
        "name": theme_id.title(),
        "description": "d",
        "cssVars": {},
        "xterm": {},
        "source": source,
    }
    fields.update(overrides)
    return ThemeManifest(**fields)


def _installed(
    item_id: str,
    name: str,
    *,
    kind: str = "theme",
    publisher: str = "example-owner",
    scope: str = SCOPE_GLOBAL,
    project_path: str = GLOBAL_PROJECT_PATH,
) -> InstalledItem:
    return InstalledItem(
        install_id="i1",
        item_id=item_id,
        kind=kind,
        publisher=publisher,
        name=name,
        version="1.0.0",
        digest="deadbeef",
        scope=scope,
        project_path=project_path,
        auto_update=False,
        source_index_url="https://catalog.test.invalid/v1/index.json",
        consented_digest=None,
        consented_body_sha=None,
        publisher_key_id="KEY1",
        revision=1,
        installed_at="2026-09-22T00:00:00Z",
        updated_at="2026-09-22T00:00:00Z",
        consent_via="sheet",
    )


class TestABundledThemeAlwaysGetsTheReservedId:

    def test_a_bundled_manifest_gets_bundled_slash_its_own_id(self):
        out = theme_feedback_ids.stamp([_manifest("matrix", "builtin")], [])
        assert out[0].feedbackItemId == "bundled/matrix"

    def test_a_bundled_theme_never_carries_a_publisher(self):
        row = _installed("example-owner/matrix", "matrix")
        out = theme_feedback_ids.stamp([_manifest("matrix", "builtin")], [row])
        assert out[0].publisher is None
        assert out[0].feedbackItemId == "bundled/matrix"

    def test_PAIRED_POSITIVE_a_user_theme_with_no_match_carries_neither(self):
        out = theme_feedback_ids.stamp([_manifest("homemade", "user")], [])
        assert out[0].feedbackItemId is None
        assert out[0].publisher is None


class TestAUserThemeInstalledFromTheCatalog:

    def test_a_matching_ledger_row_supplies_both_fields(self):
        row = _installed("example-owner/matrix-x", "matrix-x")
        out = theme_feedback_ids.stamp([_manifest("matrix-x", "user")], [row])
        assert out[0].feedbackItemId == "example-owner/matrix-x"
        assert out[0].publisher == "example-owner"

    def test_a_hand_made_theme_with_no_ledger_row_carries_neither(self):
        out = theme_feedback_ids.stamp([_manifest("scratch", "user")], [])
        assert out[0].feedbackItemId is None
        assert out[0].publisher is None

    def test_a_skill_row_with_the_same_folder_name_is_IGNORED(self):
        skill_row = _installed("example-owner/matrix", "matrix", kind="skill")
        out = theme_feedback_ids.stamp([_manifest("matrix", "user")], [skill_row])
        assert out[0].feedbackItemId is None
        assert out[0].publisher is None

    def test_PAIRED_POSITIVE_a_theme_row_with_that_same_name_DOES_answer(self):
        theme_row = _installed("example-owner/matrix", "matrix", kind="theme")
        out = theme_feedback_ids.stamp([_manifest("matrix", "user")], [theme_row])
        assert out[0].feedbackItemId == "example-owner/matrix"

    def test_a_project_scoped_row_with_the_same_name_is_IGNORED(self):
        row = _installed(
            "example-owner/matrix", "matrix", scope=SCOPE_PROJECT, project_path="/a/b"
        )
        out = theme_feedback_ids.stamp([_manifest("matrix", "user")], [row])
        assert out[0].feedbackItemId is None


class TestATheme_jsonCannotForgeEitherField:

    def test_a_manifest_claiming_a_feedback_id_is_overwritten_to_null(self):
        out = theme_feedback_ids.stamp(
            [_manifest("scratch", "user", feedbackItemId="example-owner/sme")], []
        )
        assert out[0].feedbackItemId is None

    def test_a_manifest_claiming_a_publisher_is_overwritten_to_null(self):
        out = theme_feedback_ids.stamp(
            [_manifest("scratch", "user", publisher="somebody-else")], []
        )
        assert out[0].publisher is None

    def test_a_bundled_manifest_claiming_a_publisher_still_gets_none(self):
        out = theme_feedback_ids.stamp(
            [_manifest("matrix", "builtin", publisher="somebody-else")], []
        )
        assert out[0].publisher is None
        assert out[0].feedbackItemId == "bundled/matrix"


class TestOrderAndIdentityAreUnaffected:

    def test_the_order_and_count_are_preserved(self):
        manifests = [
            _manifest("a", "builtin"),
            _manifest("b", "user"),
            _manifest("c", "user"),
        ]
        out = theme_feedback_ids.stamp(manifests, [])
        assert [m.id for m in out] == ["a", "b", "c"]

    def test_an_empty_manifest_list_answers_empty(self):
        assert theme_feedback_ids.stamp([], []) == []
