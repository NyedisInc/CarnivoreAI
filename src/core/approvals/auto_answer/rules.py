
from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Sequence, Tuple

import structlog

from src.core.approvals import carried_trust, dev_channels, mcp_multi
from src.core.approvals.auto_answer import catalog, mcp_installed
from src.core.approvals.extract import CHROME_ACCEPT_LABEL, CHROME_DECLINE_LABEL, DEV_CHANNELS_ACCEPT, is_chrome_prompt
from src.core.session_startup_gate import SCREEN_BYPASS_PERMISSIONS, SCREEN_MCP_SERVER, SCREEN_TRUST
from src.core.swarm.auto_trust import (GATE_AWAITING, is_claude_trust_dialog, is_plain_imports_dialog, plain_dialog_folder,
                                       shows_folder)

logger = structlog.get_logger()

ALLOW, DECLINE, WAIT, RETRY = "allow", "decline", "wait", "retry"


@dataclass(frozen=True)
class Verdict:

    outcome: str
    reason: str = ""
    evidence: str = ""
    options: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Seams:

    rows: Callable[[], Optional[Sequence[Any]]]
    lookup: Callable[[str], Optional[str]]
    lookup_imports: Callable[[str], bool]
    in_projects: Callable[[str], bool]
    mcp_installed: Callable[[str, str], bool] = mcp_installed.installed_for


@dataclass(frozen=True)
class Ctx:

    session_id: str
    dialog: Any
    pane_pid: Optional[int]
    scope: str
    info: Callable[[str], Awaitable[Any]]
    seams: Seams


Guard = Callable[[Ctx], Awaitable[Verdict]]


@dataclass(frozen=True)
class ScreenRule:

    info: catalog.RuleInfo
    matches: Callable[[Any], bool]
    label: str
    guard: Guard
    needs_gate: bool = False
    needs_pid: bool = False


async def _dev_channels_guard(ctx: Ctx) -> Verdict:
    channels = dev_channels.listed_channels(ctx.dialog)
    if channels != (dev_channels.OUR_CHANNEL,):
        return Verdict(DECLINE, "other_channels")
    ours = dev_channels.launched_with_our_flag(ctx.pane_pid, await asyncio.to_thread(ctx.seams.rows))
    if ours is None:
        return Verdict(RETRY, "process_unmeasured")
    return Verdict(ALLOW, evidence="launch_flag") if ours else Verdict(DECLINE, "flag_not_ours")


async def _measured_folder(ctx: Ctx) -> Tuple[Optional[str], Optional[str]]:
    info = await ctx.info(ctx.session_id)
    work = getattr(getattr(info, "session", None), "working_dir", None)
    if info is None or not work or getattr(info, "agent_family", None) != "claude" or getattr(info, "startup_gate", None) != GATE_AWAITING:
        return None, None
    return str(work), os.path.realpath(str(work))


def _scope_evidence(ctx: Ctx, folder: str) -> Optional[str]:
    if ctx.scope == catalog.SCOPE_EVERY:
        return "any_folder"
    return "project" if ctx.seams.in_projects(folder) else None


async def _folder_trust_guard(ctx: Ctx) -> Verdict:
    work, folder = await _measured_folder(ctx)
    if work is None or folder is None:
        return Verdict(WAIT, "not_measured")
    carried = await asyncio.to_thread(ctx.seams.lookup, folder)
    evidence = "carried" if carried is not None else await asyncio.to_thread(_scope_evidence, ctx, folder)
    if evidence is None:
        return Verdict(DECLINE, "not_a_project")
    if plain_dialog_folder(ctx.dialog) is None:
        return Verdict(RETRY, "not_plain")
    if not shows_folder(ctx.dialog, work):
        return Verdict(DECLINE, "other_folder")
    return Verdict(ALLOW, evidence=evidence)


