
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_su_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_su_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ruff: noqa: E402
from src.core.skills.ledger import (
    GLOBAL_PROJECT_PATH,
    SCOPE_GLOBAL,
    SCOPE_PROJECT,
    InstalledItem,
)
from src.core.skills.updates import (
    ALREADY_CURRENT,
    AUTO_UPDATE_OFF,
    BODY_CHANGED,
    ELIGIBILITY_REASONS,
    ELIGIBLE,
    NO_CONSENTED_BODY,
    NOT_GLOBAL,
    INSTRUCTIONS_WRITE,
    NOT_VERIFIED,
    SCRIPTS_PRESENT,
    VERSION_UNCHANGED,
    auto_update_eligible,
    update_available,
)
from src.models.catalog import ItemVersion

OLD_DIGEST = "a" * 64
NEW_DIGEST = "b" * 64
BODY_SHA = "c" * 64
COMMIT = "d" * 40


def row(**overrides) -> InstalledItem:
    fields = {
        "install_id": "i1",
        "item_id": "pub/review",
        "kind": "skill",
        "publisher": "pub",
        "name": "review",
        "version": "1.0.0",
        "digest": OLD_DIGEST,
        "scope": SCOPE_GLOBAL,
        "project_path": GLOBAL_PROJECT_PATH,
        "auto_update": True,
        "source_index_url": "https://example.invalid/index.json",
        "consented_digest": OLD_DIGEST,
        "consented_body_sha": BODY_SHA,
        "publisher_key_id": "RWkey",
        "revision": 1,
        "installed_at": "2026-09-15T00:00:00Z",
        "updated_at": "2026-09-15T00:00:00Z",
        "consent_via": "sheet",
    }
    fields.update(overrides)
    return InstalledItem(**fields)


def version(**overrides) -> ItemVersion:
    fields = {
        "v": "2.0.0",
        "src": {"repo": "o/r", "path": "skills/pub/review", "commit": COMMIT},
        "digest": NEW_DIGEST,
        "size": 10,
        "files": 1,
        "scripts": 0,
        "published_at": "2026-09-16T00:00:00Z",
        "sig": {"key_id": "RWkey", "sig": "c2ln", "tc": "", "gsig": "Z3NpZw=="},
    }
    fields.update(overrides)
    return ItemVersion(**fields)




def test_the_badge_is_the_digest_and_not_the_version_string():
    assert update_available(row(), version()) is True
    assert update_available(row(), version(digest=OLD_DIGEST)) is False


def test_a_new_version_string_over_the_same_bytes_is_not_an_update():
    assert update_available(row(version="1.0.0"), version(v="9.9.9", digest=OLD_DIGEST)) is False




def test_the_eligible_case_is_eligible():
    answer = auto_update_eligible(row(), version(), BODY_SHA, verified=True, scripts_present=False)

    assert answer.ok is True
    assert answer.reason == ELIGIBLE


def test_nothing_to_do_answers_already_current():
    answer = auto_update_eligible(
        row(), version(digest=OLD_DIGEST), BODY_SHA, verified=True, scripts_present=False
    )

    assert answer.ok is False
    assert answer.reason == ALREADY_CURRENT


def test_a_digest_change_under_the_same_version_string_is_refused():
    answer = auto_update_eligible(
        row(version="1.0.0"), version(v="1.0.0"), BODY_SHA, verified=True, scripts_present=False
    )

    assert answer.ok is False
    assert answer.reason == VERSION_UNCHANGED


def test_a_project_copy_is_never_auto_updated():
    answer = auto_update_eligible(
        row(scope=SCOPE_PROJECT, project_path="/tmp/p"),
        version(),
        BODY_SHA,
        verified=True,
        scripts_present=False,
    )

    assert answer.ok is False
    assert answer.reason == NOT_GLOBAL


def test_auto_update_off_is_refused():
    answer = auto_update_eligible(
        row(auto_update=False), version(), BODY_SHA, verified=True, scripts_present=False
    )

    assert answer.ok is False
    assert answer.reason == AUTO_UPDATE_OFF


