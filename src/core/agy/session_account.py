
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.core.agy import accounts
from src.core.agy.ledger import windows_from_state
from src.core.agy.state import state_for_conversation
from src.core.provider_ledger import poller
from src.models.provider_ledger import AccountUsage, UsageWindow

logger = structlog.get_logger()

_SLOTS = {"5h": ("five_hour", "5h"), "weekly": ("seven_day", "7d")}


def _windows(state: Dict[str, Any]) -> list:
    model = state.get("model") if isinstance(state.get("model"), dict) else {}
    text = ("%s %s" % (model.get("id") or "", model.get("display_name") or "")).lower()
    family = "gemini" if "gemini" in text else "3p"
    quota = state.get("quota") if isinstance(state.get("quota"), dict) else {}
    wanted = {"%s-%s" % (family, suffix): slot for suffix, slot in _SLOTS.items()}
    kept = {key: value for key, value in quota.items() if key in wanted}
    out = []
    for window in windows_from_state({**state, "quota": kept}):
        kind, label = wanted[window.kind]
        out.append(UsageWindow(kind=kind, label=label, used_pct=window.used_pct,
                               window_seconds=window.window_seconds, resets_at=window.resets_at))
    return out


def session_account(state_dir: Path, conversation_id: Optional[str]) -> Optional[AccountUsage]:
    state = state_for_conversation(state_dir, conversation_id)
    email = state.get("email") if state else None
    if not isinstance(email, str) or not email:
        return None
    try:
        account_id = accounts.account_id_for_email(email)
        windows = _windows(state)
    except (accounts.AgyAccountError, ValueError) as exc:
        logger.debug("agy_session_account_failed", error=str(exc))
        return None
    try:
        rows = poller.snapshot().accounts
    except Exception as exc:  # noqa: BLE001
        logger.debug("agy_session_account_snapshot_failed", error=str(exc))
        rows = []
    for row in rows:
        if row.id == account_id and row.provider == "antigravity":
            return row.model_copy(update={"windows": windows})
    written = state.get("written_at")
    handle = email.split("@", 1)[0].strip() or email
    return AccountUsage(
        id=account_id, name=handle, short_name=handle, provider="antigravity", identity=email,
        plan=state.get("plan_tier") if isinstance(state.get("plan_tier"), str) else None, credential_state="ok",
        fetched_at=datetime.fromtimestamp(written, tz=timezone.utc) if isinstance(written, (int, float)) else None,
        windows=windows,
    )
