
from __future__ import annotations

from dataclasses import dataclass

import structlog

from src.core.skills.kinds import KIND_CPLUG, KIND_MOD
from src.core.skills.ledger import SCOPE_GLOBAL, InstalledItem

from src.core.skills.journal_recovery import (  # noqa: F401
    OUTCOME_ALREADY_COMPLETE,
    OUTCOME_FINISHED,
    OUTCOME_NOTHING,
    OUTCOME_REFUSED,
    OUTCOME_REVERSED,
    REFUSED_DIR_NAME,
    list_pending,
    recover_one,
    recover_pending,
    refuse_journal,
)
from src.core.skills.update_journal import (  # noqa: F401
    JOURNAL_MODE,
    STEP_SWAPPING,
    STEP_WRITTEN,
    PendingJournal,
    apply_swap,
    clear_pending,
    displaced_path,
    pending_path,
    read_pending,
    write_pending,
)
from src.models.catalog import ItemVersion, review_writes_instructions

logger = structlog.get_logger()

ELIGIBLE = "ok"
ALREADY_CURRENT = "already_current"
VERSION_UNCHANGED = "version_unchanged"
NOT_GLOBAL = "not_global"
AUTO_UPDATE_OFF = "auto_update_off"
NOT_VERIFIED = "not_verified"
SCRIPTS_PRESENT = "scripts_present"
NO_CONSENTED_BODY = "no_consented_body"
BODY_CHANGED = "body_changed"
FORKED = "forked"
DRIFTED = "drifted"
DEPRECATED = "deprecated"
INSTRUCTIONS_WRITE = "instructions_write"

ELIGIBILITY_REASONS: tuple[str, ...] = (
    ELIGIBLE,
    ALREADY_CURRENT,
    VERSION_UNCHANGED,
    NOT_GLOBAL,
    AUTO_UPDATE_OFF,
    NOT_VERIFIED,
    SCRIPTS_PRESENT,
    INSTRUCTIONS_WRITE,
    NO_CONSENTED_BODY,
    BODY_CHANGED,
    FORKED,
    DEPRECATED,
)


@dataclass(frozen=True)
class Eligibility:

    ok: bool
    reason: str




def update_available(installed: InstalledItem, latest: ItemVersion) -> bool:
    return installed.digest != latest.digest


def auto_update_eligible(
    installed: InstalledItem,
    latest: ItemVersion,
    staged_body_sha: str,
    *,
    verified: bool,
    scripts_present: bool,
    forked: bool = False,
    deprecated: bool = False,
) -> Eligibility:
    if not update_available(installed, latest):
        return Eligibility(ok=False, reason=ALREADY_CURRENT)

    if installed.version == latest.v:
        logger.warning(
            "skill_version_recut",
            item_id=installed.item_id,
            version=latest.v,
            installed_digest=installed.digest,
            latest_digest=latest.digest,
        )
        return Eligibility(ok=False, reason=VERSION_UNCHANGED)

    if installed.scope != SCOPE_GLOBAL:
        return Eligibility(ok=False, reason=NOT_GLOBAL)
    if not installed.auto_update:
        return Eligibility(ok=False, reason=AUTO_UPDATE_OFF)
    if forked:
        return Eligibility(ok=False, reason=FORKED)
    if deprecated:
        return Eligibility(ok=False, reason=DEPRECATED)
    if not verified:
        return Eligibility(ok=False, reason=NOT_VERIFIED)
    if latest.scripts > 0 or scripts_present or installed.kind in (KIND_MOD, KIND_CPLUG):
        return Eligibility(ok=False, reason=SCRIPTS_PRESENT)
    if review_writes_instructions(latest.review):
        return Eligibility(ok=False, reason=INSTRUCTIONS_WRITE)

    if installed.consented_body_sha is None:
        return Eligibility(ok=False, reason=NO_CONSENTED_BODY)
    if installed.consented_body_sha != staged_body_sha:
        return Eligibility(ok=False, reason=BODY_CHANGED)

    return Eligibility(ok=True, reason=ELIGIBLE)