async def _external_imports_guard(ctx: Ctx) -> Verdict:
    work, folder = await _measured_folder(ctx)
    if work is None or folder is None:
        return Verdict(WAIT, "not_measured")
    if await asyncio.to_thread(ctx.seams.lookup_imports, folder):
        return Verdict(ALLOW, evidence="carried")
    if await asyncio.to_thread(ctx.seams.lookup, folder) is not None:
        return Verdict(DECLINE, "carried_not_approved")
    evidence = await asyncio.to_thread(_scope_evidence, ctx, folder)
    return Verdict(ALLOW, evidence=evidence) if evidence else Verdict(DECLINE, "not_a_project")


TRUST_PERMISSIONS_LABELS = frozenset({"No, continue without these permissions", carried_trust.YES_LABEL})
BYPASS_ACCEPT_LABEL: str = "Yes, I accept"
BYPASS_LABELS = frozenset({"No, exit", BYPASS_ACCEPT_LABEL})
MCP_APPROVE_LABEL: str = "Use this MCP server"
MCP_LABELS = frozenset({MCP_APPROVE_LABEL, "Use this and all future MCP servers in this project", "Continue without using this MCP server"})
_WORKSPACE_HEAD = "Accessingworkspace:"
_WORKSPACE_TAIL = "Quicksafetycheck:"


def _row_labels(dialog: Any) -> frozenset:
    return frozenset(str(getattr(r, "label", "")).strip() for r in getattr(dialog, "rows", ()))


def is_trust_permissions_dialog(dialog: Any) -> bool:
    return (dialog is not None and getattr(dialog, "family", None) == "claude" and getattr(dialog, "startup_kind", None) == SCREEN_TRUST
            and _row_labels(dialog) == TRUST_PERMISSIONS_LABELS and len(dialog.rows) == len(TRUST_PERMISSIONS_LABELS))


def is_bypass_dialog(dialog: Any) -> bool:
    return (dialog is not None and getattr(dialog, "family", None) == "claude" and getattr(dialog, "startup_kind", None) == SCREEN_BYPASS_PERMISSIONS
            and _row_labels(dialog) == BYPASS_LABELS and len(dialog.rows) == len(BYPASS_LABELS))


def is_mcp_server_dialog(dialog: Any) -> bool:
    return (dialog is not None and getattr(dialog, "family", None) == "claude" and getattr(dialog, "startup_kind", None) == SCREEN_MCP_SERVER
            and _row_labels(dialog) == MCP_LABELS and len(dialog.rows) == len(MCP_LABELS) and mcp_installed.server_name(dialog.question) is not None)


def is_mcp_servers_dialog(dialog: Any) -> bool:
    return (dialog is not None and getattr(dialog, "family", None) == "claude" and getattr(dialog, "startup_kind", None) == SCREEN_MCP_SERVER
            and getattr(dialog, "multi_select", False) is True and bool(dialog.rows) and dialog.rows[-1].label == mcp_multi.SUBMIT_LABEL
            and len(dialog.rows) >= 3 and all(r.role == "option" for r in dialog.rows[:-1]))


def _variant_shows_folder(dialog: Any, folder: str) -> bool:
    kept = [re.sub(r"^[❯›>]\s*", "", ln.strip()) for ln in str(dialog.body).splitlines()]
    text = "".join(re.sub(r"\s+", "", ln) for ln in kept if ln and not set(ln) <= {"─", "-", "━"})
    at = text.find(_WORKSPACE_HEAD)
    return at >= 0 and any(text[at:].startswith(_WORKSPACE_HEAD + re.sub(r"\s+", "", shown) + _WORKSPACE_TAIL)
                           for shown in {folder, os.path.realpath(folder)})


async def _trust_permissions_guard(ctx: Ctx) -> Verdict:
    work, folder = await _measured_folder(ctx)
    if work is None or folder is None:
        return Verdict(WAIT, "not_measured")
    carried = await asyncio.to_thread(ctx.seams.lookup, folder)
    evidence = "carried" if carried is not None else await asyncio.to_thread(_scope_evidence, ctx, folder)
    if evidence is None:
        return Verdict(DECLINE, "not_a_project")
    if not _variant_shows_folder(ctx.dialog, work):
        return Verdict(DECLINE, "not_this_folder")
    return Verdict(ALLOW, evidence=evidence)


