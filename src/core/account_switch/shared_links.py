
from __future__ import annotations

import filecmp
import os
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import structlog

from src.config.provider_accounts import DEFAULT_CLAUDE_CONFIG_DIR

logger = structlog.get_logger()

SHARED_ROOTS: Dict[str, str] = {"claude": DEFAULT_CLAUDE_CONFIG_DIR}

REQUIRED_ENTRY: Dict[str, str] = {"claude": "projects"}

MUST_SHARE: Dict[str, Tuple[str, ...]] = {
    "claude": ("projects", "sessions", "settings.json"),
}

CREATE_IF_MISSING: Tuple[str, ...] = ("projects", "sessions")

SHARED_ENTRIES: Dict[str, Tuple[str, ...]] = {
    "claude": (
        "projects",
        "sessions",
        "settings.json",
        "CLAUDE.md",
        "agents",
        "commands",
        "skills",
        "plugins",
        "hooks",
        "output-styles",
        "file-history",
        "todos",
        "keybindings.json",
        "plans",
        "ide",
    ),
}

MIGRATE_INTO_SHARED: Tuple[str, ...] = ("plans",)

LINKED = "linked"
ALREADY_LINKED = "already_linked"
PRESENT = "present"
FOREIGN_LINK = "foreign_link"
ABSENT = "absent"
SOURCE_MISSING = "source_missing"
FAILED = "failed"
PROFILE_UNAVAILABLE = "profile_unavailable"


@dataclass(frozen=True)
class LinkReport:

    profile: str
    provider: str
    default: bool
    entries: Dict[str, str] = field(default_factory=dict)
    resume_safe: bool = False


def _expanded(path: str) -> str:
    return os.path.normpath(os.path.expanduser(path))


def shared_root(provider: str) -> str:
    return os.path.realpath(_expanded(SHARED_ROOTS[provider]))


def is_default_profile(provider: str, profile_dir: str) -> bool:
    return _expanded(profile_dir) == _expanded(SHARED_ROOTS[provider])


def entry_status(profile_dir: str, provider: str, entry: str) -> str:
    target = os.path.join(_expanded(profile_dir), entry)
    source = os.path.join(shared_root(provider), entry)
    if not os.path.lexists(target):
        return ABSENT
    if os.path.islink(target):
        if os.path.realpath(target) == os.path.realpath(source):
            return ALREADY_LINKED
        return FOREIGN_LINK
    return PRESENT


def resume_safe(profile_dir: str, provider: str) -> bool:
    if is_default_profile(provider, profile_dir):
        return True
    return all(
        entry_status(profile_dir, provider, entry) == ALREADY_LINKED
        for entry in MUST_SHARE[provider]
    )


def _free_name(directory: str, name: str, tag: str) -> str:
    stem, suffix = os.path.splitext(name)
    candidate, n = f"{stem}.{tag}{suffix}", 2
    while os.path.lexists(os.path.join(directory, candidate)):
        candidate, n = f"{stem}.{tag}-{n}{suffix}", n + 1
    return candidate


def _move_no_overwrite(src: str, dest: str) -> None:
    if os.path.isfile(src) and not os.path.islink(src):
        os.link(src, dest)
        os.unlink(src)
        return
    if os.path.lexists(dest):
        raise FileExistsError(dest)
    os.rename(src, dest)


def _migrate_into_shared(own: str, shared: str, tag: str) -> bool:
    moved = 0
    try:
        os.makedirs(shared, mode=0o700, exist_ok=True)
        for name in sorted(os.listdir(own)):
            src = os.path.join(own, name)
            dest = os.path.join(shared, name)
            if os.path.lexists(dest):
                if (
                    os.path.isfile(src) and not os.path.islink(src)
                    and os.path.isfile(dest) and not os.path.islink(dest)
                    and filecmp.cmp(src, dest, shallow=False)
                ):
                    os.unlink(src)
                    continue
                dest = os.path.join(shared, _free_name(shared, name, tag))
            _move_no_overwrite(src, dest)
            moved += 1
        os.rmdir(own)
    except OSError as exc:
        logger.warning(
            "account_switch_migrate_failed",
            entry=os.path.basename(own),
            moved=moved,
            error=type(exc).__name__,
        )
        return False
    logger.info("account_switch_migrated", entry=os.path.basename(own), moved=moved)
    return True


def _link_one(profile: str, provider: str, entry: str) -> str:
    target = os.path.join(profile, entry)
    source = os.path.join(shared_root(provider), entry)
    if os.path.lexists(target) and not (
        entry in MIGRATE_INTO_SHARED
        and os.path.isdir(target)
        and not os.path.islink(target)
        and _migrate_into_shared(target, source, os.path.basename(profile))
    ):
        return entry_status(profile, provider, entry)
    if not os.path.lexists(source):
        if entry not in CREATE_IF_MISSING:
            return SOURCE_MISSING
        try:
            os.makedirs(source, mode=0o700, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "account_switch_shared_dir_unavailable",
                provider=provider,
                entry=entry,
                error=type(exc).__name__,
            )
            return FAILED
    try:
        os.symlink(os.path.realpath(source), target)
    except FileExistsError:
        return entry_status(profile, provider, entry)
    except OSError as exc:
        logger.warning(
            "account_switch_link_failed",
            provider=provider,
            entry=entry,
            error=type(exc).__name__,
        )
        return FAILED
    return LINKED


def ensure_shared_links(
    profile_dir: str, provider: str, *, managed: bool
) -> LinkReport:
    if is_default_profile(provider, profile_dir):
        return LinkReport(profile=profile_dir, provider=provider, default=True, resume_safe=True)
    profile = _expanded(profile_dir)
    entries: Dict[str, str] = {}
    usable = managed and os.path.isdir(profile) and not os.path.islink(profile)
    for entry in SHARED_ENTRIES[provider]:
        if usable:
            entries[entry] = _link_one(profile, provider, entry)
        else:
            entries[entry] = (
                entry_status(profile, provider, entry)
                if os.path.isdir(profile)
                else PROFILE_UNAVAILABLE
            )
    created: List[str] = [name for name, state in entries.items() if state == LINKED]
    if created:
        logger.info(
            "account_switch_links_created",
            provider=provider,
            entries=created,
        )
    safe = all(entries.get(entry) in (LINKED, ALREADY_LINKED) for entry in MUST_SHARE[provider])
    return LinkReport(
        profile=profile_dir,
        provider=provider,
        default=False,
        entries=entries,
        resume_safe=safe,
    )
