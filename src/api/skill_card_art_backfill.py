
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import structlog

from src.api.skills_manager_routes import _inventory_now, _profiles
from src.core.skill_manager import card_art, card_summary
from src.core.skills.project_scope import ProjectPathRefused, known_project_roots

logger = structlog.get_logger()


def _all_keys(app: Any, profiles: list, snapshot: Any) -> set:
    scopes = [None]
    try:
        scopes += sorted(known_project_roots(app.state.services.settings_reader.state_dir()))
    except ProjectPathRefused as exc:
        logger.warning("skill_card_summary_projects_unreadable", error=type(exc).__name__)
        return set()
    keys: set = set()
    for profile in profiles:
        for scope in scopes:
            inventory = _inventory_now(SimpleNamespace(app=app), profiles, profile.profile_id, scope, snapshot)
            keys |= card_summary.current_keys(loc for group in inventory["skills"] for loc in group["locations"])
    return keys


def _project_locations(app: Any, profiles: list, snapshot: Any) -> list:
    try:
        roots = sorted(known_project_roots(app.state.services.settings_reader.state_dir()))
    except ProjectPathRefused as exc:
        logger.warning("skill_card_summary_projects_unreadable", error=type(exc).__name__)
        return []
    found = []
    for root in roots:
        inventory = _inventory_now(SimpleNamespace(app=app), profiles, None, root, snapshot)
        found += [loc for group in inventory["skills"] for loc in group["locations"]]
    return found


async def queue_missing(app: Any) -> int:
    try:
        if not (await asyncio.to_thread(card_art.enabled) or await asyncio.to_thread(card_summary.enabled)):
            return 0
        profiles = await asyncio.to_thread(_profiles, Path.home())
        snapshot = await app.state.services.catalog.index_cache.get()
        inventory = await asyncio.to_thread(_inventory_now, SimpleNamespace(app=app), profiles, None, None, snapshot)
        locations = [loc for group in inventory["skills"] for loc in group["locations"]]
        queued = await asyncio.to_thread(card_art.annotate, locations)
        projects = await asyncio.to_thread(_project_locations, app, profiles, snapshot)
        queued += await asyncio.to_thread(card_summary.annotate, locations + projects)
        if card_summary.enabled():
            keys = await asyncio.to_thread(_all_keys, app, profiles, snapshot)
            if keys:
                await asyncio.to_thread(card_summary.prune, keys)
        return queued
    except Exception as exc:
        logger.warning("skill_card_art_backfill_failed", error=type(exc).__name__)
        return 0
