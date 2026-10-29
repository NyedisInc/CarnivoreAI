
from __future__ import annotations

import time

import structlog

from src.cplugs.save.pipeline_row import RECORD
from src.cplugs.save.service import RUNTIME
from src.cplugs.save.vault import units
from src.cplugs.save.vault.identity import Identity, ProjectIndex
from src.cplugs.save.vault.ingest import SourceError
from src.cplugs.save.vault.location import VaultUnavailable
from src.cplugs.save.vault.manifest import ManifestError
from src.cplugs.save.vault.store import STATUS_FAILED, STATUS_NO_FILES
from src.cplugs.sdk import save_triggers, transcript_files as tf, vault_sources

logger = structlog.get_logger()


def identity_of(save: save_triggers.LifecycleSave) -> Identity:
    facts = save.facts or {}
    identity = Identity(session_uuid=save.session_uuid, project_name=facts.get("project_name"),
                        working_dir=facts.get("working_dir"), wrapper=facts.get("wrapper"), title=facts.get("title"))
    try:
        return ProjectIndex(vault_sources.project_roots(tf.state_dir())).complete(identity)
    except vault_sources.SourceUnavailable:
        return identity


def on_save(save: save_triggers.LifecycleSave) -> None:
    timer = time.monotonic()
    failed, status, point_id = False, "", None
    try:
        vault = RUNTIME.vault()
        plan = units.plan_for(RUNTIME.sources(), save.conversation_id, save.family or units.FAMILY_CLAUDE)
        if plan is None:
            status = STATUS_NO_FILES
        else:
            outcome = vault.capture(plan, identity_of(save), save.event)
            status, point_id, failed = outcome.status, outcome.point_id, outcome.status == STATUS_FAILED
    except (VaultUnavailable, SourceError, ManifestError, OSError) as exc:
        status, failed = STATUS_FAILED, True
        logger.error("save_lifecycle_capture_failed", save_event=save.event, conversation_id=save.conversation_id,
                     error=str(exc), error_type=type(exc).__name__)
    RECORD.record_capture(failed=failed, duration_s=time.monotonic() - timer)
    logger.info("save_lifecycle_capture", save_event=save.event, conversation_id=save.conversation_id, status=status,
                point_id=point_id)
