
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import HTTPException

from src.api.catalog_consent import carries_scripts
from src.api.catalog_install_support import refuse_409
from src.core.skills.install_types import (
    NAME_TAKEN,
    SCRIPTS_NOT_SUPPORTED,
    SHEET_REQUIRED,
    InstallPlan,
    InstallRefusal,
)
from src.core.skills.kinds import KIND_SKILL
from src.models.catalog import CatalogItem, ItemVersion
from src.models.catalog_api import InstallRequest

REASON_KIND = "kind_needs_sheet"
REASON_SCRIPTS = "scripts"
REASON_REVIEW = "review_not_clean"
REASON_CHOICE = "choice_given"
REASON_CONSENT = "consent_sent"
REASON_COLLISION = "name_collision"
REASON_REPLACE = "replace"
REASON_NO_SHEET_PROOF = "no_sheet_proof"

SCRIPT_EXTENSIONS = frozenset({
    ".py", ".sh", ".bash", ".zsh", ".fish", ".js", ".mjs", ".cjs", ".ts",
    ".rb", ".pl", ".php", ".ps1", ".bat", ".cmd", ".lua", ".r", ".tcl",
    ".awk", ".command",
})

_DETAILS = {
    REASON_KIND: "only a plain skill installs in one click; this kind shows the sheet",
    REASON_SCRIPTS: "this item ships executable content, which always needs a consent that names it",
    REASON_REVIEW: "the AI review for this version is missing, unavailable, or not clean",
    REASON_CHOICE: "a name choice was sent; one-click never answers a collision on its own",
    REASON_CONSENT: "a consent was sent; that is the sheet path, not one-click",
    REASON_COLLISION: "a folder of that name is already there; the sheet offers install-as or replace",
    REASON_NO_SHEET_PROOF: "no consent or preview token came with this install; the sheet has to be shown first",
    REASON_REPLACE: "this install would replace an existing folder; the sheet asks first",
}


def sheet_required(reason: str) -> HTTPException:
    return refuse_409(SHEET_REQUIRED, _DETAILS[reason], reason=reason)


def review_is_clean(version: ItemVersion) -> bool:
    review = version.review
    return (
        review is not None
        and review.status == "reviewed"
        and review.verdict == "clean"
        and review.override is None
        and not review.warnings
    )


def one_click_precheck(
    item: CatalogItem, version: ItemVersion, body: InstallRequest
) -> Optional[str]:
    if item.kind != KIND_SKILL:
        return REASON_KIND
    if carries_scripts(version):
        return REASON_SCRIPTS
    if not review_is_clean(version):
        return REASON_REVIEW
    if body.choice is not None:
        return REASON_CHOICE
    if body.consent is not None:
        return REASON_CONSENT
    return None


def sheet_answer_for_refusal(verdict: InstallRefusal) -> Optional[str]:
    if verdict.code == NAME_TAKEN:
        return REASON_COLLISION
    if verdict.code == SCRIPTS_NOT_SUPPORTED:
        return REASON_SCRIPTS
    return None


def staging_refusal_as_sheet(exc: HTTPException) -> Optional[HTTPException]:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    if exc.status_code == 409 and detail.get("code") == SCRIPTS_NOT_SUPPORTED:
        return sheet_required(REASON_SCRIPTS)
    return None


def plan_needs_sheet(verdict: InstallPlan) -> Optional[str]:
    if verdict.replaces:
        return REASON_REPLACE
    if verdict.exec_paths:
        return REASON_SCRIPTS
    return None


def staged_has_script_members(root: Path) -> bool:
    for dirpath, _dirs, files in os.walk(root, followlinks=False):
        for name in files:
            if os.path.splitext(name)[1].lower() in SCRIPT_EXTENSIONS:
                return True
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                continue
            try:
                with open(full, "rb") as handle:
                    if handle.read(2) == b"#!":
                        return True
            except OSError:
                return True
    return False
