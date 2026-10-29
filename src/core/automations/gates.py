
from __future__ import annotations

from typing import Any, Dict, List, NamedTuple, Optional, Tuple

import structlog

from src.core.automations import models as m
from src.core.automations import pause
from src.core.automations import targets

logger = structlog.get_logger()

SPENDING_KINDS = ("agent", "recipe", "blueprint_launch", "session_message")


def spends(target: Dict[str, Any]) -> bool:
    kind = target.get("kind")
    if kind == "recipe":
        return target.get("recipe") not in m.SYSTEM_ACTIONS
    if kind == "sequence":
        return any(spends(step) for step in target.get("steps") or ())
    return kind in SPENDING_KINDS


class Verdict(NamedTuple):

    status: str
    reason: str


def login_of(target: Dict[str, Any], account_hint: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    from src.core.byoai.contracts import ByoaiError  # noqa: PLC0415
    from src.core.byoai.native import cli_run  # noqa: PLC0415
    from src.core.swarm.cards import capacity  # noqa: PLC0415

    if target.get("kind") == "sequence":
        target = (target.get("steps") or [{}])[-1]
    chosen = target.get("login_account_id") or ""
    if chosen:
        return chosen, cli_run.profile_dir("claude", chosen)
    if account_hint:
        try:
            return account_hint, cli_run.profile_dir("claude", account_hint)
        except ByoaiError:
            pass
    return capacity.account_for(None), None


def evaluate(automation: Dict[str, Any], run: Dict[str, Any], live: List[Dict[str, Any]],
             account_hint: Optional[str] = None) -> Tuple[Optional[Verdict], Dict[str, Any]]:
    notes: Dict[str, Any] = {}
    if not automation["enabled"] and run.get("trigger") != "run_now":
        return Verdict(m.SKIPPED, m.R_DISABLED), notes
    if run.get("trigger") != "run_now" and pause.is_paused():
        return Verdict(m.SKIPPED, m.R_PAUSED), notes
    others = [r for r in live if r["run_id"] != run["run_id"] and r["status"] in (m.RUNNING, m.WAITING)]
    if any(r["automation_id"] == automation["automation_id"] for r in others):
        return Verdict(m.SKIPPED, m.R_PREV_RUNNING), notes
    if len(others) >= m.MAX_LIVE_RUNS:
        return Verdict(m.SKIPPED, m.R_TWO_RUNNING), notes
    target = automation["target"]
    check = targets.VALIDATORS.get(target["kind"])
    problem = check(target) if check else None
    if problem:
        logger.info("automation_target_missing", automation_id=automation["automation_id"], problem=problem)
        return Verdict(m.FAILED, m.R_TARGET_MISSING), notes
    if not spends(target):
        return None, notes
    from src.core.byoai.contracts import ByoaiError  # noqa: PLC0415
    from src.core.byoai.native import claude_cli  # noqa: PLC0415
    from src.core.swarm.cards import capacity  # noqa: PLC0415
    from src.core.provider_ledger import refresh_guard  # noqa: PLC0415

    try:
        account_id, profile = login_of(target, account_hint)
    except ByoaiError:
        return Verdict(m.SKIPPED, m.R_LOGIN), notes
    if claude_cli._login_unusable(profile, account_id or ""):
        return Verdict(m.SKIPPED, m.R_LOGIN), notes
    spender = (target.get("steps") or [target])[-1] if target.get("kind") == "sequence" else target
    if not spender.get("api_key_connection_id"):
        usage = capacity.usage_state(account_id)
        notes["usage"] = usage.pct if usage.pct is not None else "unknown"
        if usage.floor:
            return Verdict(m.SKIPPED, m.R_USAGE), notes
    busy = refresh_guard.busy_reason(profile)
    if busy == refresh_guard.BUSY_REFRESH_LOCK:
        return Verdict(m.SKIPPED, m.R_REFRESH), notes
    if busy == refresh_guard.BUSY_CLAUDE_RUNNING:
        notes["claude_running"] = True
    return None, notes