async def _bypass_accept_guard(ctx: Ctx) -> Verdict:
    return Verdict(ALLOW, evidence="beast_on")


async def _mcp_server_guard(ctx: Ctx) -> Verdict:
    work, folder = await _measured_folder(ctx)
    if work is None or folder is None:
        return Verdict(WAIT, "not_measured")
    name = mcp_installed.server_name(ctx.dialog.question)
    if name is None or not await asyncio.to_thread(ctx.seams.mcp_installed, work, name):
        return Verdict(DECLINE, "not_installed")
    return Verdict(ALLOW, evidence="installed")


async def _mcp_servers_guard(ctx: Ctx) -> Verdict:
    work, folder = await _measured_folder(ctx)
    if work is None or folder is None:
        return Verdict(WAIT, "not_measured")
    names = tuple(r.label for r in ctx.dialog.rows[:-1])
    for name in names:
        if not await asyncio.to_thread(ctx.seams.mcp_installed, work, name):
            return Verdict(DECLINE, "not_installed")
    return Verdict(ALLOW, evidence="installed", options=names)


async def _chrome_accept_guard(ctx: Ctx) -> Verdict:
    return Verdict(ALLOW, evidence="beast_on")


async def _chrome_decline_guard(ctx: Ctx) -> Verdict:
    return Verdict(ALLOW, evidence="decline_only")


RULES: Tuple[ScreenRule, ...] = (
    ScreenRule(catalog.info_for(catalog.RULE_DEV_CHANNELS), dev_channels.is_dev_channels_dialog, DEV_CHANNELS_ACCEPT,
               _dev_channels_guard, needs_pid=True),
    ScreenRule(catalog.info_for(catalog.RULE_FOLDER_TRUST), is_claude_trust_dialog, carried_trust.YES_LABEL,
               _folder_trust_guard, needs_gate=True),
    ScreenRule(catalog.info_for(catalog.RULE_EXTERNAL_IMPORTS), lambda d: not is_claude_trust_dialog(d) and is_plain_imports_dialog(d),
               carried_trust.IMPORTS_YES_LABEL, _external_imports_guard, needs_gate=True),
    ScreenRule(catalog.info_for(catalog.RULE_CHROME_ACCEPT), is_chrome_prompt, CHROME_ACCEPT_LABEL, _chrome_accept_guard),
    ScreenRule(catalog.info_for(catalog.RULE_CHROME_DECLINE), is_chrome_prompt, CHROME_DECLINE_LABEL, _chrome_decline_guard),
    ScreenRule(catalog.info_for(catalog.RULE_TRUST_PERMISSIONS), is_trust_permissions_dialog, carried_trust.YES_LABEL,
               _trust_permissions_guard, needs_gate=True),
    ScreenRule(catalog.info_for(catalog.RULE_BYPASS_ACCEPT), is_bypass_dialog, BYPASS_ACCEPT_LABEL, _bypass_accept_guard),
    ScreenRule(catalog.info_for(catalog.RULE_MCP_SERVER), is_mcp_server_dialog, MCP_APPROVE_LABEL, _mcp_server_guard, needs_gate=True),
    ScreenRule(catalog.info_for(catalog.RULE_MCP_SERVER), is_mcp_servers_dialog, mcp_multi.SUBMIT_LABEL, _mcp_servers_guard, needs_gate=True),
)


def rules_for(dialog: Any) -> Tuple[ScreenRule, ...]:
    return tuple(rule for rule in RULES if dialog is not None and rule.matches(dialog))


def rule_for(dialog: Any) -> Optional[ScreenRule]:
    return next((rule for rule in RULES if dialog is not None and rule.matches(dialog)), None)
