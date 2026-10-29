
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

import structlog

from src.core.approvals import beast_grid, beast_policy
from src.core.mcp import pending
from src.core.mcp.caller import AgentCaller

logger = structlog.get_logger()
toggle_lock = asyncio.Lock()

RETAINED_APPROVALS = frozenset({"crosstalk_resume"})
AGENT_ACTIONS = frozenset({
    "session_create", "session_send_message", "session_send_keys", "session_restart",
    "session_stop", "session_notes_put", "crosstalk_send",
    "crosstalk_reply", "agent_spawn", "agent_fork", "swarm_spawn",
})
ALWAYS_WAITS = frozenset({
    "session_delete", "session_purge", "bookmark_rewind", "swarm_rewind", "project_pack", "project_unpack", "project_delete",
    "dashboard_delete", "pipeline_plugin_rebuild", "company_delete", "mod_remove", "automation_delete", "messaging_binding_delete",
    "swarm_card_delete",
    "pack_gh_login_add",
    "project_publish_repo", "cplug_update",
    "plugin_sideload_add", "plugin_sideload_remove",
    "computer_invite", "computer_remove", "computer_leave", "computer_add",
    "api_key_delete",
})


WIDENED_ACTIONS = frozenset({
    "project_rename", "project_move", "bookmark_branch", "mod_enabled_set", "company_color_set", "company_create", "company_rename",
    "company_parent_set", "company_hq_set", "messaging_conversation_add", "messaging_binding_create", "automation_create",
    "automation_update", "automation_run_now", "automation_run_cancel", "automation_finding_fix", "automation_run_continue",
    "automation_log_settings_update", "automation_commands_set", "automation_scheduler_set",
})


def pending_eligible(item: "pending.PendingAction") -> bool:
    from src.core.mcp import in_use

    if item.confirm_text or in_use.blocks_beast(item.in_use, item.action) or not eligible_action(item.action):
        return False
    return item.beast_eligible or item.action in WIDENED_ACTIONS


def scope_tools() -> frozenset:
    from src.core.mcp import tools

    return tools.BEAST_SCOPE_TOOLS


def eligible_action(action: str) -> bool:
    if action in ALWAYS_WAITS or action in RETAINED_APPROVALS:
        return False
    return action in AGENT_ACTIONS or action in scope_tools()


def until_passed(until: Optional[str], now: Optional[datetime] = None) -> bool:
    if not until:
        return False
    try:
        end = datetime.fromisoformat(until)
    except ValueError:
        return True
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return end <= (now or datetime.now(timezone.utc))


def _config():
    from src.config import settings

    try:
        return settings.load_auth_config().mcp
    except (ValueError, OSError) as exc:
        logger.warning("beast_mode_config_unreadable", error_type=type(exc).__name__)
        return None


def stored_armed() -> bool:
    config = _config()
    return config is not None and bool(config.beast_mode) and not until_passed(config.beast_mode_until)


def stored_prompts_armed() -> bool:
    config = _config()
    return (config is not None and bool(config.beast_mode) and bool(config.beast_prompts)
            and not until_passed(config.beast_mode_until))


def beast_enabled() -> bool:
    return stored_armed()


def handles(row_id: str) -> bool:
    return beast_policy.current().handles(row_id)


def off_column_rows() -> list:
    return [row for row in beast_grid.UNCONFIRMED_ROWS if ticked_in(row, beast_grid.MODE_OFF)]


def ticked_in(row_id: str, mode: str) -> bool:
    return beast_policy.current().ticked_in(row_id, mode)


def writes_handled() -> bool:
    return handles(beast_grid.ROW_AGENT_WRITES)


def armed_but_expired() -> bool:
    config = _config()
    return config is not None and bool(config.beast_mode) and until_passed(config.beast_mode_until)


def approval_skip(action: str, *, own_dialog: bool = False) -> bool:
    return not own_dialog and eligible_action(action) and writes_handled()


def _safe_reason(exc: BaseException) -> str:
    from src.core.mcp.tools import redact_text

    return " ".join(redact_text(str(exc)).split())[:300]


async def run_unprompted(
    caller: AgentCaller, action: str, run: Callable[[], Awaitable[dict]], *,
    target_id: str = "", target_tmux: str = "", summary: str = "", args: dict | None = None,
) -> dict:
    try:
        result = await run()
    except Exception as exc:
        pending.get_store().record_beast(
            caller_session_id=caller.current_session_id, caller_tmux=caller.tmux_name,
            external_client=caller.token_name, target_session_id=target_id,
            target_tmux=target_tmux, action=action, args_summary=summary or action,
            args=args or {}, result={"status": "failed", "error_type": type(exc).__name__},
        )
        logger.warning("mcp_action_failed_under_beast_mode", action=action, error_type=type(exc).__name__,
                       reason=_safe_reason(exc))
        raise
    pending.get_store().record_beast(
        caller_session_id=caller.current_session_id, caller_tmux=caller.tmux_name,
        external_client=caller.token_name, target_session_id=target_id,
        target_tmux=target_tmux, action=action, args_summary=summary or action,
        args=args or {}, result=result,
    )
    logger.info("mcp_action_approved_by_beast_mode", action=action, caller=caller.tmux_name,
                client=caller.token_name or None, target=target_tmux or target_id)
    return result


def pending_count() -> int:
    if not ticked_in(beast_grid.ROW_AGENT_WRITES, beast_grid.MODE_ON):
        return 0
    return len(pending.get_store().beast_candidates())


async def approve_pending() -> int:
    store = pending.get_store()
    ids = [item.id for item in store.beast_candidates()] if writes_handled() else []
    approved = 0
    for action_id in ids:
        async with toggle_lock:
            if not beast_enabled() or not writes_handled():
                break
            try:
                item = store.claim_for_beast(action_id)
            except (KeyError, ValueError):
                continue
        approved += 1
        await store.execute_claimed(item)
        logger.info("mcp_pending_approved_by_beast_mode", id=action_id, action=item.action)
    return approved
