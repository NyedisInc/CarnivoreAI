
from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

import structlog

from src.core.db import get_meta, set_meta, transaction
from src.core.mcp import agent_tool_switches
from src.core.skill_watch.store import default_watch_store
from src.core.skills import bundled_install
from src.core.skills.bundled_install import BundledSkillError
from src.core.skills.ledger_types import GLOBAL_PROJECT_PATH, SCOPE_GLOBAL

logger = structlog.get_logger()

DECLINED_META_KEY = "skills_required_declined"

STATE_INSTALLED = "installed"
STATE_DECLINED = "declined"
STATE_AVAILABLE = "available"
STATE_BLOCKED = "blocked"

ACTION_INSTALLED = "installed"
ACTION_ADOPTED = "adopted"
ACTION_UPDATED = "updated"
ACTION_NONE = "none"
ACTION_REFUSED = "refused"
ACTION_WITHDRAWN = "withdrawn"
ACTION_KEPT = "kept"


@dataclass(frozen=True)
class RequiredSkill:

    item_id: str
    folder: str
    required: bool = True
    switch: str = ""


SWITCH_TASK_MANAGER = "huddle"


REQUIRED_SKILLS: Tuple[RequiredSkill, ...] = (
    RequiredSkill("carnivore/huddle", "huddle", switch=SWITCH_TASK_MANAGER),
    RequiredSkill("carnivore/widget-builder", "widget-builder", required=False),
)

FIRST_PARTY_PUBLISHER = "carnivore"


def is_first_party(item_id: str) -> bool:
    return item_id.split("/", 1)[0] == FIRST_PARTY_PUBLISHER


def _entry(item_id: str) -> RequiredSkill:
    return next(s for s in REQUIRED_SKILLS if s.item_id == item_id)


def declined_ids(conn: sqlite3.Connection) -> frozenset:
    raw = get_meta(conn, DECLINED_META_KEY)
    if not raw:
        return frozenset()
    try:
        value = json.loads(raw)
    except ValueError:
        logger.warning("skills_required_declined_unreadable")
        return frozenset()
    return frozenset(str(v) for v in value) if isinstance(value, list) else frozenset()


def _write_declined(conn: sqlite3.Connection, ids: frozenset) -> None:
    with transaction(conn):
        set_meta(conn, DECLINED_META_KEY, json.dumps(sorted(ids)))


def mark_declined(conn: sqlite3.Connection, item_id: str) -> bool:
    if item_id not in {s.item_id for s in REQUIRED_SKILLS}:
        return False
    current = declined_ids(conn)
    if item_id not in current:
        _write_declined(conn, current | {item_id})
    logger.info("skills_required_declined", item_id=item_id)
    return True


def clear_declined(conn: sqlite3.Connection, item_id: str) -> None:
    current = declined_ids(conn)
    if item_id in current:
        _write_declined(conn, current - {item_id})


@dataclass(frozen=True)
class RequiredState:

    item_id: str
    state: str
    install_id: Optional[str] = None
    local_edits: Optional[bool] = None


def required_states(services: Any) -> List[RequiredState]:
    out: List[RequiredState] = []
    with closing(services.catalog.open_db()) as conn:
        declined = declined_ids(conn)
    with services.catalog.ledger() as ledger:
        rows = {e.item_id: ledger.find(e.item_id, SCOPE_GLOBAL, GLOBAL_PROJECT_PATH) for e in REQUIRED_SKILLS}
    for entry in REQUIRED_SKILLS:
        row = rows[entry.item_id]
        if row is not None:
            out.append(RequiredState(entry.item_id, STATE_INSTALLED, row.install_id, bundled_install.local_edits(services, row)))
        elif entry.item_id in declined:
            out.append(RequiredState(entry.item_id, STATE_DECLINED))
        else:
            name = entry.item_id.split("/", 1)[1]
            digest = bundled_install.bundled_digest(entry.folder)
            blocked = not bundled_install.plan_copies(services, name, digest)
            out.append(RequiredState(entry.item_id, STATE_BLOCKED if blocked else STATE_AVAILABLE))
    return out


def install_one(services: Any, item_id: str) -> str:
    outcome, _row = bundled_install.install_bundled(services, item_id, _entry(item_id).folder)
    return ACTION_ADOPTED if outcome == bundled_install.OUTCOME_ADOPTED else ACTION_INSTALLED


def _refresh_one(services: Any, item_id: str) -> str:
    with services.catalog.ledger() as ledger:
        row = ledger.find(item_id, SCOPE_GLOBAL, GLOBAL_PROJECT_PATH)
    if row is None:
        return ACTION_NONE
    outcome = bundled_install.refresh_bundled(services, row, _entry(item_id).folder)
    return ACTION_UPDATED if outcome == bundled_install.OUTCOME_UPDATED else ACTION_NONE


def switched_off(entry: RequiredSkill) -> bool:
    return entry.switch == SWITCH_TASK_MANAGER and not agent_tool_switches.current().huddle


def _withdraw_one(services: Any, item_id: str) -> str:
    with services.catalog.ledger() as ledger:
        row = ledger.find(item_id, SCOPE_GLOBAL, GLOBAL_PROJECT_PATH)
    if row is None:
        return ACTION_NONE
    if bundled_install.withdraw_bundled(services, row) != bundled_install.OUTCOME_WITHDRAWN:
        return ACTION_KEPT
    try:
        default_watch_store().forget(row.install_id)
    except sqlite3.Error as exc:
        logger.warning("skills_required_watch_forget_failed", item_id=item_id, error=str(exc)[:300])
    return ACTION_WITHDRAWN


def _gated_action(services: Any, state: RequiredState) -> str:
    if state.state == STATE_INSTALLED:
        return _withdraw_one(services, state.item_id)
    if state.state == STATE_BLOCKED:
        logger.info("skills_required_switched_off_foreign_folder_kept", item_id=state.item_id)
    return ACTION_NONE


async def ensure_required(services: Any) -> List[Tuple[str, str]]:
    results: List[Tuple[str, str]] = []
    try:
        states = await asyncio.to_thread(required_states, services)
    except (OSError, sqlite3.Error, BundledSkillError) as exc:
        logger.warning("skills_required_unreadable", error=type(exc).__name__, detail=str(exc)[:300])
        return results
    for state in states:
        action = ACTION_NONE
        try:
            if switched_off(_entry(state.item_id)):
                action = await asyncio.to_thread(_gated_action, services, state)
            elif state.state == STATE_AVAILABLE and _entry(state.item_id).required:
                action = await asyncio.to_thread(install_one, services, state.item_id)
            elif state.state == STATE_INSTALLED and not state.local_edits:
                action = await asyncio.to_thread(_refresh_one, services, state.item_id)
        except (BundledSkillError, OSError, sqlite3.Error) as exc:
            action = ACTION_REFUSED
            logger.warning("skills_required_install_refused", item_id=state.item_id,
                           error=type(exc).__name__, detail=str(exc)[:300])
        logger.info("skills_required_entry", item_id=state.item_id, state=state.state,
                    local_edits=state.local_edits, action=action)
        results.append((state.item_id, action))
    return results