def test_an_unverified_version_is_refused():
    answer = auto_update_eligible(row(), version(), BODY_SHA, verified=False, scripts_present=False)

    assert answer.ok is False
    assert answer.reason == NOT_VERIFIED


def test_a_version_carrying_scripts_is_refused():
    answer = auto_update_eligible(
        row(), version(scripts=1), BODY_SHA, verified=True, scripts_present=False
    )

    assert answer.ok is False
    assert answer.reason == SCRIPTS_PRESENT


def test_a_row_with_no_recorded_body_sha_is_refused():
    answer = auto_update_eligible(
        row(consented_body_sha=None), version(), BODY_SHA, verified=True, scripts_present=False
    )

    assert answer.ok is False
    assert answer.reason == NO_CONSENTED_BODY


def test_a_changed_manifest_is_refused():
    answer = auto_update_eligible(row(), version(), "f" * 64, verified=True, scripts_present=False)

    assert answer.ok is False
    assert answer.reason == BODY_CHANGED


def _review(kind: str, status: str = "reviewed") -> dict:
    return {
        "status": status,
        "verdict": "flagged",
        "warnings": [{"kind": kind, "detail": "appends to CLAUDE.md"}],
    }


def test_a_version_whose_review_edits_instruction_files_is_never_silent():
    answer = auto_update_eligible(
        row(), version(review=_review("instructions_write")), BODY_SHA,
        verified=True, scripts_present=False,
    )
    assert answer.ok is False
    assert answer.reason == INSTRUCTIONS_WRITE


def test_a_review_with_any_other_finding_still_updates_silently():
    answer = auto_update_eligible(
        row(), version(review=_review("network")), BODY_SHA,
        verified=True, scripts_present=False,
    )
    assert answer.ok is True


def test_every_reason_this_function_can_give_is_named():
    seen = {
        auto_update_eligible(row(), version(), BODY_SHA, verified=True, scripts_present=False).reason,
        auto_update_eligible(row(), version(digest=OLD_DIGEST), BODY_SHA, verified=True, scripts_present=False).reason,
        auto_update_eligible(row(version="1.0.0"), version(v="1.0.0"), BODY_SHA, verified=True, scripts_present=False).reason,
        auto_update_eligible(row(scope=SCOPE_PROJECT, project_path="/p"), version(), BODY_SHA, verified=True, scripts_present=False).reason,
        auto_update_eligible(row(auto_update=False), version(), BODY_SHA, verified=True, scripts_present=False).reason,
        auto_update_eligible(row(), version(), BODY_SHA, verified=False, scripts_present=False).reason,
        auto_update_eligible(row(), version(scripts=3), BODY_SHA, verified=True, scripts_present=False).reason,
        auto_update_eligible(row(consented_body_sha=None), version(), BODY_SHA, verified=True, scripts_present=False).reason,
        auto_update_eligible(row(), version(), "0" * 64, verified=True, scripts_present=False).reason,
        auto_update_eligible(row(), version(), BODY_SHA, verified=True, scripts_present=False, forked=True).reason,
        auto_update_eligible(row(), version(), BODY_SHA, verified=True, scripts_present=False, deprecated=True).reason,
        auto_update_eligible(row(), version(review=_review('instructions_write')), BODY_SHA, verified=True, scripts_present=False).reason,
    }

    assert seen == set(ELIGIBILITY_REASONS)


def test_a_folder_whose_manifest_declares_a_script_is_refused(tmp_path):
    answer = auto_update_eligible(
        row(), version(scripts=0), BODY_SHA, verified=True, scripts_present=True
    )

    assert answer.ok is False
    assert answer.reason == SCRIPTS_PRESENT


def test_the_caller_can_only_ever_refuse_more_than_the_signed_count_did():
    answer = auto_update_eligible(
        row(), version(scripts=3), BODY_SHA, verified=True, scripts_present=False
    )

    assert answer.ok is False
    assert answer.reason == SCRIPTS_PRESENT
