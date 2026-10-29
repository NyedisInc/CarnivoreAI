
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

import structlog

from src.core import claude_rename_retry_store as store
from src.core.claude_rename_retry import (
    RETRY_PUSH,
    RetryDecision,
    decide_retry,
    record_agreement,
    record_attempt,
    witness_agreement,
)

logger = structlog.get_logger(__name__)

RETRY_PUSH_REFUSED: str = "push_refused"

RETRY_NO_BINARY: str = "no_binary"

RETRY_DISABLED: str = "disabled"

ENABLE_ENV: str = "CLOUDE_RENAME_RETRY"


def retry_enabled() -> bool:
    raw = os.environ.get(ENABLE_ENV)
    if raw is not None:
        return raw.strip().lower() not in ("", "0", "false", "no", "off")
    return not os.environ.get("CLOUDE_TEST_MODE")


def _families_agree(agent_family: Optional[str]) -> bool:
    return agent_family in (None, "", "claude")


def run_rename_retry(
    *,
    session_id: str,
    row_id: int,
    title: Optional[str],
    claude_title: Optional[str],
    claude_uuid: Optional[str],
    agent_family: Optional[str],
    sync_action: str,
    now: Optional[float] = None,
    state_dir: Optional[Path] = None,
) -> RetryDecision:
    if not retry_enabled():
        return RetryDecision(
            RETRY_DISABLED,
            detail=f"{ENABLE_ENV} is off, so no rename retry ran",
        )

    key = f"{claude_uuid or 'none'}:{row_id}"
    at = float(now if now is not None else time.time())
    where = state_dir if state_dir is not None else store.resolve_state_dir()

    agreed = witness_agreement(title=title, claude_title=claude_title)
    mark = store.mark_for(where, key)
    if agreed is not None and (mark is None or mark.agreed_title != agreed
                               or mark.attempted_label is not None):
        mark = record_agreement(mark, agreed)
        store.save_mark(where, key, mark)

    decision = decide_retry(
        sync_action=sync_action,
        title=title,
        claude_title=claude_title,
        mark=mark,
        now=at,
    )
    if decision.verdict != RETRY_PUSH or not decision.label:
        return decision

    if not claude_uuid:
        return RetryDecision(
            RETRY_PUSH_REFUSED,
            label=decision.label,
            attempts_spent=decision.attempts_spent,
            detail="no conversation uuid is bound, so --resume has nothing to address",
        )

    try:
        return _push(
            session_id=session_id,
            key=key,
            decision=decision,
            claude_uuid=str(claude_uuid),
            agent_family=agent_family,
            mark=mark,
            at=at,
            where=where,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "rename_retry_push_threw",
            session_id=session_id,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return RetryDecision(
            RETRY_PUSH_REFUSED,
            label=decision.label,
            attempts_spent=decision.attempts_spent,
            detail=f"the push raised and was contained: {exc}",
        )


def _push(
    *,
    session_id: str,
    key: str,
    decision: RetryDecision,
    claude_uuid: str,
    agent_family: Optional[str],
    mark,
    at: float,
    where: Optional[Path],
) -> RetryDecision:
    from src.core.claude_rename import (
        PUSH_SENT,
        decide_push,
        detect_claude_version,
        oob_rename_argv,
        spawn_oob_rename,
    )
    from src.core.session_transcript_presence import CONVERSATION_PRESENT

    label = str(decision.label)
    try:
        outcome, reason = decide_push(
            label=label,
            claude_uuid=claude_uuid,
            claude_version=detect_claude_version(),
            is_claude_session=_families_agree(agent_family),
            transcript_presence=CONVERSATION_PRESENT,
        )
    except (ImportError, OSError, ValueError) as exc:
        logger.warning(
            "rename_retry_decide_failed", session_id=session_id, error=str(exc)
        )
        return RetryDecision(
            RETRY_PUSH_REFUSED,
            label=label,
            attempts_spent=decision.attempts_spent,
            detail=f"the push could not be decided: {exc}",
        )

    if outcome != PUSH_SENT:
        logger.info(
            "rename_retry_push_refused",
            session_id=session_id,
            outcome=outcome,
            reason=reason,
            note="no attempt spent; the cloudecode label is stored either way",
        )
        return RetryDecision(
            RETRY_PUSH_REFUSED,
            label=label,
            attempts_spent=decision.attempts_spent,
            detail=reason,
        )

    try:
        from src.core.server_status import collect_claude_cli

        claude_path = (collect_claude_cli() or {}).get("path")
    except (ImportError, OSError) as exc:
        logger.debug(
            "rename_retry_binary_unresolved", session_id=session_id, error=str(exc)
        )
        claude_path = None
    if not claude_path:
        return RetryDecision(
            RETRY_NO_BINARY,
            label=label,
            attempts_spent=decision.attempts_spent,
            detail="the claude binary could not be resolved, so nothing was run",
        )

    store.save_mark(where, key, record_attempt(mark, label=label, now=at))
    spawn_oob_rename(oob_rename_argv(claude_path, claude_uuid, label), session_id=session_id)
    logger.info(
        "rename_retry_pushed",
        session_id=session_id,
        row_id=key,
        attempt=decision.attempts_spent + 1,
        note="retry of a browser rename that had not reached claude",
    )
    return RetryDecision(
        RETRY_PUSH,
        label=label,
        attempts_spent=decision.attempts_spent + 1,
        detail=decision.detail,
    )
