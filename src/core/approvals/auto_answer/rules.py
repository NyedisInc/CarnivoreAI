
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Sequence, Tuple

import structlog

from src.core.approvals import carried_trust, dev_channels
from src.core.approvals.auto_answer import catalog
from src.core.approvals.extract import CHROME_DECLINE_LABEL, DEV_CHANNELS_ACCEPT, is_chrome_prompt
from src.core.swarm.auto_trust import GATE_AWAITING, is_claude_trust_dialog, is_plain_imports_dialog, shows_folder

logger = structlog.get_logger()

ALLOW, DECLINE, WAIT, RETRY = "allow", "decline", "wait", "retry"


@dataclass(frozen=True)
class Verdict:

    outcome: str
    reason: str = ""
    evidence: str = ""


@dataclass(frozen=True)
class Seams:

    rows: Callable[[], Optional[Sequence[Any]]]
    lookup: Callable[[str], Optional[str]]
    lookup_imports: Callable[[str], bool]
    in_projects: Callable[[str], bool]


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
    if not shows_folder(ctx.dialog, work):
        return Verdict(DECLINE, "not_plain")
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


async def _chrome_decline_guard(ctx: Ctx) -> Verdict:
    return Verdict(ALLOW, evidence="decline_only")


RULES: Tuple[ScreenRule, ...] = (
    ScreenRule(catalog.info_for(catalog.RULE_DEV_CHANNELS), dev_channels.is_dev_channels_dialog, DEV_CHANNELS_ACCEPT,
               _dev_channels_guard, needs_pid=True),
    ScreenRule(catalog.info_for(catalog.RULE_FOLDER_TRUST), is_claude_trust_dialog, carried_trust.YES_LABEL,
               _folder_trust_guard, needs_gate=True),
    ScreenRule(catalog.info_for(catalog.RULE_EXTERNAL_IMPORTS), lambda d: not is_claude_trust_dialog(d) and is_plain_imports_dialog(d),
               carried_trust.IMPORTS_YES_LABEL, _external_imports_guard, needs_gate=True),
    ScreenRule(catalog.info_for(catalog.RULE_CHROME_DECLINE), is_chrome_prompt, CHROME_DECLINE_LABEL, _chrome_decline_guard),
)


def rule_for(dialog: Any) -> Optional[ScreenRule]:
    return next((rule for rule in RULES if dialog is not None and rule.matches(dialog)), None)
